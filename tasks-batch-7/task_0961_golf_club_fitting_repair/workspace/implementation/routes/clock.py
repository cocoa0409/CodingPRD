"""Logical clock endpoint (test-driving capability)."""
from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import get_auth, require_role
from response import success_response, parse_iso, iso_format
from services.sweeps import run_time_sweeps

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    user_id, role = get_auth()
    require_role(role, {"ShopAdmin"})
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    to_iso8601 = data.get("to_iso8601")
    try:
        new_now = parse_iso(to_iso8601)
    except (ValueError, TypeError):
        raise_err("ERR_VALIDATION", "to_iso8601 must be an ISO8601 timestamp")
    db.logical_now = new_now
    run_time_sweeps()
    return success_response({"current_utc": iso_format(db.logical_now)})
