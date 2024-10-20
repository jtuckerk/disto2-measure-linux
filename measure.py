"""This script sets up "keyboard mode" on a leica disto D2 laser measuring device for linux machines

This script sets up the device such that a single press causes the laser to turn on for <AIM_DELAY>
seconds and then measures and outputs the measurement to the keyboard in mm.

in addition to python and the below imported packages xdotool is also needed.

for running this on something other than linux only the send_keys and send_enter functions should
need to be updated


"""

import asyncio
from bleak import BleakScanner, BleakClient
import struct
import signal
import subprocess

## 67 measures and 6F turns on the laser

# wait 1.5 seconds before measure to give time to aim the laser
AIM_DELAY = 1.5


def send_keys(keys):
    try:
        subprocess.call(['xdotool', 'type', keys])
    except Exception as e:
        print("failed to type", str(e))

def send_enter():
    try:
        subprocess.call(['xdotool', 'key', 'Return'])
    except Exception as e:
        print("failed to type", str(e))


async def scan_and_connect(service_uuid="3ab10100-f831-4395-b29d-570977d5bf94"):
    """
    Scans for BLE devices advertising the specified service UUID and connects to the first one found.

    Args:
        service_uuid: The service UUID to filter the scan results.

    Returns:
        The connected BleakClient object, or None if no connection was established.
    """
    try:
        print("Scanning for devices with service UUID:", service_uuid)

        # 1. Scan for devices
        devices = await BleakScanner.discover()

        target_device = None
        for d in devices:
            print(f"Found device: {d.address} - {d.name}")
            if service_uuid.lower() in d.metadata["uuids"]:  # Case-insensitive comparison
                target_device = d
                break

        if not target_device:
            print("Target device not found.")
            return None

        # 2. Connect to the target device
        print(f"Connecting to {target_device.name}...")
        client = BleakClient(target_device.address)
        await client.connect()
        print("Connected!")

        return client

    except Exception as e:
        print("Error scanning or connecting:", e)
        return None



# Characteristic UUIDs (replace with actual ones if different)
DISTANCE_CHARACTERISTIC_UUID = "3AB10101-F831-4395-B29D-570977D5BF94"
COMMAND_CHARACTERISTIC_UUID = "3AB10109-F831-4395-B29D-570977d5BF94"


async def do_measure(client):
    """Allows interactive input and sending of commands to the BLE device."""
    command_characteristic = client.services.get_characteristic(COMMAND_CHARACTERISTIC_UUID)
    if not command_characteristic:
        print("Command characteristic not found.")
        return

    laser_on = bytes.fromhex("6F")
    measure = bytes.fromhex("67")

    await client.write_gatt_char(command_characteristic, laser_on)
    await asyncio.sleep(AIM_DELAY)
    await client.write_gatt_char(command_characteristic, measure)

async def clear_device(client):
    """Allows interactive input and sending of commands to the BLE device."""
    command_characteristic = client.services.get_characteristic(COMMAND_CHARACTERISTIC_UUID)
    if not command_characteristic:
        print("Command characteristic not found.")
        return

    laser_off = bytes.fromhex("70")
    await client.write_gatt_char(command_characteristic, laser_off)




def notification_wrapper(client):
    async def handle_distance_notification(sender, data):
        """Callback function to process distance notifications."""
        # Decode the data assuming it's a 4-byte little-endian float
        print("received event")
        global miss_counter

        if not button_clicked.is_set():
            button_clicked.set()
            async with counter_lock:
                miss_counter +=1

            async with counter_lock:
                if miss_counter > 1:
                    # Since this script is a bit of a hack to allow us to measure with a delay after
                    # clicking the measure button we rely on the button_clicked variable only being
                    # set between when the button is clicked and when a measurement is taken.
                    # if somehow we get in a state where the button is clicked multiple times without
                    # any measurements being taken then we need to reset the variable and the device
                    print("bad state")
                    button_clicked.clear()
                    await clear_device(client)
                    return
            await do_measure(client)
            return

        async with counter_lock:
            miss_counter = 0
        distance_meters = struct.unpack("<f", data)[0]

        # Convert to millimeters
        distance_mm = distance_meters * 1000

        print(f"Distance: {distance_mm:.1f} mm")  # Adjust '.3f' for desired precision
        send_keys(f"{distance_mm:.1f}")
        send_enter()

        button_clicked.clear()
    return handle_distance_notification

async def handle_notifications(client):
    """Handles distance notifications from the BLE device."""
    distance_characteristic = client.services.get_characteristic(DISTANCE_CHARACTERISTIC_UUID)
    if not distance_characteristic:
        print("Distance characteristic not found.")
        return

    measure_callback = notification_wrapper(client)
    await client.start_notify(distance_characteristic, measure_callback)

    # Keep the connection alive to receive notifications until a keyboard interrupt
    await disconnect_event.wait()


# Shared Event for button click status
button_clicked = asyncio.Event()
disconnect_event = asyncio.Event()


def handle_keyboard_interrupt():
    """Handles keyboard interrupts (Ctrl+C) to gracefully disconnect."""
    print("Keyboard interrupt detected. Disconnecting...")
    disconnect_event.set()  # Signal the disconnect event

miss_counter = 0
counter_lock = asyncio.Lock()

async def main():
    client = await scan_and_connect()
    if client:
        try:
            await clear_device(client)
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGINT, handle_keyboard_interrupt)

            # Run notification handling and command input concurrently
            await handle_notifications(client)
        except Exception as e:
            print("Error:", e)
        finally:
            await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())