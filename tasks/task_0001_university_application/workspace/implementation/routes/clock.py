"""Test-driving clock route."""

from flask import Blueprint

import errors
import response as resp
import util
from middleware import require_auth
from routes._helpers import get_json_body, require_field


bp = Blueprint("clock", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_auth(["PlatformAdmin"])
def advance_clock():
    body = get_json_body()
    target_str = require_field(body, "to_iso8601", kind="string")
    target_dt = util.parse_iso(target_str)
    if target_dt is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'to_iso8601' must be a valid ISO 8601 timestamp.")
    util.set_clock(target_dt)
    return resp.success_object({
        "clock_iso": util.format_iso(target_dt),
    })
