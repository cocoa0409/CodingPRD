"""Test-driving logical clock endpoint."""

from datetime import datetime, timezone

from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles, get_json_body, require_fields, reject_unknown_fields
from response import success_object

bp = Blueprint("clock", __name__)


def _parse_iso8601(s):
    if not isinstance(s, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("PlatformAdmin")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {"to_iso8601"})
    require_fields(body, ["to_iso8601"])
    target = _parse_iso8601(body["to_iso8601"])
    db.clock_set(target)
    return success_object({"current_utc": db.fmt_ts(db.clock_now())})
