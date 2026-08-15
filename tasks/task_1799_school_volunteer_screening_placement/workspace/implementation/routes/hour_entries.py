"""Hour entry endpoints: log, list, read, verify, reject, revoke."""

import re
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
import clock
import services
from errors import (
    APIError, not_found, invalid_request, forbidden,
    ERR_PLACEMENT_INVALID_STATE, ERR_HOURS_OUTSIDE_PLACEMENT_WINDOW,
    ERR_HOURS_EXCEED_LIMIT, ERR_HOUR_ENTRY_INVALID_STATE,
    ERR_PLACEMENT_VOLUNTEER_MISMATCH,
)
from middleware import require_roles, check_volunteer_ownership
from pagination import parse_pagination, paginate
from response import success_object, success_list

ACTIVITY_CATEGORIES = ("STANDARD", "TUTORING", "MENTORING")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _recompute_volunteer_after_hour_change(volunteer, allow_auto_award=True):
    services.recompute_volunteer_hours(volunteer)
    services.recompute_recognition_points(volunteer)
    services.recompute_recognition_tier(volunteer, allow_auto_award=allow_auto_award)
    services.touch(volunteer)


def register(app):
    @app.route("/hour-entries", methods=["POST"])
    def create_entry():
        role, user_id = require_roles("Volunteer", "DistrictCoordinator")
        body = request.get_json(silent=True) or {}

        # p3 existence: placement_id
        pid = body.get("placement_id")
        pl = None
        if pid is not None:
            pl = db.placements.get(pid)
            if pl is None:
                raise not_found("placement_id does not resolve")

        # p2 ownership for Volunteer: placement must belong to caller
        if role == "Volunteer" and pl is not None:
            check_volunteer_ownership(role, user_id, pl["volunteer_id"])

        # p4 state: placement in {CONFIRMED, COMPLETED}
        if pl is not None and pl["status"] not in ("CONFIRMED", "COMPLETED"):
            raise APIError(ERR_PLACEMENT_INVALID_STATE,
                           "hour logging requires placement in {CONFIRMED, COMPLETED}", 409)

        # p6 referential: placement.volunteer_id == caller's volunteer (when role Volunteer)
        # Already enforced as p2 ownership above.

        # p7 temporal: worked_date within [starts_at date, ends_at date]
        if pl is not None:
            worked_date_raw = body.get("worked_date")
            opp = db.opportunities.get(pl["opportunity_id"])
            if opp is not None and worked_date_raw is not None and isinstance(worked_date_raw, str) and DATE_RE.match(worked_date_raw):
                try:
                    from datetime import date as _date
                    wd = _date.fromisoformat(worked_date_raw)
                    s_date = clock.parse_iso(opp["starts_at"]).date()
                    e_date = clock.parse_iso(opp["ends_at"]).date()
                    if not (s_date <= wd <= e_date):
                        raise APIError(ERR_HOURS_OUTSIDE_PLACEMENT_WINDOW,
                                       "worked_date outside the placement opportunity's [starts_at date, ends_at date]", 422)
                except ValueError:
                    pass  # malformed date handled at p10

        # p8: hours <= 12 (ERR_HOURS_EXCEED_LIMIT)
        hours_raw = body.get("hours")
        if hours_raw is not None:
            try:
                h_dec = Decimal(str(hours_raw))
                if h_dec > Decimal("12"):
                    raise APIError(ERR_HOURS_EXCEED_LIMIT,
                                   "Single hour entry declares hours > 12", 422)
            except (ValueError, ArithmeticError):
                pass  # malformed handled at p10

        # p10 shape
        if pid is None:
            raise invalid_request("placement_id is required")
        worked_date = body.get("worked_date")
        if not worked_date or not isinstance(worked_date, str) or not DATE_RE.match(worked_date):
            raise invalid_request("worked_date must be YYYY-MM-DD")
        try:
            from datetime import date as _date
            _date.fromisoformat(worked_date)
        except ValueError:
            raise invalid_request("worked_date must be a valid calendar date")
        if hours_raw is None or isinstance(hours_raw, bool):
            raise invalid_request("hours is required and must be a number")
        try:
            hours_dec = Decimal(str(hours_raw))
        except (ValueError, ArithmeticError):
            raise invalid_request("hours must be a number")
        if hours_dec <= 0:
            raise invalid_request("hours must be positive")
        # at most 2 decimal places
        exponent = hours_dec.as_integer_ratio()
        quantized = hours_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if hours_dec != quantized:
            raise invalid_request("hours may carry at most two decimal places")
        cat = body.get("activity_category")
        if cat not in ACTIVITY_CATEGORIES:
            raise invalid_request("activity_category must be STANDARD, TUTORING, or MENTORING")

        # points = round_half_up(hours * multiplier, 1 decimal)
        mult = services.POINTS_MULTIPLIER[cat]
        points = (hours_dec * mult).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

        entry = {
            "id": db.new_id(),
            "created_at": clock.now_iso(),
            "updated_at": clock.now_iso(),
            "version": 1,
            "placement_id": pid,
            "volunteer_id": pl["volunteer_id"],
            "worked_date": worked_date,
            "hours": float(hours_dec),
            "activity_category": cat,
            "status": "PENDING",
            "points": float(points),
        }
        db.hour_entries[entry["id"]] = entry

        volunteer = db.volunteers[pl["volunteer_id"]]
        services.recompute_volunteer_hours(volunteer)
        services.touch(volunteer)

        return success_object(entry, 201)

    @app.route("/hour-entries", methods=["GET"])
    def list_entries():
        require_roles("DistrictCoordinator", "CampusAdmin")
        limit, offset = parse_pagination()
        items = list(db.hour_entries.values())
        pid = request.args.get("placement_id")
        vid = request.args.get("volunteer_id")
        status = request.args.get("status")
        if pid is not None:
            items = [e for e in items if e["placement_id"] == pid]
        if vid is not None:
            items = [e for e in items if e["volunteer_id"] == vid]
        if status is not None:
            items = [e for e in items if e["status"] == status]
        page, total = paginate(items, limit, offset)
        return success_list(page, limit, offset, total)

    @app.route("/hour-entries/<eid>", methods=["GET"])
    def get_entry(eid):
        role, user_id = require_roles("DistrictCoordinator", "CampusAdmin", "Volunteer")
        entry = db.hour_entries.get(eid)
        if entry is None:
            raise not_found()
        if role == "Volunteer":
            check_volunteer_ownership(role, user_id, entry["volunteer_id"])
        return success_object(entry, 200)

    @app.route("/hour-entries/<eid>/verify", methods=["POST"])
    def verify(eid):
        require_roles("CampusAdmin", "DistrictCoordinator")
        entry = db.hour_entries.get(eid)
        if entry is None:
            raise not_found()
        if entry["status"] != "PENDING":
            raise APIError(ERR_HOUR_ENTRY_INVALID_STATE, "Verify requires PENDING", 409)
        entry["status"] = "VERIFIED"
        services.touch(entry)
        volunteer = db.volunteers[entry["volunteer_id"]]
        _recompute_volunteer_after_hour_change(volunteer, allow_auto_award=True)
        return success_object(entry, 200)

    @app.route("/hour-entries/<eid>/reject", methods=["POST"])
    def reject(eid):
        require_roles("CampusAdmin", "DistrictCoordinator")
        entry = db.hour_entries.get(eid)
        if entry is None:
            raise not_found()
        if entry["status"] != "PENDING":
            raise APIError(ERR_HOUR_ENTRY_INVALID_STATE, "Reject requires PENDING", 409)
        entry["status"] = "REJECTED"
        services.touch(entry)
        volunteer = db.volunteers[entry["volunteer_id"]]
        services.recompute_volunteer_hours(volunteer)
        services.touch(volunteer)
        return success_object(entry, 200)

    @app.route("/hour-entries/<eid>/revoke", methods=["POST"])
    def revoke(eid):
        require_roles("DistrictCoordinator")
        entry = db.hour_entries.get(eid)
        if entry is None:
            raise not_found()
        if entry["status"] != "VERIFIED":
            raise APIError(ERR_HOUR_ENTRY_INVALID_STATE, "Revoke requires VERIFIED", 409)
        entry["status"] = "REVOKED"
        services.touch(entry)
        volunteer = db.volunteers[entry["volunteer_id"]]
        _recompute_volunteer_after_hour_change(volunteer, allow_auto_award=False)
        return success_object(entry, 200)
