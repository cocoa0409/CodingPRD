"""Clock + sweep test-driving endpoints."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import success_object
from util import parse_iso, format_ts
from services.domain import run_sweeps

bp = Blueprint("clock", __name__)


@bp.route("/v1/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    to = body.get("to_iso8601")
    if not to:
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 required")
    try:
        dt = parse_iso(to)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid to_iso8601")
    db.set_now(dt)
    return success_object({"now_utc": format_ts(db.get_now())})


@bp.route("/v1/_sweeps/run", methods=["POST"])
def run_sweep():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    advance_to = body.get("advance_to_iso8601")
    if not advance_to:
        raise ApiError("ERR_INVALID_REQUEST", 400, "advance_to_iso8601 required")
    try:
        dt = parse_iso(advance_to)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid advance_to_iso8601")
    db.set_now(dt)
    applied = run_sweeps()
    return success_object({"applied_transitions": applied, "now_utc": format_ts(db.get_now())})
