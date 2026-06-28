"""Logical clock route (PRD §2.4, §4). Clerk-only. Sets the server-wide logical
clock; once set, every RecordingOffice.recording_date tracks the new value."""
from flask import Blueprint

import errors
from auth import require_auth, CLERK
from clock import clock, parse_iso
from db import db
from helpers import body, require_fields
from response import ok

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth([CLERK])
    data = body()
    require_fields(data, ["to_iso8601"])
    raw = data["to_iso8601"]
    try:
        dt = parse_iso(raw)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid to_iso8601")
    clock.set(dt)
    # Every office's recording_date tracks the logical clock value.
    for office in db.offices.values():
        office["recording_date"] = dt
    return ok({})
