"""Test-driving clock route."""
from flask import Blueprint, request

from middleware import get_auth, require_role
from validate import require_body, require_datetime
from services.domain import advance_clock
from response import success

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin", "BillingAdmin"})
    data = require_body(request.get_json(silent=True))
    new_dt = require_datetime(data, "to_iso8601")
    advance_clock(new_dt)
    return success({}, status=200)
