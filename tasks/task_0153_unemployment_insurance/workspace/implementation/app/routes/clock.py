"""SystemClock routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import (
    ROLE_ADJUDICATOR,
    ROLE_APPEAL_OFFICER,
    ROLE_CLAIMANT,
    ROLE_EMPLOYER_AGENT,
    ROLE_SYSTEM_ADMIN,
    require_auth,
)
from ..clock import advance_seconds, now_iso
from ..envelope import success_object
from ..errors import APIError
from ..serializers import serialize_system_clock
from ..services.sweep import sweep
from ..store import get_store, reset_store
from ..validators import get_json_body, require_int

bp = Blueprint("clock", __name__)


@bp.get("/_clock")
@require_auth([
    ROLE_CLAIMANT, ROLE_ADJUDICATOR, ROLE_APPEAL_OFFICER,
    ROLE_EMPLOYER_AGENT, ROLE_SYSTEM_ADMIN,
])
def clock_read():
    return jsonify(success_object(serialize_system_clock(now_iso()))), 200


@bp.post("/_clock/advance")
@require_auth([ROLE_SYSTEM_ADMIN])
def clock_advance():
    body = get_json_body()
    seconds = require_int(body, "seconds")
    store = get_store()
    with store.lock:
        advance_seconds(seconds)
        sweep()
    return jsonify(success_object(serialize_system_clock(now_iso()))), 200


@bp.post("/__test__/reset")
def test_reset():
    """Test-only hook: wipe all in-memory state.

    Not gated by auth so tests can call it cleanly between scenarios.
    """
    reset_store()
    # Re-init clock to now()
    _ = now_iso()
    return jsonify(success_object(serialize_system_clock(now_iso()))), 200
