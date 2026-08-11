"""Test-driving logical clock route."""
import db
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import get_caller, require_role, get_json_body
from response import success


def register(bp):
    @bp.route("/_clock/set_current_utc", methods=["POST"])
    def set_current_utc():
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator"])
        body = get_json_body()
        to_iso = body.get("to_iso8601")
        if not isinstance(to_iso, str):
            raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be a string")
        # validate parseable
        db.parse_dt(to_iso)
        db.set_clock(to_iso)
        return success({"current_utc": db.get_clock()})
