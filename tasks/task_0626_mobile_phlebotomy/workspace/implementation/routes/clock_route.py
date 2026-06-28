"""Test-driving logical clock endpoint (PRD 2.4)."""
from flask import Blueprint

import common
import errors
from clock import clock, parse_iso
from middleware import require_roles

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("LabOps", "Dispatcher")
def set_clock():
    body = common.get_body()
    to_iso8601 = common.require_str(body, "to_iso8601")
    dt = parse_iso(to_iso8601)
    if dt is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 instant.")
    clock.set(dt)
    # Output null per the endpoint table; data is an empty object for 2xx no-data.
    return common.object_response({})
