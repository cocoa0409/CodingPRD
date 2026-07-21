"""Test-driving logical clock control surface."""
from flask import Blueprint

import db
import middleware
from response import object_response

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    middleware.authenticate(["PlatformAdmin"])
    payload = middleware.body()
    instant = middleware.req_datetime(payload, "to_iso8601")
    db.set_clock(instant)
    return object_response({"current_utc": db.iso(instant)})
