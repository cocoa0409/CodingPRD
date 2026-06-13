"""Device cascade helpers (PRD 3.6, 3.7).

System cascades issue STARTER_DISABLE / STARTER_ENABLE commands with a
zero-length window at the current clock time. They bypass the public-endpoint
preconditions and the window-overlap check, applying their effect idempotently.
Each command record and the device itself are mutated (version bump on device).
"""
import db
from clock import get_now
from timeutil import iso_now


def _new_command(device, command_type):
    now = get_now()
    iso = iso_now(now)
    cmd = db.common_fields(with_version=True)
    cmd.update({
        "device_id": device["id"],
        "command_type": command_type,
        "effective_start": iso,
        "effective_end": iso,
        "status": "ISSUED",
    })
    db.device_commands[cmd["id"]] = cmd
    return cmd


def cascade_starter_disable(device):
    """Issue a STARTER_DISABLE cascade: starter_state=DISABLED, count += 1 (idempotent)."""
    if device is None:
        return None
    cmd = _new_command(device, "STARTER_DISABLE")
    device["starter_state"] = "DISABLED"
    device["active_disable_count"] = device["active_disable_count"] + 1
    db.touch(device)
    return cmd


def cascade_starter_enable(device, reset_to_zero=False):
    """Issue a STARTER_ENABLE cascade.

    reset_to_zero=False: active_disable_count -= 1 (floor 0)   [DELINQUENT cure]
    reset_to_zero=True : active_disable_count reset to 0       [DEFAULT cure / redemption]
    """
    if device is None:
        return None
    cmd = _new_command(device, "STARTER_ENABLE")
    device["starter_state"] = "ENABLED"
    if reset_to_zero:
        device["active_disable_count"] = 0
    else:
        device["active_disable_count"] = max(0, device["active_disable_count"] - 1)
    db.touch(device)
    return cmd
