"""Logical clock test-driving endpoint (PRD §2.9)."""
from flask import Blueprint

import errors
import response
from db import db, parse_iso
from middleware import require_roles
from services import common

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # all roles except Homeowner (scaffold §1.5)
    require_roles({"SalesDesigner", "InstallManager", "Manufacturer",
                   "PermitOfficer", "Inspector"})
    body = common.get_json()
    to_iso = common.require_field(body, "to_iso8601", expected_types=["string"])
    try:
        dt = parse_iso(to_iso)
    except (ValueError, TypeError):
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 timestamp.")
    db.set_clock(dt)
    # returns 200 with no resource payload (PRD §4)
    return response.success({}, status=200)
