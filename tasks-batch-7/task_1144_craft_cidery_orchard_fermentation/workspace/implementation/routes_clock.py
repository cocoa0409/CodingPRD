"""Test-driving logical clock endpoint."""

from flask import Blueprint, request

import db
from errors import validation
from middleware import require_roles
from response import parse_ts, success_object, ts
from services import time_sweep

bp = Blueprint("clock", __name__, url_prefix="/cidery")


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc():
    b = request.get_json(silent=True) or {}
    try:
        target = parse_ts(b.get("to_iso8601"))
    except (TypeError, ValueError):
        raise validation("to_iso8601 must be an ISO8601 timestamp")
    db.set_now(target)
    time_sweep()
    return success_object({"now_iso8601": ts(db.now())})
