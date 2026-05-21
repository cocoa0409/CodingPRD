"""Test harness clock endpoint."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint

from ..auth import require_auth
from ..clock import clock
from ..errors import ApiError
from ..responses import success_response
from ..store import store
from ..validation import get_json_body, require_number


bp = Blueprint("clock", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_auth("PlatformAdmin")
def advance_clock():
    body = get_json_body()
    seconds = require_number(body, "seconds")
    if seconds < 0:
        raise ApiError("ERR_VALIDATION", "seconds must be non-negative.")
    clock.advance(float(seconds))
    return success_response({}, status=200)


# Test-harness only — reset every in-memory collection and clock offset.
# Not part of PRD; exists solely so the runner's conftest can isolate
# tests against the shared in-memory process.
def _reset():
    with store.lock:
        store.parks.clear()
        store.lots.clear()
        store.homes.clear()
        store.residents.clear()
        store.leases.clear()
        store.rent_notices.clear()
        store.eviction_cases.clear()
        store.utility_bills.clear()
        store.home_sale_transfers.clear()
        store.conversion_requests.clear()
    # Reset clock offset.
    with clock._lock:
        clock._offset = timedelta(seconds=0)


@bp.route("/__test__/reset", methods=["POST"])
def reset_test_state():
    _reset()
    return success_response({}, status=200)


@bp.route("/_test/reset", methods=["POST"])
def reset_test_state_alt():
    _reset()
    return success_response({}, status=200)


__all__ = ["bp"]
