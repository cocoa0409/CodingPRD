"""Opportunity endpoints including publish/cancel/match."""

from flask import request

import db
import clock
import services
from errors import (
    APIError, not_found, invalid_request,
    ERR_OPPORTUNITY_INVALID_STATE, ERR_OPPORTUNITY_WINDOW_PASSED,
    ERR_OPPORTUNITY_FULL,
)
from middleware import require_roles
from pagination import parse_pagination, paginate
from response import success_object, success_list

REQUIRED_CONTACT_TYPES = ("SUPERVISED", "UNSUPERVISED")
RESTRICTED_CATEGORIES = ("NONE", "TRANSPORT", "ONE_ON_ONE")


def register(app):
    @app.route("/opportunities", methods=["POST"])
    def create_opportunity():
        require_roles("CampusAdmin", "DistrictCoordinator")
        body = request.get_json(silent=True) or {}

        # p3 existence
        campus_id = body.get("campus_id")
        if campus_id is not None and campus_id not in db.campuses:
            raise not_found("campus_id does not resolve")

        # p10 shape
        if campus_id is None:
            raise invalid_request("campus_id is required")
        title = body.get("title")
        if not title or not isinstance(title, str):
            raise invalid_request("title is required")
        description = body.get("description", "")
        rct = body.get("required_contact_type")
        if rct not in REQUIRED_CONTACT_TYPES:
            raise invalid_request("required_contact_type must be SUPERVISED or UNSUPERVISED")
        rc = body.get("restricted_category")
        if rc not in RESTRICTED_CATEGORIES:
            raise invalid_request("restricted_category must be NONE, TRANSPORT, or ONE_ON_ONE")
        capacity = body.get("capacity")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise invalid_request("capacity must be an integer >= 1")
        starts_raw = body.get("starts_at")
        ends_raw = body.get("ends_at")
        if not starts_raw or not ends_raw:
            raise invalid_request("starts_at and ends_at are required")
        try:
            starts = clock.parse_iso(starts_raw)
            ends = clock.parse_iso(ends_raw)
        except (ValueError, TypeError):
            raise invalid_request("starts_at and ends_at must be valid ISO8601 datetimes")
        if not (starts < ends):
            raise invalid_request("starts_at must be strictly before ends_at")

        opp = {
            "id": db.new_id(),
            "created_at": clock.now_iso(),
            "updated_at": clock.now_iso(),
            "version": 1,
            "campus_id": campus_id,
            "title": title,
            "description": description if isinstance(description, str) else "",
            "required_contact_type": rct,
            "restricted_category": rc,
            "capacity": capacity,
            "starts_at": clock.to_iso(starts),
            "ends_at": clock.to_iso(ends),
            "status": "DRAFT",
            "committed_count": 0,
            "projected_count": 0,
        }
        db.opportunities[opp["id"]] = opp
        return success_object(opp, 201)

    @app.route("/opportunities", methods=["GET"])
    def list_opportunities():
        require_roles("DistrictCoordinator", "CampusAdmin", "Volunteer")
        limit, offset = parse_pagination()
        items = list(db.opportunities.values())
        campus_id = request.args.get("campus_id")
        status = request.args.get("status")
        rct = request.args.get("required_contact_type")
        if campus_id is not None:
            items = [o for o in items if o["campus_id"] == campus_id]
        if status is not None:
            items = [o for o in items if o["status"] == status]
        if rct is not None:
            items = [o for o in items if o["required_contact_type"] == rct]
        page, total = paginate(items, limit, offset)
        return success_list(page, limit, offset, total)

    @app.route("/opportunities/<oid>", methods=["GET"])
    def get_opportunity(oid):
        require_roles("DistrictCoordinator", "CampusAdmin", "Volunteer")
        opp = db.opportunities.get(oid)
        if opp is None:
            raise not_found()
        return success_object(opp, 200)

    @app.route("/opportunities/<oid>/publish", methods=["POST"])
    def publish(oid):
        require_roles("CampusAdmin", "DistrictCoordinator")
        opp = db.opportunities.get(oid)
        if opp is None:
            raise not_found()
        # p4 state
        if opp["status"] != "DRAFT":
            raise APIError(ERR_OPPORTUNITY_INVALID_STATE, "Publish requires DRAFT", 409)
        # p7 temporal
        if clock.parse_iso(opp["starts_at"]) <= clock.now():
            raise APIError(ERR_OPPORTUNITY_WINDOW_PASSED, "Publish attempted when starts_at <= now", 422)
        opp["status"] = "OPEN"
        services.touch(opp)
        return success_object(opp, 200)

    @app.route("/opportunities/<oid>/cancel", methods=["POST"])
    def cancel(oid):
        require_roles("CampusAdmin", "DistrictCoordinator")
        opp = db.opportunities.get(oid)
        if opp is None:
            raise not_found()
        # p4 state
        if opp["status"] not in ("DRAFT", "OPEN"):
            raise APIError(ERR_OPPORTUNITY_INVALID_STATE, "cancel requires {DRAFT, OPEN}", 409)
        # cascade placements
        for pl in list(db.placements.values()):
            if pl["opportunity_id"] == opp["id"] and pl["status"] in ("REQUESTED", "CONFIRMED"):
                pl["status"] = "CANCELLED"
                pl["cancel_reason"] = "OPPORTUNITY_CANCELLED"
                services.touch(pl)
        services.recompute_opportunity_counts(opp)
        opp["status"] = "CANCELLED"
        services.touch(opp)
        return success_object(opp, 200)

    @app.route("/opportunities/<oid>/match", methods=["POST"])
    def match(oid):
        require_roles("DistrictCoordinator")
        opp = db.opportunities.get(oid)
        if opp is None:
            raise not_found()
        # p4 state
        if opp["status"] != "OPEN":
            raise APIError(ERR_OPPORTUNITY_INVALID_STATE, "match requires OPEN", 409)

        body = request.get_json(silent=True) or {}
        max_placements = body.get("max_placements")
        if max_placements is not None:
            if isinstance(max_placements, bool) or not isinstance(max_placements, int) or max_placements < 0:
                raise invalid_request("max_placements must be a non-negative integer")

        req_level = services.REQUIRED_LEVEL_FOR_CONTACT[opp["required_contact_type"]]
        o_start = clock.parse_iso(opp["starts_at"])
        o_end = clock.parse_iso(opp["ends_at"])

        # Build eligibility pool (silent filters per PRD §3.4)
        pool = []
        for vol in db.volunteers.values():
            if vol["status"] != "ACTIVE":
                continue
            # latest cleared check level adequate for the level implied by
            # the opportunity's required_contact_type (PRD §2.6 / §3.4)
            latest = services.latest_cleared_check(vol)
            if latest is None or not services.level_adequate(latest["level"], req_level):
                continue
            # restriction flags
            if services.flags_block_category(vol["restriction_flags"], opp["restricted_category"]):
                continue
            # training compliance
            if not services.training_compliance(vol):
                continue
            # no existing placement on this opportunity (any status counts for match exclusion)
            existing = [
                p for p in db.placements.values()
                if p["opportunity_id"] == opp["id"] and p["volunteer_id"] == vol["id"]
            ]
            if existing:
                continue
            # no overlapping CONFIRMED placement (half-open)
            conflict = False
            for p in db.placements.values():
                if p["volunteer_id"] != vol["id"] or p["status"] != "CONFIRMED":
                    continue
                other = db.opportunities.get(p["opportunity_id"])
                if other is None:
                    continue
                os_ = clock.parse_iso(other["starts_at"])
                oe_ = clock.parse_iso(other["ends_at"])
                if services.half_open_overlap(o_start, o_end, os_, oe_):
                    conflict = True
                    break
            if conflict:
                continue
            pool.append(vol)

        # rank: total_verified_hours ASC, tie-break created_at ASC
        pool.sort(key=lambda v: (v["total_verified_hours"], v["created_at"], v["id"]))

        committed = sum(
            1 for p in db.placements.values()
            if p["opportunity_id"] == opp["id"] and p["status"] == "CONFIRMED"
        )
        remaining = opp["capacity"] - committed

        created_ids = []
        for vol in pool:
            if remaining <= 0:
                break
            if max_placements is not None and len(created_ids) >= max_placements:
                break
            pl = {
                "id": db.new_id(),
                "created_at": clock.now_iso(),
                "updated_at": clock.now_iso(),
                "version": 1,
                "opportunity_id": opp["id"],
                "volunteer_id": vol["id"],
                "status": "CONFIRMED",
                "confirmed_at": clock.now_iso(),
                "cancel_reason": None,
            }
            db.placements[pl["id"]] = pl
            created_ids.append(pl["id"])
            remaining -= 1

        services.recompute_opportunity_counts(opp)
        services.touch(opp)

        result = {
            "matched_count": len(created_ids),
            "created_placement_ids": created_ids,
            "committed_count": opp["committed_count"],
            "remaining_capacity": opp["capacity"] - opp["committed_count"],
        }
        return success_object(result, 200)
