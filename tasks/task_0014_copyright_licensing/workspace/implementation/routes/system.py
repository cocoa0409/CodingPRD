"""Health, clock advance."""
from flask import Blueprint

from clock import iso_now, parse_iso, set_now
from common import get_json_body
from errors import api_error
from middleware import require_roles
from response import success
from services.transitions import evaluate_clock_advanced

bp = Blueprint("system", __name__)


@bp.route("/health", methods=["GET"])
def health():
    return success({"status": "ok"})


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    ts = body.get("to_iso8601") or body.get("to_timestamp")
    if not ts:
        raise api_error("ERR_VALIDATION", "to_iso8601 required")
    try:
        dt = parse_iso(ts)
    except Exception:
        raise api_error("ERR_VALIDATION", "invalid to_iso8601")
    set_now(dt)
    evaluate_clock_advanced()
    return success({"now": iso_now()})
