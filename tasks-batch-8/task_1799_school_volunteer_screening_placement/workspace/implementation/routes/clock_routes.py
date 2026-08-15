"""Logical clock endpoint: POST /_clock/set_current_utc."""

from flask import request

import db
import clock
import services
from errors import invalid_request
from middleware import require_roles
from response import success_object


def register(app):
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        require_roles("DistrictCoordinator")
        body = request.get_json(silent=True) or {}
        to_raw = body.get("to_iso8601")
        if not to_raw:
            raise invalid_request("to_iso8601 is required")
        try:
            to_dt = clock.parse_iso(to_raw)
        except (ValueError, TypeError):
            raise invalid_request("to_iso8601 must be a valid ISO8601 datetime")

        clock.set_current(to_dt)
        now = clock.now()

        # Sweep 1: BackgroundChecks {CLEARED, CLEARED_WITH_FLAGS} with expires_at <= now -> EXPIRED
        expired_check_count = 0
        affected_volunteer_ids = set()
        for check in db.background_checks.values():
            if check["status"] in ("CLEARED", "CLEARED_WITH_FLAGS"):
                exp = check.get("expires_at")
                if exp is not None and clock.parse_iso(exp) <= now:
                    check["status"] = "EXPIRED"
                    services.touch(check)
                    expired_check_count += 1
                    affected_volunteer_ids.add(check["volunteer_id"])

        # Sweep 2: recompute each affected volunteer's clearance_expires_at; ACTIVE without valid clearance -> RESCREEN_REQUIRED
        volunteers_rescreened_count = 0
        for vid in affected_volunteer_ids:
            vol = db.volunteers.get(vid)
            if vol is None:
                continue
            services.recompute_clearance_expires_at(vol)
            if vol["status"] == "ACTIVE":
                cea = vol["clearance_expires_at"]
                if cea is None or clock.parse_iso(cea) <= now:
                    vol["status"] = "RESCREEN_REQUIRED"
                    services.touch(vol)
                    volunteers_rescreened_count += 1
                else:
                    # clearance still valid; updated but no demotion. Do not bump version.
                    pass

        # Sweep 3: Opportunities OPEN with ends_at <= now -> COMPLETED
        opportunities_completed_count = 0
        for opp in db.opportunities.values():
            if opp["status"] == "OPEN" and clock.parse_iso(opp["ends_at"]) <= now:
                opp["status"] = "COMPLETED"
                services.touch(opp)
                opportunities_completed_count += 1

        result = {
            "current_utc": clock.now_iso(),
            "expired_check_count": expired_check_count,
            "volunteers_rescreened_count": volunteers_rescreened_count,
            "opportunities_completed_count": opportunities_completed_count,
        }
        return success_object(result, 200)
