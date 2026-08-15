"""Placement endpoints: request, confirm, cancel, complete, list, read."""

from flask import request

import db
import clock
import services
from errors import (
    APIError, not_found, invalid_request,
    ERR_OPPORTUNITY_INVALID_STATE, ERR_OPPORTUNITY_FULL,
    ERR_PLACEMENT_INVALID_STATE, ERR_PLACEMENT_TIME_CONFLICT,
    ERR_PLACEMENT_WINDOW_OPEN, ERR_NO_CHECKIN_FOR_PLACEMENT,
    ERR_VOLUNTEER_INVALID_STATE, ERR_DUPLICATE_PLACEMENT,
    ERR_CLEARANCE_LEVEL_INSUFFICIENT, ERR_RESTRICTED_ROLE,
    ERR_TRAINING_INCOMPLETE,
)
from middleware import require_roles, check_volunteer_ownership
from pagination import parse_pagination, paginate
from response import success_object, success_list


def register(app):
    @app.route("/placements", methods=["POST"])
    def create_placement():
        role, user_id = require_roles("Volunteer", "DistrictCoordinator")
        body = request.get_json(silent=True) or {}

        # p2 ownership: Volunteer role -> volunteer_id forced to caller
        if role == "Volunteer":
            supplied = body.get("volunteer_id")
            if supplied is not None and supplied != user_id:
                from errors import forbidden
                raise forbidden("Volunteer role may only request placements for self")
            body = dict(body)
            body["volunteer_id"] = user_id

        # p3 existence: opportunity_id, then volunteer_id (payload field order)
        oid = body.get("opportunity_id")
        if oid is not None and oid not in db.opportunities:
            raise not_found("opportunity_id does not resolve")
        vid = body.get("volunteer_id")
        if vid is not None and vid not in db.volunteers:
            raise not_found("volunteer_id does not resolve")

        # p4 state: opportunity OPEN, volunteer ACTIVE
        if oid is not None:
            opp = db.opportunities[oid]
            if opp["status"] != "OPEN":
                raise APIError(ERR_OPPORTUNITY_INVALID_STATE,
                               "placement request requires OPEN opportunity", 409)
        if vid is not None:
            vol = db.volunteers[vid]
            if vol["status"] != "ACTIVE":
                raise APIError(ERR_VOLUNTEER_INVALID_STATE,
                               "placement request requires ACTIVE volunteer", 409)

        # p8 duplicate: no placement in {REQUESTED, CONFIRMED} for (volunteer, opportunity)
        if oid is not None and vid is not None:
            for p in db.placements.values():
                if p["opportunity_id"] == oid and p["volunteer_id"] == vid and p["status"] in ("REQUESTED", "CONFIRMED"):
                    raise APIError(ERR_DUPLICATE_PLACEMENT,
                                   "A placement in {REQUESTED, CONFIRMED} already exists for (volunteer, opportunity)", 409)

        # p10 shape
        if oid is None:
            raise invalid_request("opportunity_id is required")
        if vid is None:
            raise invalid_request("volunteer_id is required")

        pl = {
            "id": db.new_id(),
            "created_at": clock.now_iso(),
            "updated_at": clock.now_iso(),
            "version": 1,
            "opportunity_id": oid,
            "volunteer_id": vid,
            "status": "REQUESTED",
            "confirmed_at": None,
            "cancel_reason": None,
        }
        db.placements[pl["id"]] = pl

        opp = db.opportunities[oid]
        services.recompute_opportunity_counts(opp)
        services.touch(opp)

        return success_object(pl, 201)

    @app.route("/placements", methods=["GET"])
    def list_placements():
        require_roles("DistrictCoordinator", "CampusAdmin")
        limit, offset = parse_pagination()
        items = list(db.placements.values())
        vid = request.args.get("volunteer_id")
        oid = request.args.get("opportunity_id")
        status = request.args.get("status")
        if vid is not None:
            items = [p for p in items if p["volunteer_id"] == vid]
        if oid is not None:
            items = [p for p in items if p["opportunity_id"] == oid]
        if status is not None:
            items = [p for p in items if p["status"] == status]
        page, total = paginate(items, limit, offset)
        return success_list(page, limit, offset, total)

    @app.route("/placements/<pid>", methods=["GET"])
    def get_placement(pid):
        role, user_id = require_roles("DistrictCoordinator", "CampusAdmin", "Volunteer")
        pl = db.placements.get(pid)
        if pl is None:
            raise not_found()
        if role == "Volunteer":
            check_volunteer_ownership(role, user_id, pl["volunteer_id"])
        return success_object(pl, 200)

    @app.route("/placements/<pid>/confirm", methods=["POST"])
    def confirm(pid):
        require_roles("CampusAdmin", "DistrictCoordinator")
        pl = db.placements.get(pid)
        if pl is None:
            raise not_found()
        opp = db.opportunities.get(pl["opportunity_id"])
        vol = db.volunteers.get(pl["volunteer_id"])

        # p4 state
        if pl["status"] != "REQUESTED":
            raise APIError(ERR_PLACEMENT_INVALID_STATE, "Confirm requires REQUESTED", 409)
        if opp is None or opp["status"] != "OPEN":
            raise APIError(ERR_OPPORTUNITY_INVALID_STATE,
                           "placement confirm requires OPEN opportunity", 409)
        if vol is None or vol["status"] != "ACTIVE":
            raise APIError(ERR_VOLUNTEER_INVALID_STATE,
                           "placement confirm requires ACTIVE volunteer", 409)

        # p5 screening gates in order
        req_level = services.REQUIRED_LEVEL_FOR_CONTACT[opp["required_contact_type"]]
        # (a) clearance-level adequacy (PRD §2.6): the volunteer's LATEST
        # cleared check level must be adequate for the level implied by the
        # opportunity's required_contact_type. Expiry is deliberately not a
        # stage-five gate (§2.7 note): the clock sweep demotes expired ACTIVE
        # volunteers, which then fails stage 4 instead.
        latest = services.latest_cleared_check(vol)
        if latest is None or not services.level_adequate(latest["level"], req_level):
            raise APIError(ERR_CLEARANCE_LEVEL_INSUFFICIENT,
                           "Volunteer's latest cleared check level is below the level the opportunity requires", 422)
        # (b) restriction flags
        if services.flags_block_category(vol["restriction_flags"], opp["restricted_category"]):
            raise APIError(ERR_RESTRICTED_ROLE,
                           "Volunteer.restriction_flags block the opportunity's restricted_category", 422)
        # (c) training compliance
        if not services.training_compliance(vol):
            raise APIError(ERR_TRAINING_INCOMPLETE,
                           "A required TrainingModule lacks a valid (unexpired) TrainingRecord", 422)

        # p7 temporal: half-open overlap with other CONFIRMED placements
        o_start = clock.parse_iso(opp["starts_at"])
        o_end = clock.parse_iso(opp["ends_at"])
        for other_p in db.placements.values():
            if other_p["id"] == pl["id"]:
                continue
            if other_p["volunteer_id"] != vol["id"] or other_p["status"] != "CONFIRMED":
                continue
            other_opp = db.opportunities.get(other_p["opportunity_id"])
            if other_opp is None:
                continue
            os_ = clock.parse_iso(other_opp["starts_at"])
            oe_ = clock.parse_iso(other_opp["ends_at"])
            if services.half_open_overlap(o_start, o_end, os_, oe_):
                raise APIError(ERR_PLACEMENT_TIME_CONFLICT,
                               "Confirm would create overlapping CONFIRMED placements", 422)

        # p8 capacity
        services.recompute_opportunity_counts(opp)
        if opp["committed_count"] >= opp["capacity"]:
            raise APIError(ERR_OPPORTUNITY_FULL,
                           "Confirm attempted when opportunity.committed_count >= capacity", 409)

        pl["status"] = "CONFIRMED"
        pl["confirmed_at"] = clock.now_iso()
        services.touch(pl)
        services.recompute_opportunity_counts(opp)
        services.touch(opp)
        return success_object(pl, 200)

    @app.route("/placements/<pid>/cancel", methods=["POST"])
    def cancel_placement(pid):
        role, user_id = require_roles("Volunteer", "CampusAdmin", "DistrictCoordinator")
        pl = db.placements.get(pid)
        if pl is None:
            raise not_found()
        # p2 ownership
        if role == "Volunteer":
            check_volunteer_ownership(role, user_id, pl["volunteer_id"])
        # p4 state
        if pl["status"] not in ("REQUESTED", "CONFIRMED"):
            raise APIError(ERR_PLACEMENT_INVALID_STATE,
                           "cancel requires {REQUESTED, CONFIRMED}", 409)

        pl["status"] = "CANCELLED"
        pl["cancel_reason"] = "VOLUNTEER_WITHDRAW" if role == "Volunteer" else "ADMIN_CANCEL"
        services.touch(pl)
        opp = db.opportunities.get(pl["opportunity_id"])
        if opp is not None:
            services.recompute_opportunity_counts(opp)
            services.touch(opp)
        return success_object(pl, 200)

    @app.route("/placements/<pid>/complete", methods=["POST"])
    def complete_placement(pid):
        require_roles("CampusAdmin", "DistrictCoordinator")
        pl = db.placements.get(pid)
        if pl is None:
            raise not_found()
        opp = db.opportunities.get(pl["opportunity_id"])

        # p4 state
        if pl["status"] != "CONFIRMED":
            raise APIError(ERR_PLACEMENT_INVALID_STATE, "complete requires CONFIRMED", 409)

        # p7 temporal: now >= opportunity.ends_at
        if opp is not None and clock.now() < clock.parse_iso(opp["ends_at"]):
            raise APIError(ERR_PLACEMENT_WINDOW_OPEN,
                           "Complete attempted before opportunity.ends_at", 422)

        # p8: >= 1 CLOSED check-in for placement
        has_closed = any(
            c for c in db.check_ins.values()
            if c["placement_id"] == pl["id"] and c["status"] == "CLOSED"
        )
        if not has_closed:
            raise APIError(ERR_NO_CHECKIN_FOR_PLACEMENT,
                           "Complete attempted with zero CLOSED VisitCheckIns linked to the placement", 422)

        pl["status"] = "COMPLETED"
        services.touch(pl)
        if opp is not None:
            services.recompute_opportunity_counts(opp)
            services.touch(opp)
        return success_object(pl, 200)
