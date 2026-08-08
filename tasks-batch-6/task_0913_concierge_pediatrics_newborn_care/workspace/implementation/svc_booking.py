"""ConsultBooking helpers shared by the booking routes and CASCADE A."""
from flask import g

import constants as C
import svc_entitlement
from store import db, touch


def _padded_end(booking_end):
    from datetime import timedelta

    return booking_end + timedelta(minutes=C.CONSULT_TURNAROUND_BUFFER_MINUTES)


def has_schedule_conflict(consultant_physician_id, start, end, exclude_booking_id=None):
    """Half-open [scheduled_start, scheduled_end) padded by 15 minutes on the
    trailing edge.  A booking starting exactly at prior_end + 15 does NOT collide."""
    new_end = _padded_end(end)
    for other in db.bookings.values():
        if other["consultant_physician_id"] != consultant_physician_id:
            continue
        if other["status"] != "SCHEDULED":
            continue
        if exclude_booking_id is not None and other["id"] == exclude_booking_id:
            continue
        other_end = _padded_end(other["scheduled_end"])
        if start < other_end and other["scheduled_start"] < new_end:
            return True
    return False


def cancel_booking(booking):
    """CASCADE C — release the hold, then reopen an EXHAUSTED pool."""
    booking["status"] = "CANCELLED"
    touch(booking, g.touched)
    grant = db.grants.get(booking["grant_id"])
    if grant is not None:
        svc_entitlement.release_unit(grant, booking["coverage_route"])
