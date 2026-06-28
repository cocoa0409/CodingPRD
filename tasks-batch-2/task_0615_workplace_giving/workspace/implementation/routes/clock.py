"""Logical clock endpoint (PRD §2.7)."""
from flask import Blueprint

from db import db
from middleware import get_user_context, require_role
from response import object_response
from services.common import get_json_body, require_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager"})
    body = get_json_body()
    to_iso = require_datetime(body, "to_iso8601")
    db.clock.set(to_iso)
    # Output null per scaffold; 200 with empty data object.
    return object_response({}, 200)
