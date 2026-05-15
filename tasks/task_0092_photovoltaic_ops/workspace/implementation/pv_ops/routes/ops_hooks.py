"""Test/operational hooks: /_clock/advance, /_events/emit, /_sweep/run."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, current_app

from pv_ops.auth import require_roles
from pv_ops.responses import success, accepted
from pv_ops.utils import get_body, parse_dt, require_str


bp = Blueprint("ops_hooks", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("PlatformAdmin")
def clock_advance():
    body = get_body()
    target = parse_dt(body.get("to"), "to")
    store = current_app.extensions["store"]
    with store.lock:
        store.clock.set(target)
        # Whenever the clock advances we also run the arrears watchdog and
        # downsampling sweep so time-based transitions are processed deterministically.
        from pv_ops.services.sweep import run_sweep

        result = run_sweep(store)
    return success({"now": store.clock.now_iso(), **result})


@bp.route("/_events/emit", methods=["POST"])
@require_roles("PlatformAdmin")
def events_emit():
    body = get_body()
    source = require_str(body, "source")
    if "payload" not in body:
        from pv_ops.errors import APIError, ERR_VALIDATION

        raise APIError(ERR_VALIDATION, 422, "Missing payload")
    payload = body["payload"]
    return accepted({"source": source, "payload": payload, "accepted": True})


@bp.route("/_sweep/run", methods=["POST"])
@require_roles("PlatformAdmin")
def sweep_run():
    store = current_app.extensions["store"]
    with store.lock:
        from pv_ops.services.sweep import run_sweep

        result = run_sweep(store)
    return success(result)
