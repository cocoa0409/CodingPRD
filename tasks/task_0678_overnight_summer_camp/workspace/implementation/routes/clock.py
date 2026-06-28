"""Logical clock administration. PRD §2.4 / §2.1.

The clock endpoint is exempt from the priority-1 ERR_UNAUTHENTICATED header
check (SCAFFOLD §1.4 applies_to), but setting the clock is reserved to the
CampDirector role and is not available to Anonymous (PRD §2.1). We therefore
require the X-User-Role header to be CampDirector; a non-director role is
rejected with ERR_FORBIDDEN_ROLE.
"""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_json_body
from services import validate

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role = request.headers.get("X-User-Role")
    if role != "CampDirector":
        raise ApiError(errors.ERR_FORBIDDEN_ROLE, 403, "Setting the clock is reserved to CampDirector.")
    body = get_json_body()
    dt = validate.require_datetime(body, "to_iso8601")
    db.set_clock(dt)
    return response.success({"now": db.iso(dt)}, 200)
