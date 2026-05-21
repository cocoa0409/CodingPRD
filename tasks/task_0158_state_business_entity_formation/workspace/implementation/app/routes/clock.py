"""Clock-advance and manual-sweep endpoints (test-driving infrastructure)."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_auth
from ..envelope import object_response
from ..errors import err_invalid_input
from ..store import store
from ..timeutil import advance, iso, now as clock_now, parse_duration
from ..util import get_json_body, require_str
from ..services.engine import run_sweep


bp = Blueprint("clock", __name__, url_prefix="/business-registry")


@bp.post("/_clock/advance")
@require_auth(["TestHarness"])
def clock_advance():
    body = get_json_body()
    duration_raw = require_str(body, "duration_iso8601", min_len=1, max_len=64)
    delta = parse_duration(duration_raw)
    if delta is None:
        raise err_invalid_input("duration_iso8601 must be a valid ISO 8601 duration")
    with store.lock:
        new_instant = advance(delta)
        result = run_sweep(at=new_instant)
    return jsonify(object_response({
        "now": iso(new_instant),
        "transitions_applied": result.get("transitions_applied", {}),
    })), 200


@bp.post("/_sweep/run")
@require_auth(["TestHarness", "ComplianceOfficer"])
def sweep_run():
    with store.lock:
        now = clock_now()
        result = run_sweep(at=now)
    return jsonify(object_response({
        "now": iso(now),
        "transitions_applied": result.get("transitions_applied", {}),
    })), 200
