"""Test-driving capture clock (PRD §2.5)."""
from flask import Blueprint

from db import db
from errors import err, ERR_INVALID_REQUEST
from middleware import get_identity, require_roles
from response import object_response
from services.common import get_body, require_fields, require_str
from services.cycle import parse_iso, complete_due_cycles

bp = Blueprint("clock", __name__)


@bp.post("/_clock/advance")
def advance_clock():
    _, role = get_identity()
    require_roles(role, {"Manager"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    to_iso = require_str(body["to_iso8601"], "to_iso8601")
    try:
        new_clock = parse_iso(to_iso)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 timestamp")
    with db.lock:
        db.capture_clock = new_clock
        # Complete any RUNNING cycle whose cycle_ends_at <= the new clock.
        complete_due_cycles(new_clock)
    # Endpoint output is null per the spec; return an empty data object.
    return object_response({})
