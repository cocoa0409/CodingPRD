"""Test-driving admin endpoints (PRD §3.10): clock advance, sweep, event emit."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import clock
from ..errors import api_error
from ..response import success_envelope
from ..services.sweep import run_sweep
from ..store import store
from ..utils import get_json_body, parse_iso_datetime, require_str

bp = Blueprint("admin", __name__, url_prefix="/scf")


@bp.post("/_clock/advance")
@require_auth(["PlatformAdmin"])
def clock_advance():
    body = get_json_body()
    to_raw = require_str(body, "to")
    target = parse_iso_datetime(to_raw)
    clock.advance_to(target)
    with store.lock:
        run_sweep()
    return success_envelope({"now": to_raw})


@bp.post("/_sweep/run")
@require_auth(["PlatformAdmin"])
def sweep_run():
    with store.lock:
        run_sweep()
    return success_envelope({})


@bp.post("/_events/emit")
@require_auth(["PlatformAdmin"])
def event_emit():
    body = get_json_body()
    event_type = require_str(body, "event_type")
    payload = body.get("payload", {})
    if not isinstance(payload, dict):
        raise api_error("ERR_VALIDATION", "payload must be an object")
    row = store.emit_event(event_type, payload)
    return success_envelope({"event_id": row["id"], "event_type": event_type})
