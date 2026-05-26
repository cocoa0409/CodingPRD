"""Test-driving clock endpoint (PRD §2.6)."""
from flask import Blueprint

import db
from errors import invalid_request
from middleware import require_roles, ROLE_PLANNER, ROLE_OPS
from response import success
from routes.common import get_json_body
from services import validate
from services.cascade import cascade_clock_auto_transitions
from services.timeutil import parse_iso, is_iso8601


bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles({ROLE_PLANNER, ROLE_OPS})
    body = validate.ensure_dict(get_json_body())
    validate.require_fields(body, ("to_iso8601",))
    to_iso = body["to_iso8601"]
    if not is_iso8601(to_iso):
        raise invalid_request("to_iso8601 must be a valid ISO 8601 UTC timestamp")
    db.set_clock(parse_iso(to_iso))
    cascade_clock_auto_transitions()
    return success({}, status=200)
