"""Logical-clock control endpoint (PRD §2.9, §3.2, §3.3)."""

import clock
import common
import errors
from response import success
from routehelpers import auth_and_role, body


def register(app):
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        # Roles: PlatformAdmin only.
        auth_and_role(["PlatformAdmin"])
        data = body()
        to_iso = common.require_str(data, "to_iso8601")
        # Validate it parses as a timestamp (else ERR_INVALID_REQUEST).
        from timeutil import parse_iso
        try:
            parse_iso(to_iso)
        except ValueError:
            raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 timestamp")
        clock.set_clock(to_iso)
        # PRD §1.5 output: null -> empty data object.
        return success({}, status=200)
