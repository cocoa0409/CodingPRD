"""Test-driving capabilities: logical clock and payment simulation."""

import uuid

from flask import Blueprint

import db
import errors
import helpers as h
import response

bp = Blueprint("core", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    h.require_roles("TrackOps")
    data = h.body()
    if "to_iso8601" not in data:
        raise errors.invalid_request("field 'to_iso8601' is required")
    parsed = h.parse_dt(data["to_iso8601"])  # raises ERR_INVALID_REQUEST on malformed input
    db.CURRENT_UTC = h.fmt_dt(parsed)
    return response.success({"current_utc": db.CURRENT_UTC}, 200)


@bp.route("/_payments/simulate", methods=["POST"])
def simulate_payment():
    h.require_roles("TrackOps")
    data = h.body()
    booking_id = h.req_string(data, "booking_id")
    outcome = h.req_enum(data, "outcome", h.PAYMENT_OUTCOMES)
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise errors.not_found("booking %s not found" % booking_id)
    current = booking["payment_status"]
    if outcome == "AUTHORIZE":
        if current != "UNPAID":
            raise errors.invalid_state("payment_status must be UNPAID to AUTHORIZE")
        booking["payment_status"] = "AUTHORIZED"
    elif outcome == "CAPTURE":
        if current != "AUTHORIZED":
            raise errors.invalid_state("payment_status must be AUTHORIZED before CAPTURED")
        booking["payment_status"] = "CAPTURED"
    elif outcome == "VOID":
        if current != "AUTHORIZED":
            raise errors.invalid_state("payment_status must be AUTHORIZED to VOID")
        booking["payment_status"] = "UNPAID"
    elif outcome == "REFUND":
        if current != "CAPTURED":
            raise errors.invalid_state("payment_status must be CAPTURED to REFUND")
        booking["payment_status"] = "REFUNDED"
    booking["updated_at"] = h.now_str()
    booking["version"] += 1
    for driver in db.drivers.values():
        if driver["booking_id"] == booking["id"]:
            h.recompute_driver_cleared(driver)
    return response.success(h.serialize_booking(booking), 200)
