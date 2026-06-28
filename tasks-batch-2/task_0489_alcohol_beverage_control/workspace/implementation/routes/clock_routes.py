"""POST /_clock/set_current_utc — advance the logical clock."""
from flask import Blueprint

import errors
from auth import require_auth
from clock import clock, iso, parse_iso
from helpers import body
from response import ok

bp = Blueprint("clock", __name__)

# Anonymous and Applicant may NOT drive the clock (per endpoint roles).
CLOCK_ROLES = ["Director", "LicensingExaminer", "AdjudicationOfficer", "ZoningOfficer", "Investigator"]


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(CLOCK_ROLES)
    data = body()
    if "to_iso8601" not in data or data["to_iso8601"] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing to_iso8601")
    try:
        target = parse_iso(data["to_iso8601"])
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid to_iso8601")
    clock.set(target)
    return ok({"now": iso(clock.now())})
