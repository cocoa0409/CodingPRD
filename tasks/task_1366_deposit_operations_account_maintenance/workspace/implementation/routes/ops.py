"""Ops endpoints (PRD §3.8, §2.5): the daily sweep and the logical clock."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from services.sweep import run_daily_sweep

bp = Blueprint("ops", __name__)


@bp.post("/bank/ops/daily-sweep")
def daily_sweep():
    require_roles(["OpsManager", "System"])
    result = run_daily_sweep()
    return success_object(result)


@bp.post("/bank/_clock/set_current_utc")
def set_clock():
    require_roles(["OpsManager", "System"])
    body = request.get_json(silent=True) or {}
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str) or not to_iso8601.strip():
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        instant = db.parse_instant(to_iso8601)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 instant")
    db.set_clock(instant.isoformat().replace("+00:00", "Z"))
    return success_object({"current_utc": db._clock["current"]})
