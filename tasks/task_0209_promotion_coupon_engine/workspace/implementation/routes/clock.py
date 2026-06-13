"""Logical clock + expiry sweep (PRD §2.8, §3.3)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, parse_dt
from errors import err
from middleware import require_roles
from response import success
from services.common import require_field, require_json_object, touch

bp = Blueprint("clock", __name__)


def run_expiry_sweep():
    """Any ACTIVE/PAUSED promotion whose window has closed (clock >= active_until)
    auto-transitions to EXPIRED."""
    for p in db.promotions.values():
        if p["status"] in ("ACTIVE", "PAUSED"):
            au = parse_dt(p["active_until"])
            if db.clock >= au:
                p["status"] = "EXPIRED"
                touch(p)


@bp.post("/_clock/set")
@require_roles("PlatformOperator")
def set_clock():
    with db.lock:
        body = require_json_object(request.get_json(silent=True))
        now_utc = require_field(body, "now_utc")
        dt = parse_dt(now_utc)
        if dt is None:
            raise err("ERR_INVALID_REQUEST", "now_utc must be ISO 8601")
        db.clock = dt
        run_expiry_sweep()
        return success(None, 200)


@bp.post("/_clock/advance")
@require_roles("PlatformOperator")
def advance_clock():
    with db.lock:
        body = require_json_object(request.get_json(silent=True))
        seconds = require_field(body, "seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise err("ERR_INVALID_REQUEST", "seconds must be a number")
        db.clock = db.clock + timedelta(seconds=seconds)
        run_expiry_sweep()
        return success(None, 200)
