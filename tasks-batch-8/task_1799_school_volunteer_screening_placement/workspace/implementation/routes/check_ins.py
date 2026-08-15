"""Visit check-in endpoints: create, list, read, check-out."""

from datetime import timedelta

from flask import request

import db
import clock
import services
from errors import (
    APIError, not_found, invalid_request,
    ERR_VOLUNTEER_INVALID_STATE, ERR_OPEN_CHECKIN_EXISTS,
    ERR_CHECKIN_INVALID_STATE, ERR_OUTSIDE_CHECKIN_WINDOW,
    ERR_PLACEMENT_INVALID_STATE, ERR_PLACEMENT_VOLUNTEER_MISMATCH,
    ERR_PLACEMENT_CAMPUS_MISMATCH,
)
from middleware import require_roles, check_volunteer_ownership
from pagination import parse_pagination, paginate
from response import success_object, success_list


def register(app):
    @app.route("/check-ins", methods=["POST"])
    def create_checkin():
        role, user_id = require_roles("Volunteer", "CampusAdmin", "DistrictCoordinator")
        body = request.get_json(silent=True) or {}

        # p2 ownership: Volunteer checks in self
        if role == "Volunteer":
            supplied = body.get("volunteer_id")
            if supplied is not None and supplied != user_id:
                from errors import forbidden
                raise forbidden("Volunteer role may only check in self")
            body = dict(body)
            body["volunteer_id"] = user_id

        # p3 existence: campus_id, volunteer_id, placement_id (payload field order)
        campus_id = body.get("campus_id")
        if campus_id is not None and campus_id not in db.campuses:
            raise not_found("campus_id does not resolve")
        vid = body.get("volunteer_id")
        if vid is not None and vid not in db.volunteers:
            raise not_found("volunteer_id does not resolve")
        pid = body.get("placement_id")
        pl = None
        if pid is not None:
            pl = db.placements.get(pid)
            if pl is None:
                raise not_found("placement_id does not resolve")

        # p4 state: volunteer must be ACTIVE; placement must be CONFIRMED when given
        if vid is not None:
            vol = db.volunteers[vid]
            if vol["status"] != "ACTIVE":
                raise APIError(ERR_VOLUNTEER_INVALID_STATE,
                               "check-in requires ACTIVE volunteer", 409)
        if pl is not None and pl["status"] != "CONFIRMED":
            raise APIError(ERR_PLACEMENT_INVALID_STATE,
                           "check-in with placement_id requires placement CONFIRMED", 409)

        # p6 referential coherence (placement-linked)
        if pl is not None and vid is not None:
            if pl["volunteer_id"] != vid:
                raise APIError(ERR_PLACEMENT_VOLUNTEER_MISMATCH,
                               "Referenced placement belongs to a different volunteer than the check-in subject", 422)
            opp = db.opportunities.get(pl["opportunity_id"])
            if opp is not None and campus_id is not None and opp["campus_id"] != campus_id:
                raise APIError(ERR_PLACEMENT_CAMPUS_MISMATCH,
                               "Check-in campus_id differs from the placement opportunity's campus_id", 422)

        # p7 temporal: placement-linked window [starts_at - 30min, ends_at] closed
        if pl is not None:
            opp = db.opportunities.get(pl["opportunity_id"])
            if opp is not None:
                now = clock.now()
                win_start = clock.parse_iso(opp["starts_at"]) - timedelta(minutes=30)
                win_end = clock.parse_iso(opp["ends_at"])
                if not (win_start <= now <= win_end):
                    raise APIError(ERR_OUTSIDE_CHECKIN_WINDOW,
                                   "Check-in with placement_id outside [starts_at - 30 minutes, ends_at]", 422)

        # p8: no OPEN check-in for volunteer
        if vid is not None:
            for c in db.check_ins.values():
                if c["volunteer_id"] == vid and c["status"] == "OPEN":
                    raise APIError(ERR_OPEN_CHECKIN_EXISTS,
                                   "Volunteer already has an OPEN VisitCheckIn (any campus)", 409)

        # p10 shape
        if campus_id is None:
            raise invalid_request("campus_id is required")
        if vid is None:
            raise invalid_request("volunteer_id is required")

        checked_in_at = clock.now_iso()
        campus = db.campuses[campus_id]
        badge_code = services.assign_badge_code(campus, checked_in_at)

        ci = {
            "id": db.new_id(),
            "created_at": clock.now_iso(),
            "updated_at": clock.now_iso(),
            "version": 1,
            "campus_id": campus_id,
            "volunteer_id": vid,
            "placement_id": pid,
            "checked_in_at": checked_in_at,
            "checked_out_at": None,
            "status": "OPEN",
            "badge_code": badge_code,
            "close_reason": None,
        }
        db.check_ins[ci["id"]] = ci
        return success_object(ci, 201)

    @app.route("/check-ins", methods=["GET"])
    def list_checkins():
        require_roles("DistrictCoordinator", "CampusAdmin")
        limit, offset = parse_pagination()
        items = list(db.check_ins.values())
        vid = request.args.get("volunteer_id")
        cid = request.args.get("campus_id")
        pid = request.args.get("placement_id")
        status = request.args.get("status")
        if vid is not None:
            items = [c for c in items if c["volunteer_id"] == vid]
        if cid is not None:
            items = [c for c in items if c["campus_id"] == cid]
        if pid is not None:
            items = [c for c in items if c["placement_id"] == pid]
        if status is not None:
            items = [c for c in items if c["status"] == status]
        page, total = paginate(items, limit, offset)
        return success_list(page, limit, offset, total)

    @app.route("/check-ins/<cid>", methods=["GET"])
    def get_checkin(cid):
        role, user_id = require_roles("DistrictCoordinator", "CampusAdmin", "Volunteer")
        ci = db.check_ins.get(cid)
        if ci is None:
            raise not_found()
        if role == "Volunteer":
            check_volunteer_ownership(role, user_id, ci["volunteer_id"])
        return success_object(ci, 200)

    @app.route("/check-ins/<cid>/check-out", methods=["POST"])
    def checkout(cid):
        role, user_id = require_roles("Volunteer", "CampusAdmin", "DistrictCoordinator")
        ci = db.check_ins.get(cid)
        if ci is None:
            raise not_found()
        # p2 ownership
        if role == "Volunteer":
            check_volunteer_ownership(role, user_id, ci["volunteer_id"])
        # p4 state
        if ci["status"] != "OPEN":
            raise APIError(ERR_CHECKIN_INVALID_STATE,
                           "Check-out attempted on a check-in not in OPEN", 409)
        ci["status"] = "CLOSED"
        ci["checked_out_at"] = clock.now_iso()
        ci["close_reason"] = "SELF" if role == "Volunteer" else "ADMIN"
        services.touch(ci)
        return success_object(ci, 200)
