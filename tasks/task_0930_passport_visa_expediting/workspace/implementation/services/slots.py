"""AppointmentSlot capacity + status derivation (PRD 3.3).

The closure verdict dominates: a slot whose calendar date is closed stays
CLOSED regardless of booked_count.
"""
import clock
import store


def derive_status(slot, consulate):
    day = clock.render_date(slot["starts_at"].date())
    if consulate is not None and day in (consulate.get("closure_dates") or []):
        return "CLOSED"
    if slot["booked_count"] >= slot["capacity"]:
        return "FULL"
    return "OPEN"


def redrive(slot, consulate=None, bump=False):
    if consulate is None:
        consulate = store.get("consulates", slot["consulate_id"])
    status = derive_status(slot, consulate)
    changed = slot["status"] != status
    slot["status"] = status
    if changed and bump:
        store.touch(slot)
    return changed


def take_seat(slot, bump=True):
    slot["booked_count"] += 1
    redrive(slot)
    if bump:
        store.touch(slot)


def release_seat(slot, bump=True):
    if slot["booked_count"] > 0:
        slot["booked_count"] -= 1
    redrive(slot)
    if bump:
        store.touch(slot)
