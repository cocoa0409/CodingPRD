"""POST /_clock/set_current_utc — test-driving endpoint for the logical clock."""

from flask import Blueprint

import clock
from middleware import authenticate, require_role
from response import ok
from validation import get_body, validate

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = authenticate()
    data = get_body()
    v = validate(data, [("to_iso8601", "datetime", True)])
    require_role(role, {"TrustExecutive"})
    current = clock.set_clock(v["to_iso8601"])
    return ok({"current_utc": current})
