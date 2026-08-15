"""POST /api/_clock/set_current_utc"""
from flask import Blueprint

from middleware import require_roles
from response import success_object
from errors import err_invalid_request
from util import parse_dt, iso_from_dt
from services.clock import set_logical_clock, get_logical_clock
from ._helpers import get_json_body, require_fields

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
@require_roles("PlantAdmin")
def set_current_utc(_user_id, _role):
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_dt(body["to_iso8601"])
    if dt is None:
        raise err_invalid_request("to_iso8601 must be a valid ISO 8601 datetime")
    set_logical_clock(dt)
    return success_object({"current_utc": iso_from_dt(get_logical_clock())}, 200)
