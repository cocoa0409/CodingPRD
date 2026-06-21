"""Test-driving logical clock endpoint (PRD §2.7, §3.8)."""
from flask import Blueprint

import db
import errors
import response
import util
import validate
from middleware import require_auth, require_role, QI_COORDINATOR, SETTLEMENT_OFFICER

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR, SETTLEMENT_OFFICER})
    data = validate.body()
    if "to_iso8601" not in data:
        raise errors.invalid_request("Missing required field: to_iso8601.")
    dt = util.parse_iso(data["to_iso8601"])
    # Advances the logical clock; subsequent posture reads recompute against it.
    db.set_clock(dt)
    # output: null (SCAFFOLD §1.5); 200 OK with an empty data object.
    return response.success_object({})
