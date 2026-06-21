"""Test-driving operational endpoints: the server clock (PRD §2.8)."""
from flask import Blueprint

import clock
import helpers
from middleware import get_identity, require_roles
from response import success

bp = Blueprint("ops", __name__)


# ---------------------------------------------------------------------------
# POST /_clock/set_current_utc  (JuryAdministrator)
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator"})

    body = helpers.get_body()
    to_iso = helpers.require_string(body, "to_iso8601")
    dt = helpers.parse_iso8601(to_iso, "to_iso8601")
    clock.set_current(dt)

    iso = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return success({"current_utc": iso}, status=200)
