"""Administrative logical-clock set endpoint (PRD §2.11)."""
from flask import Blueprint

from clock import clock
from middleware import require_auth, require_role
from response import object_response
from services.common import get_body, require_present, as_datetime

bp = Blueprint("clock_route", __name__)

# All four operational staff roles may drive the clock (not Customer).
CLOCK_ROLES = ["InventoryManager", "LivestockKeeper", "ClinicVet", "StoreClerk"]


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = require_auth()
    require_role(role, CLOCK_ROLES)
    body = get_body()
    to_iso = require_present(body, "to_iso8601")
    as_datetime(to_iso, "to_iso8601")  # validate -> ERR_INVALID_FIELD_VALUE on failure
    clock.set(to_iso)
    return object_response({})
