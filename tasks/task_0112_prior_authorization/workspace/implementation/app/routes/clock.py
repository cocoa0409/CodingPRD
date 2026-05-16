"""Clock and sweep test-driving endpoints."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..clock import clock_now_dt, clock_now_iso, parse_iso, set_clock
from ..errors import APIError
from ..helpers import get_json_body, require_field
from ..responses import success_response
from ..store import get_lock, get_store, reset_store, stamp_update


bp = Blueprint("clock_sweep", __name__)


@bp.post("/__test__/reset")
def test_reset():
    """Test-only: wipe the in-memory store between tests.

    Not in the PRD's role matrix — this is a harness convention used by
    the runner's autouse conftest to keep tests independent. No auth
    required; the endpoint is namespaced under /__test__/.
    """
    with get_lock():
        reset_store()
    return jsonify({"ok": True}), 200


@bp.post("/_clock/advance")
@require_auth("PlatformAdmin")
def clock_advance():
    body = get_json_body()
    to = require_field(body, "to")
    # Parse to ensure well-formed; advance only forward (PRD doesn't require monotonic,
    # but tests typically move forward).
    parsed = parse_iso(to)
    set_clock(to)
    body_out, status = success_response({"now": clock_now_iso()})
    return jsonify(body_out), status


@bp.post("/_sweep/run")
@require_auth("PlatformAdmin")
def sweep_run():
    swept = []
    with get_lock():
        store = get_store()
        now = clock_now_dt()
        for auth in list(store.authorization_requests.values()):
            if auth["status"] != "APPROVED":
                continue
            if not auth.get("expires_at"):
                continue
            expires_at = parse_iso(auth["expires_at"])
            if now >= expires_at:
                auth["status"] = "EXPIRED"
                stamp_update(auth)
                swept.append(auth["id"])
    body_out, status = success_response({"expired_authorization_request_ids": swept})
    return jsonify(body_out), status
