"""Logical clock endpoints (PRD §2.6, SCAFFOLD §1.5 _clock)."""
from flask import Blueprint

import errors
from db import db, parse_iso, iso_from_dt
from middleware import get_auth, require_role
from response import object_response
from services.common import get_json_body, require_fields

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_auth()
    require_role(role, {"Registrar", "ComplianceOfficer"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    try:
        new_dt = db.clock.set(body["to_iso8601"])
    except (ValueError, TypeError):
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 instant.")
    return object_response({"current_utc": iso_from_dt(new_dt)}, 200)


@bp.route("/_clock", methods=["GET"])
def get_clock():
    _, role = get_auth()
    require_role(role, {"Registrar", "Guide", "ComplianceOfficer", "Parent"})
    return object_response({"current_utc": db.clock.now_iso()}, 200)
