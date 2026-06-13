"""Test-driving clock endpoint (PRD §3.10)."""

from flask import Blueprint

import errors
import services
from db import db
from clock import parse_iso
from errors import err
from helpers import get_body, require_datetime
from middleware import require_user_context, require_role
from response import ok_object

bp = Blueprint("clock", __name__)

CLOCK_ROLES = {"PlatformAdmin"}


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    user_id, role = require_user_context()
    require_role(role, CLOCK_ROLES)
    body = get_body()
    target = require_datetime(body, "to_iso8601")
    # Target must be at or after the current clock; rewind rejected.
    if target < db.clock:
        raise err(errors.ERR_CLOCK_REWIND, "Clock target is earlier than the current clock")
    db.clock = target
    swept_permit_ids, swept_booking_ids = services.run_clock_sweeps()
    data = {
        "now": body["to_iso8601"],
        "swept_permit_ids": swept_permit_ids,
        "swept_booking_ids": swept_booking_ids,
    }
    return ok_object(data)
