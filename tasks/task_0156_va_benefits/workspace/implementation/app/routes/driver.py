"""Test driver routes: /_clock/advance, /_sweep/run, and /__test__/reset."""
from __future__ import annotations

from flask import Blueprint, current_app

from ..auth import require_auth
from ..clock import Clock
from ..errors import ApiError
from ..services.enrollments import run_sweep
from ..store import Store
from ._common import get_json_body, get_store, respond_object

bp = Blueprint("driver", __name__)


@bp.route("/__test__/reset", methods=["POST"])
def reset_state():
    """Wipe in-memory state to a fresh Store for test isolation.

    No auth required: this is purely a test-harness hook. Returns current
    server clock so the test runner can re-sync its clock tracker.
    """
    new_store = Store()
    current_app.config["STORE"] = new_store
    return respond_object({"now": Clock.format(new_store.clock.now())})


@bp.route("/_clock/advance", methods=["POST"])
@require_auth(["PlatformAdmin"])
def advance():
    body = get_json_body()
    store = get_store()
    if "to" in body and body["to"] is not None:
        try:
            target = Clock.parse(body["to"])
        except ValueError as e:
            raise ApiError("ERR_INVALID_BODY", str(e))
        now = store.clock.advance_to(target)
    elif "seconds" in body and body["seconds"] is not None:
        s = body["seconds"]
        if not isinstance(s, int) or isinstance(s, bool):
            raise ApiError("ERR_INVALID_BODY", "seconds must be an integer")
        if s < 0:
            raise ApiError("ERR_INVALID_BODY", "seconds must be non-negative")
        now = store.clock.advance_seconds(s)
    else:
        raise ApiError("ERR_INVALID_BODY", "must provide 'to' or 'seconds'")
    return respond_object({"now": Clock.format(now)})


@bp.route("/_sweep/run", methods=["POST"])
@require_auth(["PlatformAdmin"])
def sweep():
    store = get_store()
    with store.lock:
        result = run_sweep(store)
    return respond_object(result)
