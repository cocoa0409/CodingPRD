"""Test-driver endpoints (POST /_clock/advance, POST /_events/emit)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from app.auth import require_role
from app.clock import logical_clock
from app.errors import api_error
from app.response import success_object
from app.services.scheduler import run_clock_advance_side_effects
from app.store import reset_store, store
from app.utils import format_iso, is_number, parse_iso
from datetime import datetime, timezone


bp = Blueprint("admin", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_role("AdminOps")
def clock_advance(user_id: str, role: str):
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")
    to_raw = body.get("to")
    by_hours = body.get("by_hours")
    if to_raw is None and by_hours is None:
        raise api_error("ERR_INVALID_REQUEST", "Provide 'to' or 'by_hours'")
    if to_raw is not None:
        target = parse_iso(to_raw)
        if target is None:
            raise api_error("ERR_INVALID_REQUEST", "Invalid 'to' timestamp")
    else:
        if not is_number(by_hours):
            raise api_error("ERR_INVALID_REQUEST", "by_hours must be a number")
        target = logical_clock.now() + timedelta(hours=float(by_hours))

    current = logical_clock.now()
    if target < current:
        raise api_error("ERR_INVALID_REQUEST", "Clock cannot move backwards")
    logical_clock.set(target)
    run_clock_advance_side_effects()
    return success_object({"now": format_iso(logical_clock.now())})


@bp.route("/__test__/reset", methods=["POST"])
def test_reset():
    """Test-only state-reset endpoint. Wipes the in-memory store and
    resets the logical clock to the current wall-clock instant. Not
    declared in PRD §3.7; available as test infrastructure to keep
    cases isolated when run in a shared process."""
    reset_store()
    logical_clock.set(datetime.now(timezone.utc).replace(microsecond=0))
    return success_object({"reset": True})


@bp.route("/_events/emit", methods=["POST"])
@require_role("AdminOps")
def events_emit(user_id: str, role: str):
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")
    system = body.get("system")
    event_type = body.get("event_type")
    if system not in ("payment", "logistics", "im", "vet"):
        raise api_error("ERR_INVALID_REQUEST", "system must be one of payment|logistics|im|vet")
    if not isinstance(event_type, str):
        raise api_error("ERR_INVALID_REQUEST", "event_type required")
    # We accept the event and acknowledge without dispatching to a specific
    # order/adjustment — tests that need to drive a specific entity use the
    # dedicated routes.
    return success_object({"system": system, "event_type": event_type, "received": True})
