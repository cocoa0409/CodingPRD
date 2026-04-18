"""Health, clock, sweep routes."""
from flask import Blueprint

from clock import set_now, parse_iso, iso_now
from common import get_json_body
from errors import api_error
from middleware import get_auth, require_roles
from response import success
from services.sweep import run_sweep

bp = Blueprint("system", __name__)


@bp.route("/health", methods=["GET"])
def health():
    return success({"status": "ok"})


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    ts = body.get("to_timestamp")
    if not ts:
        raise api_error("ERR_INVALID_TIME_WINDOW", "to_timestamp required")
    try:
        dt = parse_iso(ts)
    except Exception:
        raise api_error("ERR_INVALID_TIME_WINDOW", "invalid to_timestamp")
    set_now(dt)
    return success({"now": iso_now()})


@bp.route("/_sweep/run", methods=["POST"])
def sweep_run():
    require_roles(["PlatformAdmin"])
    count = run_sweep()
    return success({"swept_count": count})
