"""The plant logical clock test-driving endpoint (PRD §2.5). PlantManager
only; mutates no entity, only moves the clock that temporal rules consult."""
from flask import Blueprint

from db import iso, now, parse_dt, set_now
from errors import ApiError
from middleware import auth, body
from response import success_object

clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth(("PlantManager",))
    b = body()
    target = parse_dt(b.get("to_iso8601"))
    if target is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime.")
    set_now(target)
    return success_object({"current_utc": iso(now())})
