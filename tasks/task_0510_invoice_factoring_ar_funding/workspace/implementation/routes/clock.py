"""Logical-clock test-driving endpoint (§1.5 / PRD §2.4)."""

from flask import Blueprint

import db
import errors
from common import req_str
from middleware import authenticate, authorize
from response import success
from routes.helpers import get_body
from services import transitions

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    authorize(role, ("PlatformAdmin",))
    body = get_body()
    iso = req_str(body, "to_iso8601")
    try:
        db.set_clock(iso)
    except (ValueError, TypeError):
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 datetime")
    # Advancing the clock recomputes aging and fires FUNDED->OUTSTANDING.
    transitions.advance_clock_side_effects()
    return success({}, status=200)
