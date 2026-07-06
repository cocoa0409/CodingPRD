"""ShowEvent seat recompute and OPEN<->SOLD_OUT bubble-up (PRD §3.3, §3.4).

seats_sold is derived: the sum of party_size over the show's ShowBookings in
{HELD, CONFIRMED}, plus the total_seats of GroupBookings in DEPOSIT_PAID (their
reserved block). seats_sold is recomputed whenever a booking changes state.
"""
from db import db


def recompute_seats_sold(show):
    """Recompute seats_sold from live booking/group state. Returns the value.

    Per SCAFFOLD ShowEvent.seats_sold: sum of party_size over ShowBookings in
    {HELD, CONFIRMED}. GroupBookings reserve total_seats once DEPOSIT_PAID
    (PRD §3.5: paying the deposit adds total_seats into seats_sold; cancelling
    from DEPOSIT_PAID subtracts it). So the derived total includes both.
    """
    total = 0
    for b in db.show_bookings.values():
        if b["show_event_id"] == show["id"] and b["status"] in ("HELD", "CONFIRMED"):
            total += b["party_size"]
    for g in db.group_bookings.values():
        if g["show_event_id"] == show["id"] and g["status"] == "DEPOSIT_PAID":
            total += g["total_seats"]
    show["seats_sold"] = total
    return total


def capacity_of(show):
    venue = db.venues.get(show["venue_id"])
    return venue["seated_capacity"] if venue else 0


def accessible_seats_of(show):
    venue = db.venues.get(show["venue_id"])
    return venue["accessible_seats"] if venue else 0


def accessible_seats_used(show, exclude_booking_id=None):
    """Sum of accessible_seats_requested over the show's occupying bookings.

    Counts ShowBookings in {HELD, CONFIRMED} against the show.
    """
    total = 0
    for b in db.show_bookings.values():
        if b["id"] == exclude_booking_id:
            continue
        if b["show_event_id"] == show["id"] and b["status"] in ("HELD", "CONFIRMED"):
            total += b.get("accessible_seats_requested", 0)
    return total


def bubble_after_recompute(show):
    """Apply OPEN<->SOLD_OUT auto-transition based on current seats_sold.

    Returns True if the status changed (caller still bumps version once for
    the whole seat-mutation operation; status change and recompute are part of
    one mutation).
    """
    cap = capacity_of(show)
    changed = False
    if show["status"] == "OPEN" and show["seats_sold"] >= cap:
        show["status"] = "SOLD_OUT"
        changed = True
    elif show["status"] == "SOLD_OUT" and show["seats_sold"] < cap:
        show["status"] = "OPEN"
        changed = True
    return changed
