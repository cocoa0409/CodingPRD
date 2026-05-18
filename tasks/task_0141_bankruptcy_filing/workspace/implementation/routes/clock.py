"""Test-only clock-advance endpoint.

POST /_clock/advance accepts {"to_iso8601": "..."} and sets the server clock
forward (or backward) to the supplied instant. Required by SCAFFOLD §1.5 so
the meeting-date precondition can be satisfied without wall-clock waits.
"""

from flask import Blueprint

from middleware import require_auth, parse_json_body
from response import success
from db import store
from errors import make_error
from utils import parse_iso8601


clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/_clock/advance")
@require_auth(allowed_roles=["Trustee"])
def advance_clock_route():
    body = parse_json_body(required_fields=["to_iso8601"])
    try:
        when = parse_iso8601(body["to_iso8601"])
    except Exception:
        raise make_error("ERR_BAD_REQUEST", "to_iso8601 must be an ISO 8601 timestamp.")
    with store.lock:
        store.set_clock(when)
    return success({})
