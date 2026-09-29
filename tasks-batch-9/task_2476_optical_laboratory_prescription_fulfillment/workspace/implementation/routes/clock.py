"""The logical clock (PRD 2.6)."""

from flask import Blueprint

from auth import require_roles
from envelope import ok
from errors import ApiError
from store import db, fmt_dt
from validate import F, json_body, parse_datetime, validate_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    body = json_body()
    data = validate_body(body, [F("current_utc", "datetime")])
    require_roles()
    instant = parse_datetime(data["current_utc"])
    if instant < db.clock:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    db.clock = instant
    return ok({"current_utc": fmt_dt(db.clock)})
