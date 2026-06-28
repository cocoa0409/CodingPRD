from flask import Blueprint

from clock import clock, parse_clock_field
from middleware import require_role
from response import object_response
from errors import err, ERR_INVALID_REQUEST
from services.common import get_json_body, require_fields

clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # Public per PRD §2.1 (no auth headers required), but RBAC role is OpsAdmin.
    # PRD §2.1 lists clock-setting among the unauthenticated endpoints, so we do
    # NOT require auth headers here.
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    try:
        parse_clock_field(body["to_iso8601"])
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO-8601 instant.")
    clock.set(body["to_iso8601"])
    return object_response({}, 200)
