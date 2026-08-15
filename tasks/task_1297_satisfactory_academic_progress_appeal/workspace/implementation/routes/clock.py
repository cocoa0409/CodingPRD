"""Test-driving logical clock endpoint (AidAdministrator only).

The clock moves only forward; a target earlier than the current logical time
is rejected with ERR_INVALID_REQUEST.
"""

from datetime import timezone

from flask import Blueprint

import errors
from db import fmt_ts, now, set_now
from middleware import authenticate, get_body, require_roles
from response import success

bp = Blueprint("clock", __name__)


def _parse_instant(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.post("/sap/_clock/set_current_utc")
def set_current_utc():
    authenticate()
    require_roles("AidAdministrator")
    body = get_body()
    target = _parse_instant(body.get("to_iso8601"))
    if target is None:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "to_iso8601 must be an ISO 8601 timestamp")
    if target < now():
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "The logical clock moves only forward")
    set_now(target)
    return success({"current_utc": fmt_ts(target)})
