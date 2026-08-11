"""Single-token custody: the append-only chain and its exclusivity invariant (PRD 2.7)."""
import clock
import store
from services import lookup


def open_event(order):
    for row in lookup.custody_events_of(order):
        if row["released_at"] is None:
            return row
    return None


def append_first(order, holder_type, reason):
    """Order creation opens the chain -- no prior row to release."""
    row = {
        "order_id": order["id"],
        "holder_type": holder_type,
        "leg_index": None,
        "acquired_at": clock.now(),
        "released_at": None,
        "reason": reason,
    }
    store.insert("custody_events", row)
    order["custody_holder"] = holder_type
    return row


def handover(order, holder_type, reason, leg_index=None):
    """Stamp released_at on the open row, then append the new row at that instant."""
    instant = clock.now()
    current = open_event(order)
    if current is not None:
        current["released_at"] = instant
    row = {
        "order_id": order["id"],
        "holder_type": holder_type,
        "leg_index": leg_index,
        "acquired_at": instant,
        "released_at": None,
        "reason": reason,
    }
    store.insert("custody_events", row)
    order["custody_holder"] = holder_type
    return row


def open_count(order):
    return len([r for r in lookup.custody_events_of(order) if r["released_at"] is None])
