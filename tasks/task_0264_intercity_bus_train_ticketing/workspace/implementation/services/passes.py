"""Travel-pass ride accounting and status derivation (PRD 3.10; scaffold pass_rides).

rides_consumed: count of ACTIVE legs across pass-funded bookings currently
redeeming this pass. rides_remaining = rides_total - rides_consumed (never < 0).
Status is re-derived from balance: 0 remaining -> EXHAUSTED; >0 -> ACTIVE
(unless EXPIRED by the clock). EXPIRED is terminal.
"""
import clock
from timeutil import parse_date
import db


def is_expired_by_clock(travel_pass):
    """True if the clock date is strictly past expires_on (PRD 3.10)."""
    expires = parse_date(travel_pass["expires_on"])
    clock_date = clock.now().date()
    return clock_date > expires


def consumed_rides(pass_id):
    """rides_consumed: ACTIVE legs across pass-funded bookings redeeming this pass."""
    total = 0
    for booking in db.bookings.values():
        if booking.get("pass_id") != pass_id:
            continue
        if booking.get("funding_kind") != "PASS":
            continue
        for leg in db.booking_legs.values():
            if leg["booking_id"] != booking["id"]:
                continue
            if leg["leg_state"] == "ACTIVE":
                total += 1
    return total


def recompute(travel_pass, bump_version=True):
    """Recompute rides_consumed/rides_remaining and re-derive status.

    EXPIRED is terminal and is not reverted by a balance recompute.
    """
    consumed = consumed_rides(travel_pass["id"])
    remaining = travel_pass["rides_total"] - consumed
    if remaining < 0:
        remaining = 0

    old_consumed = travel_pass["rides_consumed"]
    old_remaining = travel_pass["rides_remaining"]
    old_status = travel_pass["status"]

    travel_pass["rides_consumed"] = consumed
    travel_pass["rides_remaining"] = remaining

    new_status = old_status
    if old_status != "EXPIRED":
        if remaining == 0:
            new_status = "EXHAUSTED"
        else:
            new_status = "ACTIVE"
    travel_pass["status"] = new_status

    changed = (
        old_consumed != consumed
        or old_remaining != remaining
        or old_status != new_status
    )
    if bump_version and changed:
        db.touch(travel_pass)
    return travel_pass


def mark_expired(travel_pass):
    """Drive the pass to terminal EXPIRED, bumping version (PRD 3.10)."""
    if travel_pass["status"] != "EXPIRED":
        travel_pass["status"] = "EXPIRED"
        db.touch(travel_pass)
    return travel_pass
