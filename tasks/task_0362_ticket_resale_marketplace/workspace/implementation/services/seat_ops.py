"""Seat allocation/release primitives. Each seat status change is a mutation
(bumps the seat's version/updated_at), and the parent listing reconciles afterward."""
import db


def seats_for_listing(listing_id):
    return [s for s in db.seats.values() if s["listing_id"] == listing_id]


def seats_for_order(order_id):
    return [s for s in db.seats.values() if s.get("order_id") == order_id]


def set_status(seat, status, order_id="__unset__"):
    seat["status"] = status
    if order_id != "__unset__":
        seat["order_id"] = order_id
    db.touch(seat)


def allocate_fifo(listing, quantity, order_id):
    """Take `quantity` AVAILABLE seats in FIFO order (created_at ASC, then id),
    moving them AVAILABLE -> HELD with order_id stamped. Returns the held seats.
    Caller is responsible for having validated availability first."""
    available = [s for s in seats_for_listing(listing["id"]) if s["status"] == "AVAILABLE"]
    available.sort(key=lambda s: (s["created_at"], s["id"]))
    chosen = available[:quantity]
    for s in chosen:
        set_status(s, "HELD", order_id=order_id)
    return chosen
