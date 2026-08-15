"""Logical clock test-driving endpoint."""
from flask import Blueprint

import clock
import errors
import middleware
import response
from routes.helpers import body, require
from services import cascade

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    middleware.require_roles(["PlantManager"])
    data = body()
    raw = require(data, "to_iso8601")
    dt = clock.try_parse(raw) if isinstance(raw, str) else None
    if dt is None:
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "to_iso8601 must be an ISO8601 timestamp")
    clock.set_to(dt)
    # Advancing the clock may transition certificates APPROVED -> EXPIRED
    # (lazy expiry applied at this touch point; expiry never cascades).
    cascade.touch_certificates()
    return response.success_object({"current_utc": clock.now_iso()})
