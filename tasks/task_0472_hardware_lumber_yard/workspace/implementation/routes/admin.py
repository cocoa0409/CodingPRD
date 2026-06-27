"""Administrative test-driving clock endpoint (PRD 3.11)."""
from flask import Blueprint

import clock
import db
import validate
from auth import authenticate, require_roles
from response import ok

bp = Blueprint("admin", __name__)

# Any of the four operator roles may drive the clock (per scaffold endpoint
# table). Contractor is NOT listed.
CLOCK_ROLES = {"InventoryManager", "AccountsManager", "RentalClerk", "SalesAssociate"}


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = authenticate()
    require_roles(caller, CLOCK_ROLES)
    data = validate.body()
    to_iso = validate.require_str(data, "to_iso8601")
    dt = validate.parse_iso(to_iso, "to_iso8601")
    with db.lock:
        clock.set_now(dt)
    return ok({})
