"""Logical-clock test-driving endpoint."""
from flask import Blueprint

from middleware import require_roles
from response import success_object
from services.clock import set_logical_now, logical_now
from services.validation import get_json_body, reject_unknown_fields, validate_datetime

bp = Blueprint("clock", __name__)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(["URDirector"])
    body = get_json_body()
    reject_unknown_fields(body, ["to_iso8601"])
    dt = validate_datetime(body, "to_iso8601")
    set_logical_now(dt)
    return success_object({"current_utc": _iso(logical_now())}, 200)
