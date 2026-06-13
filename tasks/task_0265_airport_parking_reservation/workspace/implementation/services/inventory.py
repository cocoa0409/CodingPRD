"""Typed stall inventory reconciliation (PRD §2.5)."""
from db import store
from services.records import touch

_CAP_FIELD = {
    "STANDARD": "standard_capacity",
    "OVERSIZED": "oversized_capacity",
    "EV": "ev_capacity",
}
_AVAIL_FIELD = {
    "STANDARD": "available_standard_count",
    "OVERSIZED": "available_oversized_count",
    "EV": "available_ev_count",
}


def available_count(lot, stall_class):
    return lot[_AVAIL_FIELD[stall_class]]


def recompute_lot_availability(lot):
    """Recompute all three availability counters from active StallHolds.

    available_<C> = capacity_C - count(holds on lot with class C and status in
    {HELD, OCCUPIED}). Clamped at >= 0. Bumps the lot (updated_at + version).
    """
    counts = {"STANDARD": 0, "OVERSIZED": 0, "EV": 0}
    for hold in store.stall_holds.values():
        if hold["lot_id"] == lot["id"] and hold["status"] in ("HELD", "OCCUPIED"):
            counts[hold["stall_class"]] += 1
    for cls in ("STANDARD", "OVERSIZED", "EV"):
        avail = lot[_CAP_FIELD[cls]] - counts[cls]
        if avail < 0:
            avail = 0
        lot[_AVAIL_FIELD[cls]] = avail
    touch(lot)
