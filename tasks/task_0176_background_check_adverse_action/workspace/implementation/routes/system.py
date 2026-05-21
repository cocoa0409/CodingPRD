"""Routes: /fcra/_clock + /fcra/_sweep (test orchestration)."""
from __future__ import annotations

from flask import Blueprint

from core.auth import require_roles
from core.envelope import get_json_body, success_response
from core.errors import err_validation_failed
from core.store import store
from core.utils import lock
from services.sweep_service import run_sweep


bp = Blueprint("system", __name__)


@bp.route("/fcra/_clock/advance", methods=["POST"])
@require_roles("PlatformAdmin")
def post_clock_advance():
    body = get_json_body()
    seconds = body.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise err_validation_failed("seconds must be an integer.")
    if seconds < 0:
        raise err_validation_failed("seconds must be non-negative.")
    with lock():
        store.advance_logical_clock(seconds)
    from core.clock import logical_now_iso

    return success_response({"current_time": logical_now_iso()})


@bp.route("/fcra/_sweep/run", methods=["POST"])
@require_roles("PlatformAdmin")
def post_sweep_run():
    with lock():
        result = run_sweep()
    return success_response(result)
