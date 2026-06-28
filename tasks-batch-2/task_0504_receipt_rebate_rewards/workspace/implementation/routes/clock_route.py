"""Logical-clock test-driving endpoint (PRD §2.10)."""
from flask import Blueprint

from clock import parse_iso
from errors import err
from middleware import get_identity, require_roles
from response import object_response
from services.timeadvance import fire_due_transitions
from state import store
from validation import get_json_body, require_string

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin"])
    body = get_json_body()
    to_iso = require_string(body, "to_iso8601")
    parsed = parse_iso(to_iso)
    if parsed is None:
        raise err("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 instant.")
    store.clock.set(parsed)
    # Fire due time-based transitions.
    fire_due_transitions(store)
    return object_response(store.clock, {})
