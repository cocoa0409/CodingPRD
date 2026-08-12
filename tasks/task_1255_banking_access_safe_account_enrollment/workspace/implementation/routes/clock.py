"""Logical clock endpoint."""

import db
from errors import err_validation
from middleware import require_roles, get_json_body, require_fields, check_string
from response import success_object


def register(bp):
    @bp.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        require_roles("CoalitionAdmin")
        body = get_json_body()
        require_fields(body, ["to_iso8601"])
        check_string(body["to_iso8601"], "to_iso8601")
        if not db.is_valid_iso_datetime(body["to_iso8601"]):
            err_validation("to_iso8601 must be a valid ISO 8601 timestamp")
        current = db.parse_dt(db.get_clock())
        target = db.parse_dt(body["to_iso8601"])
        if target < current:
            err_validation("Clock is monotonic: to_iso8601 must be >= current value")
        db.set_clock(target.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z")
        return success_object({"current_utc": db.get_clock()})
