"""The two /_ test-driving endpoints (PlatformAdmin only)."""
from flask import Blueprint

import auth
import cascade
import clock
import response
import validate
from store import db, touch

from routes import common

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authenticate(("PlatformAdmin",))
    data = validate.body()
    raw = validate.instant_req(data, "current_utc")
    instant = clock.parse_instant(raw)
    previous = clock.now()
    clock.set_now(instant)
    if instant > previous:  # moving backwards runs no sweep at all
        cascade.run_sweeps(instant)
    return response.empty(200)


@bp.post("/_payments/simulate-chargeback")
def simulate_chargeback():
    auth.authenticate(("PlatformAdmin",))
    data = validate.body()
    raw_booking = data.get("booking_id")
    if isinstance(raw_booking, str) and raw_booking:
        booking = common.find("bookings", raw_booking)
    else:
        booking = None
    validate.str_req(data, "booking_id")
    validate.str_req(data, "reason_code")
    if booking["payment_status"] != "CAPTURED":
        from errors import ApiError
        raise ApiError("ERR_PAYMENT_NOT_CAPTURED")
    booking["payment_status"] = "CHARGEBACK"
    touch(booking)
    return response.obj(booking, 200)
