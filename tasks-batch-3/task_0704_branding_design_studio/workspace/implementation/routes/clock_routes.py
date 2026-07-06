"""Logical clock administrative endpoint (PRD §2.11)."""
from flask import Blueprint

from clock import clock
from middleware import authenticate
from helpers import require_role, get_json_body, require_fields
from errors import err, ERR_INVALID_REQUEST
from util import parse_iso8601
from response import success

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = authenticate()
    # Available to StudioOps and BillingOps (PRD §2.11 / §1.5).
    require_role(caller, "StudioOps", "BillingOps")
    body = get_json_body()
    require_fields(body, "to_iso8601")
    instant = parse_iso8601(body["to_iso8601"])
    if instant is None:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime")
    clock.set(instant)
    # output: null -> empty object data.
    return success({}, status=200)
