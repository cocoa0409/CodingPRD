"""The logical-clock control operation (no auth, no role check)."""

from flask import Blueprint

from db import db
from middleware import body
from response import object_response
from validation import req_instant

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    payload = body()
    instant, raw = req_instant(payload, "to_iso8601")
    db.set_clock(instant, raw)
    return object_response({"current_utc": db.clock_raw})
