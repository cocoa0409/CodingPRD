"""Derived-field recompute helpers used across state transitions."""


def recompute_slot_fill(slot):
    """fill_status = FULL when booked_count >= capacity, else OPEN (PRD §2.7)."""
    slot["fill_status"] = "FULL" if slot["booked_count"] >= slot["capacity"] else "OPEN"


def recompute_pickup_standing(customer):
    """Inclusive thresholds (PRD §2.9): >=4 BLOCKED, >=2 WATCH, else GOOD."""
    strikes = customer["no_show_strikes"]
    if strikes >= 4:
        customer["pickup_standing"] = "BLOCKED"
    elif strikes >= 2:
        customer["pickup_standing"] = "WATCH"
    else:
        customer["pickup_standing"] = "GOOD"


def lines_of(db, order_id):
    return [ln for ln in db.order_lines.values() if ln["order_id"] == order_id]


def hold_of(db, order_id):
    for h in db.holds.values():
        if h["order_id"] == order_id:
            return h
    return None
