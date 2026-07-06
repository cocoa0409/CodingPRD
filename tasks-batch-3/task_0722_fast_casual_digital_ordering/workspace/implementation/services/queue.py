"""Store queue_status recomputation (PRD §2.7, §1.3 queue_status)."""
from db import db, parse_iso

BUSY_THRESHOLD = 0.70
SURGE_THRESHOLD = 1.0


def recompute_queue_status(store):
    """Derive queue_status from the most-loaded active slot.

    Active slot: window_start_utc <= clock_now < window_end_utc AND not is_closed.
    Recomputation is a mutation of the store (touch).
    """
    clock = db.clock_dt()
    capacity = store["throughput_capacity_per_slot"]
    load_ratio = 0.0
    for slot in db.pickup_slots.values():
        if slot["store_id"] != store["id"]:
            continue
        if slot.get("is_closed"):
            continue
        start = parse_iso(slot["window_start_utc"])
        end = parse_iso(slot["window_end_utc"])
        if start <= clock < end:
            if capacity > 0:
                ratio = slot["reserved_count"] / capacity
            else:
                ratio = 0.0
            if ratio > load_ratio:
                load_ratio = ratio

    if load_ratio >= SURGE_THRESHOLD:
        status = "SURGE"
    elif load_ratio >= BUSY_THRESHOLD:
        status = "BUSY"
    else:
        status = "OPEN"

    if store.get("queue_status") != status:
        store["queue_status"] = status
        db.touch(store)
    return status
