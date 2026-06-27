from flask import Blueprint

from clock import clock, parse_iso8601, format_iso8601_ms
from errors import err
from middleware import auth
from response import success
from validate import get_body, require

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(["ContractingOfficer"])
    body = get_body()
    raw = require(body, "to_iso8601")
    try:
        dt = parse_iso8601(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime.")
    clock.set(dt)
    return success({"now_utc": format_iso8601_ms(clock.now())},
                   status=200, response_type="object")
