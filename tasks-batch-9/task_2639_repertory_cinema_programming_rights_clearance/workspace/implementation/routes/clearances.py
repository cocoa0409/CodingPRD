"""Repertory rights clearance (PRD 3.3)."""
from flask import Blueprint

import serialize
from auth import ROLE_EXEC, ROLE_PROGRAMMER, ROLE_RIGHTS, ROLE_TECH, authorize
from calc import venue_local_day
from cascade import Ledger, cancel_showtime
from errors import ApiError
from response import object_response, paged
from store import new_record, now, ordered, touch
from validate import (FORMATS, bad, body, find, insert, must_find, query_str, req_day,
                      req_enum, req_id, req_int, req_str, rows)

bp = Blueprint("clearances", __name__)

READ_ROLES = (ROLE_PROGRAMMER, ROLE_RIGHTS, ROLE_TECH, ROLE_EXEC)
LIVE_STATUSES = ("SUBMITTED", "CHANGES_REQUESTED", "CLEARED")


def require_clearance_state(clearance, allowed):
    if clearance["status"] not in allowed:
        raise ApiError("ERR_CLEARANCE_INVALID_STATE",
                       "A licence in %s does not admit this transition." % clearance["status"])


def clearance_venue(clearance):
    booking = find("bookings", clearance["booking_id"])
    if booking is None:
        return None
    return find("venues", booking["venue_id"])


def lapse_if_lapsed(clearance, venue):
    """Lazy expiry (PRD 3.3): a cleared licence past its window flips to EXPIRED.

    The flip persists even when the request that discovered it goes on to fail.
    """
    if clearance["status"] != "CLEARED" or venue is None:
        return False
    if clearance["window_end_date"] < venue_local_day(venue, now()):
        clearance["status"] = "EXPIRED"
        touch(clearance)
        return True
    return False


@bp.post("/clearances")
def create_clearance():
    role, uid = authorize((ROLE_RIGHTS,))
    payload = body()
    licensor_name = req_str(payload, "licensor_name")
    license_fee_cents = req_int(payload, "license_fee_cents", minimum=0)
    territory = req_str(payload, "territory")
    window_start = req_day(payload, "window_start_date")
    window_end = req_day(payload, "window_end_date")
    if window_end < window_start:
        raise bad("window_end_date must not be earlier than window_start_date.")
    max_screenings = req_int(payload, "max_screenings", minimum=1)
    source_format = req_enum(payload, "source_format", FORMATS)
    title_id = req_id(payload, "title_id")
    booking_id = req_id(payload, "booking_id")
    title = must_find("titles", title_id)
    booking = must_find("bookings", booking_id)
    if booking["status"] == "WITHDRAWN":
        raise ApiError("ERR_BOOKING_INVALID_STATE",
                       "A withdrawn engagement cannot carry a new licence.")
    venue = find("venues", booking["venue_id"])
    supported = venue["supported_formats"] if venue else []
    if source_format != title["native_format"] and source_format not in supported:
        raise ApiError("ERR_FORMAT_INCOMPATIBLE",
                       "source_format is neither the title's native format nor supported.")
    if booking["title_id"] != title_id:
        raise ApiError("ERR_REFERENCE_MISMATCH",
                       "The licence and its engagement must name the same title.")
    row = new_record(
        title_id=title_id,
        booking_id=booking_id,
        licensor_name=licensor_name,
        license_fee_cents=license_fee_cents,
        territory=territory,
        window_start_date=window_start,
        window_end_date=window_end,
        max_screenings=max_screenings,
        source_format=source_format,
        screenings_used=0,
        screenings_remaining=max_screenings,
        status="SUBMITTED",
        submitted_by_user_id=uid,
        cleared_by_user_id=None,
        change_request_note=None,
        revoked_reason=None,
    )
    insert("clearances", row)
    return object_response(serialize.clearance(row), 201)


@bp.get("/clearances/<clearance_id>")
def read_clearance(clearance_id):
    authorize(READ_ROLES)
    return object_response(serialize.clearance(must_find("clearances", clearance_id)))


@bp.get("/clearances")
def list_clearances():
    authorize(READ_ROLES)
    found = rows("clearances")
    for name in ("title_id", "booking_id", "status"):
        value = query_str(name)
        if value is not None:
            found = [c for c in found if c[name] == value]
    return paged(ordered(found), serialize.clearance)


@bp.post("/clearances/<clearance_id>/submit")
def resubmit_clearance(clearance_id):
    role, uid = authorize((ROLE_RIGHTS,))
    body()
    clearance = must_find("clearances", clearance_id)
    require_clearance_state(clearance, ("CHANGES_REQUESTED",))
    clearance["status"] = "SUBMITTED"
    clearance["submitted_by_user_id"] = uid
    touch(clearance)
    return object_response(serialize.clearance(clearance))


@bp.post("/clearances/<clearance_id>/request-changes")
def request_changes(clearance_id):
    authorize((ROLE_RIGHTS, ROLE_EXEC))
    payload = body()
    note = req_str(payload, "change_request_note")
    clearance = must_find("clearances", clearance_id)
    require_clearance_state(clearance, ("SUBMITTED",))
    clearance["status"] = "CHANGES_REQUESTED"
    clearance["change_request_note"] = note
    touch(clearance)
    return object_response(serialize.clearance(clearance))


@bp.post("/clearances/<clearance_id>/clear")
def clear_clearance(clearance_id):
    role, uid = authorize((ROLE_RIGHTS, ROLE_EXEC), require_user_id=True)
    body()
    clearance = must_find("clearances", clearance_id)
    require_clearance_state(clearance, ("SUBMITTED",))
    venue = clearance_venue(clearance)
    if venue is not None and clearance["window_end_date"] < venue_local_day(venue, now()):
        raise ApiError("ERR_CLEARANCE_INVALID_STATE",
                       "The licensed window has already run out.")
    if uid == clearance["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The caller who lodged this licence may not clear it.")
    clearance["status"] = "CLEARED"
    clearance["cleared_by_user_id"] = uid
    touch(clearance)
    return object_response(serialize.clearance(clearance))


@bp.post("/clearances/<clearance_id>/revoke")
def revoke_clearance(clearance_id):
    authorize((ROLE_RIGHTS, ROLE_EXEC))
    payload = body()
    revoked_reason = req_str(payload, "revoked_reason")
    clearance = must_find("clearances", clearance_id)
    require_clearance_state(clearance, LIVE_STATUSES)
    ledger = Ledger()
    clearance["status"] = "REVOKED"
    clearance["revoked_reason"] = revoked_reason
    ledger.mark(clearance)
    for showtime in ordered(rows("showtimes")):
        if showtime["clearance_id"] == clearance["id"] and showtime["status"] == "SCHEDULED":
            cancel_showtime(showtime, "CLEARANCE_REVOKED", ledger)
    ledger.flush()
    return object_response(serialize.clearance(clearance))
