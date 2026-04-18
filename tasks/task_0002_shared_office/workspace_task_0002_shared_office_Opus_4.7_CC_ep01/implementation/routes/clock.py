from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_TIME_WINDOW
from response import success
from middleware import require_roles
from util import parse_iso, now_iso_string
from db import db
from services.sweep_service import run_sweep

bp = Blueprint("clock", __name__)


@bp.route("/_clock/advance", methods=["POST"])
def advance_clock():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    to_ts = body.get("to_timestamp")
    dt = parse_iso(to_ts) if to_ts else None
    if dt is None:
        raise_error(ERR_INVALID_TIME_WINDOW, "Invalid to_timestamp")
    db.set_clock(dt)
    return success({"clock": now_iso_string(dt)})


@bp.route("/_sweep/run", methods=["POST"])
def sweep_run():
    require_roles("PlatformAdmin")
    run_sweep()
    return success({"clock": now_iso_string(db.now())})
