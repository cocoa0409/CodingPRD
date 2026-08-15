"""Test-driving logical clock."""
from flask import Blueprint, request

from db import clock, _parse_iso, _fmt_ts
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from services.derived import sweep_melt_risk_all_deposited

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("SystemAdmin")
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    if not to_iso:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 required")
    dt = _parse_iso(to_iso)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 malformed")
    clock.set(dt)
    sweep_melt_risk_all_deposited()
    return success_object({"current_utc": _fmt_ts(clock.now())})
