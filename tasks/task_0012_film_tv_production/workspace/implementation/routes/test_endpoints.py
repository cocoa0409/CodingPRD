"""Test-driving endpoints (clock advance, event simulator)."""
from flask import Blueprint

import errors as E
from middleware import require_roles
from response import ok_object
from body import get_json_body, require_string
from clock import clock, parse_iso8601


bp = Blueprint("test_endpoints", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("ExecutiveProducer")
def advance_clock():
    body = get_json_body()
    target = require_string(body, "to_iso8601")
    try:
        dt = parse_iso8601(target)
    except Exception:
        E.validation_err("Invalid to_iso8601 datetime")
    clock.set(dt)
    return ok_object({"now": clock.now_iso()})


@bp.route("/_events/emit", methods=["POST"])
@require_roles("ExecutiveProducer")
def emit_event():
    body = get_json_body()
    event_type = require_string(body, "event_type")
    payload = body.get("payload", {})
    if not isinstance(payload, dict):
        E.validation_err("payload must be an object")
    return ok_object({"event_type": event_type, "payload": payload, "accepted": True})
