from flask import Blueprint, request

from db import DB, parse_iso
from errors import err_invalid_request
from middleware import get_actor, require_role
from response import success_object
from util import require_fields

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["to_iso8601"])
    raw = payload.get("to_iso8601")
    try:
        dt = parse_iso(raw)
    except Exception:
        raise err_invalid_request("to_iso8601 must be a valid ISO 8601 UTC timestamp")
    with DB.lock:
        DB.set_now(dt)
        return success_object({}, status=200)
