"""Seat-inventory ledger reconciliation (PRD 2.6, 3.x; scaffold calc seat_inventory).

Counters are derived from the live set of ACTIVE BookingLegs on a service date,
partitioned by their owning Booking's booking_status. Recompute bumps the
service date's version and updated_at whenever any counter changes.
"""
import db


def _live_counts(service_date_id):
    held = 0
    sold = 0
    for leg in db.booking_legs.values():
        if leg["service_date_id"] != service_date_id:
            continue
        if leg["leg_state"] != "ACTIVE":
            continue
        booking = db.bookings.get(leg["booking_id"])
        if booking is None:
            continue
        if booking["booking_status"] == "HELD":
            held += 1
        elif booking["booking_status"] == "CONFIRMED":
            sold += 1
    return held, sold


def recompute(service_date, bump_version=True):
    """Recompute seats_held/seats_sold/seats_available/load_factor.

    seats_available is an invariant that never goes negative (PRD 2.6).
    load_factor = seats_sold / seats_total (CONFIRMED only).
    When bump_version is True the service date's version increments and
    updated_at refreshes (PRD 2.6: 'Whenever any of these counters changes...').
    """
    held, sold = _live_counts(service_date["id"])
    available = service_date["seats_total"] - held - sold
    if available < 0:
        available = 0
    load_factor = sold / service_date["seats_total"]

    changed = (
        service_date["seats_held"] != held
        or service_date["seats_sold"] != sold
        or service_date["seats_available"] != available
        or service_date["load_factor"] != load_factor
    )
    service_date["seats_held"] = held
    service_date["seats_sold"] = sold
    service_date["seats_available"] = available
    service_date["load_factor"] = load_factor
    if bump_version and changed:
        db.touch(service_date)
    return service_date


def seat_taken(service_date_id, seat_number, exclude_leg_id=None):
    """True if seat_number is occupied by another ACTIVE leg on this service
    date (PRD 3.3 reserved-seat uniqueness)."""
    if seat_number is None:
        return False
    for leg in db.booking_legs.values():
        if leg["id"] == exclude_leg_id:
            continue
        if leg["service_date_id"] != service_date_id:
            continue
        if leg["leg_state"] != "ACTIVE":
            continue
        if leg.get("seat_number") == seat_number:
            return True
    return False
