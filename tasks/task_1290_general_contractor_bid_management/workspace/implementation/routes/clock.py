from flask import Blueprint

import errors
from db import CLOCK, parse_iso, format_ts
from middleware import get_context, require_role, get_json_body, require_fields, reject_unexpected
from response import success_object

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    get_context_role = get_context()
    require_role(get_context_role[1], {"LeadEstimator", "ChiefEstimator", "PrequalReviewer"})
    body = get_json_body()
    reject_unexpected(body, {"to_iso8601"})
    require_fields(body, ["to_iso8601"])
    target = parse_iso(body.get("to_iso8601"))
    if target is None:
        raise errors.err_invalid_request("to_iso8601 must be a valid ISO 8601 timestamp")
    current = CLOCK.set_to(target)
    return success_object({"current_utc": format_ts(current)}, 200)
