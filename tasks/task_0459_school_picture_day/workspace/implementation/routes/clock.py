"""Logical clock control (PRD §2.10)."""
from datetime import datetime, timezone

from flask import Blueprint

import db
from common import get_body, require_fields, require_str
from errors import err
from middleware import get_user_context, require_role
from response import object_response

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator", "StudioPhotographer", "FulfillmentClerk"])
    body = get_body()
    require_fields(body, ["to_iso8601"])
    raw = require_str(body, "to_iso8601")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    db.set_clock(dt.astimezone(timezone.utc))
    return object_response({})
