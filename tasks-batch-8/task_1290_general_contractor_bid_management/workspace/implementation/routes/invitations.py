from flask import Blueprint, request

import errors
from db import DB, CLOCK, new_id, stamp_new, touch
from middleware import (
    get_context, require_role, get_json_body, require_fields, reject_unexpected,
    require_enum, parse_limit_offset,
)
from response import success_object, success_list
from services import bids as bid_svc

bp = Blueprint("invitations", __name__)

ESTIMATORS = {"LeadEstimator", "ChiefEstimator", "PrequalReviewer"}


def serialize_invitation(inv):
    return {
        "id": inv["id"],
        "bid_package_id": inv["bid_package_id"],
        "subcontractor_id": inv["subcontractor_id"],
        "status": inv["status"],
        "responded_at": inv["responded_at"],
        "first_plan_room_access_at": inv["first_plan_room_access_at"],
        "plan_room_access_count": inv["plan_room_access_count"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


def get_invitation_or_404(inv_id):
    inv = DB.invitations.get(inv_id)
    if inv is None:
        raise errors.err_invitation_not_found()
    return inv


@bp.post("/invitations")
def create_invitation():
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    body = get_json_body()
    reject_unexpected(body, {"bid_package_id", "subcontractor_id"})
    require_fields(body, ["bid_package_id", "subcontractor_id"])
    pkg_id = body["bid_package_id"]
    sub_id = body["subcontractor_id"]
    if not isinstance(pkg_id, str) or not isinstance(sub_id, str):
        raise errors.err_invalid_request("bid_package_id and subcontractor_id must be strings")
    # Existence, left-to-right body FK order: bid_package_id then subcontractor_id
    pkg = DB.bid_packages.get(pkg_id)
    if pkg is None:
        raise errors.err_package_not_found()
    sub = DB.subcontractors.get(sub_id)
    if sub is None:
        raise errors.err_subcontractor_not_found()
    # Allowed while package is DRAFT or PUBLISHED
    if pkg["status"] not in ("DRAFT", "PUBLISHED"):
        raise errors.err_package_invalid_state("Invitations allowed only while DRAFT or PUBLISHED")
    for inv in DB.invitations.values():
        if inv["bid_package_id"] == pkg_id and inv["subcontractor_id"] == sub_id:
            raise errors.err_duplicate_invitation()
    inv = {
        "id": new_id(),
        "bid_package_id": pkg_id,
        "subcontractor_id": sub_id,
        "status": "SENT",
        "responded_at": None,
        "first_plan_room_access_at": None,
        "plan_room_access_count": 0,
    }
    stamp_new(inv)
    inv["_created_at_dt"] = CLOCK.now()
    DB.invitations[inv["id"]] = inv
    return success_object(serialize_invitation(inv), 201)


@bp.get("/invitations")
def list_invitations():
    user_id, role = get_context()
    require_role(role, ESTIMATORS | {"Subcontractor"})
    limit, offset = parse_limit_offset(request.args)
    pkg_f = request.args.get("bid_package_id")
    sub_f = request.args.get("subcontractor_id")
    status_f = request.args.get("status")
    items = sorted(DB.invitations.values(), key=lambda i: (i["_created_at_dt"], i["id"]))
    if role == "Subcontractor":
        items = [i for i in items if i["subcontractor_id"] == user_id]
    if pkg_f is not None:
        items = [i for i in items if i["bid_package_id"] == pkg_f]
    if sub_f is not None:
        items = [i for i in items if i["subcontractor_id"] == sub_f]
    if status_f is not None:
        items = [i for i in items if i["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_invitation(i) for i in page], limit, offset, total)


@bp.get("/invitations/<inv_id>")
def read_invitation(inv_id):
    user_id, role = get_context()
    require_role(role, ESTIMATORS | {"Subcontractor"})
    inv = get_invitation_or_404(inv_id)
    if role == "Subcontractor" and inv["subcontractor_id"] != user_id:
        raise errors.err_forbidden_ownership()
    return success_object(serialize_invitation(inv))


@bp.post("/invitations/<inv_id>/respond")
def respond_invitation(inv_id):
    user_id, role = get_context()
    require_role(role, {"Subcontractor"})
    inv = get_invitation_or_404(inv_id)
    body = get_json_body()
    reject_unexpected(body, {"intent"})
    require_fields(body, ["intent"])
    intent = require_enum(body, "intent", {"BIDDING", "DECLINED"})
    if inv["subcontractor_id"] != user_id:
        raise errors.err_forbidden_ownership()

    current = inv["status"]
    permitted = {
        ("SENT", "BIDDING"),
        ("SENT", "DECLINED"),
        ("BIDDING", "DECLINED"),
        ("DECLINED", "BIDDING"),
    }
    if (current, intent) not in permitted:
        raise errors.err_invitation_invalid_state()

    pkg = DB.bid_packages.get(inv["bid_package_id"])
    if current == "DECLINED" and intent == "BIDDING":
        # Reconsider requires package PUBLISHED
        if pkg is None or pkg["status"] != "PUBLISHED":
            raise errors.err_package_not_accepting_bids()

    inv["status"] = intent
    inv["responded_at"] = __import__("db").iso_now()
    touch(inv)

    if current == "BIDDING" and intent == "DECLINED":
        # Cascade: PENDING acks for (this package's addenda, this sub) -> WAIVED
        for ack in DB.acks.values():
            if ack["subcontractor_id"] != inv["subcontractor_id"] or ack["status"] != "PENDING":
                continue
            add = DB.addendums.get(ack["addendum_id"])
            if add and add["bid_package_id"] == inv["bid_package_id"]:
                ack["status"] = "WAIVED"
                ack["waived_reason"] = "bidder declined"
                touch(ack)
        bid_svc.recompute_ack_complete_for(inv["bid_package_id"], inv["subcontractor_id"])
    elif current == "DECLINED" and intent == "BIDDING":
        # Reconsider cascade: create PENDING acks for addenda lacking one in
        # {PENDING, ACKNOWLEDGED} for this subcontractor (WAIVED rows retained).
        for add in DB.addendums.values():
            if add["bid_package_id"] != inv["bid_package_id"]:
                continue
            live = any(
                a["addendum_id"] == add["id"]
                and a["subcontractor_id"] == inv["subcontractor_id"]
                and a["status"] in ("PENDING", "ACKNOWLEDGED")
                for a in DB.acks.values()
            )
            if not live:
                ack = {
                    "id": new_id(),
                    "addendum_id": add["id"],
                    "subcontractor_id": inv["subcontractor_id"],
                    "status": "PENDING",
                    "acknowledged_at": None,
                    "waived_reason": None,
                }
                stamp_new(ack)
                ack["_created_at_dt"] = CLOCK.now()
                DB.acks[ack["id"]] = ack
        bid_svc.recompute_ack_complete_for(inv["bid_package_id"], inv["subcontractor_id"])

    return success_object(serialize_invitation(inv))


@bp.post("/invitations/<inv_id>/plan-room-access")
def plan_room_access(inv_id):
    user_id, role = get_context()
    require_role(role, {"Subcontractor"})
    inv = get_invitation_or_404(inv_id)
    if inv["subcontractor_id"] != user_id:
        raise errors.err_forbidden_ownership()
    pkg = DB.bid_packages.get(inv["bid_package_id"])
    if pkg is None or pkg["status"] != "PUBLISHED":
        raise errors.err_package_not_accepting_bids()
    if inv["status"] == "DECLINED":
        raise errors.err_invitation_declined()
    if inv["status"] not in ("SENT", "BIDDING"):
        raise errors.err_invitation_invalid_state()
    if inv["first_plan_room_access_at"] is None:
        inv["first_plan_room_access_at"] = __import__("db").iso_now()
    inv["plan_room_access_count"] += 1
    touch(inv)
    return success_object(serialize_invitation(inv))
