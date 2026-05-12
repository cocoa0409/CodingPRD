"""Test harness endpoints: /_clock/advance, /_sweep/run, /_events/external, /_meta/health."""

from flask import Blueprint

from db import db, new_id
from clock import clock, now_iso
from middleware import (
    require_roles,
    get_auth,
    parse_json_body,
    require_fields,
    require_str,
    require_enum,
)
from response import success_object
from errors import ERR_CLOCK_REGRESS, ERR_BAD_REQUEST, raise_error
from datetime_utils import parse_iso8601
from services.audit import append_audit
from services.sweep import run_sweep

bp = Blueprint("harness", __name__)

EVENT_KINDS = {"TICKETING_PLATFORM", "PAYMENT", "CINEMA_MGMT"}


@bp.route("/_meta/health", methods=["GET"])
def health():
    return success_object({"status": "ok"})


@bp.route("/_test/reset", methods=["POST"])
def test_reset():
    """Test-only hook: wipe in-memory state and reset the server clock.
    Not part of PRD; used by the test harness to isolate per-test state."""
    db.reset()
    clock.reset()
    return success_object({})


@bp.route("/_clock/advance", methods=["POST"])
@require_roles({"PlatformAdmin"})
def advance_clock():
    role, user_id = get_auth()
    body = parse_json_body()
    require_fields(body, ["to_timestamp"])
    to_timestamp_str = require_str(body.get("to_timestamp"), "to_timestamp")
    target = parse_iso8601(to_timestamp_str, "to_timestamp")
    if not clock.advance_to(target):
        raise_error(ERR_CLOCK_REGRESS, "to_timestamp is not after current clock")
    append_audit(role, user_id, "CLOCK_ADVANCE", "Clock", "clock", {"to_timestamp": to_timestamp_str})
    return success_object({})


@bp.route("/_sweep/run", methods=["POST"])
@require_roles({"PlatformAdmin"})
def sweep_run():
    role, user_id = get_auth()
    run_sweep()
    append_audit(role, user_id, "SWEEP_RUN", "Sweep", "sweep", {})
    return success_object({})


@bp.route("/_events/external", methods=["POST"])
@require_roles({"PlatformAdmin", "TicketingPlatform"})
def post_external_event():
    role, user_id = get_auth()
    body = parse_json_body()
    require_fields(body, ["kind", "payload"])
    kind = require_enum(body.get("kind"), "kind", EVENT_KINDS)
    payload = body.get("payload")
    if not isinstance(payload, dict):
        raise_error(ERR_BAD_REQUEST, "payload must be object")
    now = now_iso()
    evt = {
        "id": new_id(),
        "kind": kind,
        "payload": payload,
        "applied": False,
        "created_at": now,
    }
    db.external_events[evt["id"]] = evt
    # Run handler — for this implementation, just flip applied to True
    evt["applied"] = True
    return success_object(dict(evt), http_status=201)
