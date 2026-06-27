"""Logical clock test-driving endpoint (PRD §3.9). Singleton ComplianceClock:
carries only id and created_at (no updated_at, no version)."""
from flask import Blueprint

import errors
from db import db, new_id, clock_iso, CLOCK_START
from middleware import get_identity, require_role
from response import object_response
from routes.common import get_json_body
from timeutil import parse_iso

bp = Blueprint("clock", __name__)

# A stable singleton id/created_at minted on first boot import.
_CLOCK_ID = new_id()
_CLOCK_CREATED = CLOCK_START.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _clock_dict():
    return {
        "id": _CLOCK_ID,
        "created_at": _CLOCK_CREATED,
        "current_utc": clock_iso(),
    }


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = get_identity()
    require_role(role, {"OfficeManager"})
    body = get_json_body()

    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str) or not to_iso:
        raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        target = parse_iso(to_iso)
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 is not a valid instant")

    db.clock = target
    return object_response(_clock_dict(), 200)
