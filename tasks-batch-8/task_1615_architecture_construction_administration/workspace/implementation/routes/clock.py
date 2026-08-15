"""POST /ca/_clock/set_current_utc — logical clock control."""

from flask import Blueprint

import db
from middleware import get_user_context, require_role, get_body
from response import success_object
from services.helpers import req_field, is_ts_str, invalid
from services import calcs

bp = Blueprint("clock", __name__)


@bp.post("/ca/_clock/set_current_utc")
def set_clock():
    _, role = get_user_context()
    require_role(role, ("FirmAdmin",))
    body = get_body(required=True)
    to_iso = req_field(body, "to_iso8601")
    if not is_ts_str(to_iso):
        invalid("to_iso8601 must be an ISO 8601 timestamp")
    current = db.clock.set(to_iso)
    # side effect: recompute ca_posture for every ACTIVE CaProject
    calcs.recompute_posture_all_active()
    return success_object({"current_utc": db.LogicalClock.fmt(current)}, 200)
