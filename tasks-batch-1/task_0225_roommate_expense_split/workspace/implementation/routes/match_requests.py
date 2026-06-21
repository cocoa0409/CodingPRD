"""MatchRequest endpoints and lifecycle (PRD §3.1, §3.2)."""
from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import calc

bp = Blueprint("match_requests", __name__)

ALL_ROLES = {"Roommate", "DisputeMediator", "PlatformOperator"}
SCORING = {"STRICT", "LENIENT"}


def _household_for_listing(listing_id):
    for h in db.households.values():
        if h["listing_id"] == listing_id and h["status"] != "DISSOLVED":
            return h
    return None


@bp.route("/match-requests", methods=["POST"])
def create_match_request():
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        body = validate.get_json_body()
        listing_id = validate.require_str(body, "listing_id")
        applicant_id = validate.require_str(body, "applicant_id")
        scoring_mode = validate.require_enum(body, "scoring_mode", SCORING, default="STRICT")
        # existence (left-to-right): listing then applicant
        listing = db.room_listings.get(listing_id)
        if not listing:
            raise err("ERR_NOT_FOUND", "listing_id does not exist.")
        applicant = db.roommate_profiles.get(applicant_id)
        if not applicant:
            raise err("ERR_NOT_FOUND", "applicant_id does not exist.")
        # no self-application
        if applicant_id == listing["lister_id"]:
            raise err("ERR_SELF_APPLICATION", "Applicant cannot be the lister.")
        score = calc.compatibility_score(applicant, listing, scoring_mode)
        mr = {
            "listing_id": listing_id,
            "applicant_id": applicant_id,
            "scoring_mode": scoring_mode,
            "compatibility_score": score,
            "status": "PENDING",
        }
        models.stamp_create(mr)
        db.match_requests[mr["id"]] = mr
        return response.ok(models.serialize(mr), 201)


@bp.route("/match-requests/<mid>", methods=["GET"])
def get_match_request(mid):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        mr = db.match_requests.get(mid)
        if not mr:
            raise err("ERR_NOT_FOUND", "Match request not found.")
        return response.ok(models.serialize(mr))


@bp.route("/match-requests", methods=["GET"])
def list_match_requests():
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        limit, offset = parse_pagination()
        items = list(db.match_requests.values())
        listing_id = request.args.get("listing_id")
        applicant_id = request.args.get("applicant_id")
        if listing_id is not None:
            items = [x for x in items if x["listing_id"] == listing_id]
        if applicant_id is not None:
            items = [x for x in items if x["applicant_id"] == applicant_id]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/match-requests/<mid>/accept", methods=["POST"])
def accept_match_request(mid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        mr = db.match_requests.get(mid)
        if not mr:
            raise err("ERR_NOT_FOUND", "Match request not found.")
        listing = db.room_listings.get(mr["listing_id"])
        # ownership: acting roommate must be the lister
        if p.user_id != listing["lister_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the lister may accept.")
        if mr["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Match request is not PENDING.")
        # compatibility gate (priority 17). Listing-OPEN and household-capacity are NOT
        # enforced at accept: accept only creates a PENDING membership, and the capacity /
        # single-occupancy gates are enforced at activation (ERR_ROOM_AT_CAPACITY /
        # ERR_OCCUPANCY_OVERLAP), allowing applications past capacity to be queued.
        if mr["compatibility_score"] < calc.MATCH_THRESHOLD:
            raise err("ERR_BELOW_MATCH_THRESHOLD", "Compatibility score below threshold.")
        household = _household_for_listing(listing["id"])

        mr["status"] = "ACCEPTED"
        models.touch(mr)
        if household is None:
            household = {
                "listing_id": listing["id"],
                "manager_id": listing["lister_id"],
                "split_policy": listing["split_policy"],
                "status": "FORMING",
                "active_member_count": 0,
                "ledger_sum_cents": 0,
            }
            models.stamp_create(household)
            db.households[household["id"]] = household
        membership = {
            "household_id": household["id"],
            "profile_id": mr["applicant_id"],
            "move_in_date": None,
            "planned_move_out_date": None,
            "actual_move_out_date": None,
            "occupied_days_estimate": 0,
            "occupied_days_actual": 0,
            "status": "PENDING",
        }
        models.stamp_create(membership)
        db.memberships[membership["id"]] = membership
        return response.ok(models.serialize(mr))


@bp.route("/match-requests/<mid>/reject", methods=["POST"])
def reject_match_request(mid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        mr = db.match_requests.get(mid)
        if not mr:
            raise err("ERR_NOT_FOUND", "Match request not found.")
        listing = db.room_listings.get(mr["listing_id"])
        if p.user_id != listing["lister_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the lister may reject.")
        if mr["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Match request is not PENDING.")
        mr["status"] = "REJECTED"
        models.touch(mr)
        return response.ok(models.serialize(mr))


@bp.route("/match-requests/<mid>/withdraw", methods=["POST"])
def withdraw_match_request(mid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        mr = db.match_requests.get(mid)
        if not mr:
            raise err("ERR_NOT_FOUND", "Match request not found.")
        if p.user_id != mr["applicant_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the applicant may withdraw.")
        if mr["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Match request is not PENDING.")
        mr["status"] = "WITHDRAWN"
        models.touch(mr)
        return response.ok(models.serialize(mr))


@bp.route("/match-requests/<mid>/reapply", methods=["POST"])
def reapply_match_request(mid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        mr = db.match_requests.get(mid)
        if not mr:
            raise err("ERR_NOT_FOUND", "Match request not found.")
        if p.user_id != mr["applicant_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the applicant may re-apply.")
        if mr["status"] != "WITHDRAWN":
            raise err("ERR_INVALID_STATE", "Match request is not WITHDRAWN.")
        listing = db.room_listings.get(mr["listing_id"])
        if listing["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Listing is not OPEN.")
        applicant = db.roommate_profiles.get(mr["applicant_id"])
        mr["compatibility_score"] = calc.compatibility_score(applicant, listing, mr["scoring_mode"])
        mr["status"] = "PENDING"
        models.touch(mr)
        return response.ok(models.serialize(mr))
