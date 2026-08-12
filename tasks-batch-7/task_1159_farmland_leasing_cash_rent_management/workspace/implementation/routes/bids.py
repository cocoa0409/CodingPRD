from flask import Blueprint, request
from middleware import get_caller, require_role, get_json_body
from services.common import (require_string, require_enum, require_int,
                             require_nonneg_int, require_number, optional_number,
                             optional_int, parse_pagination, occ_check)
from response import success_object, success_list
from errors import ApiError
from db import db, new_common, touch, CLOCK
from services.serialize import serialize
from services.core import recompute_offering_scores

bp = Blueprint("bids", __name__)
READ_ROLES = {"FarmManager", "Landlord", "Tenant"}
LEASE_TYPES = {"CASH", "FLEX", "SHARE"}


def _validate_conditional_params(body, lease_type, partial=False):
    """Validate per-type required params. partial=True for PATCH (only validate
    fields that are present)."""
    def present(f):
        return f in body and body[f] is not None

    if lease_type == "CASH":
        if not partial or present("cash_bid_per_acre_cents"):
            if not present("cash_bid_per_acre_cents"):
                raise ApiError("ERR_VALIDATION", 400,
                               "cash_bid_per_acre_cents is required for CASH bids")
            require_nonneg_int(body, "cash_bid_per_acre_cents")
    elif lease_type == "FLEX":
        for f in ("flex_base_per_acre_cents", "flex_cap_cents", "revenue_trigger_cents"):
            if not partial or present(f):
                if not present(f):
                    raise ApiError("ERR_VALIDATION", 400, f"{f} is required for FLEX bids")
                require_nonneg_int(body, f)
        if not partial or present("flex_bonus_pct"):
            if not present("flex_bonus_pct"):
                raise ApiError("ERR_VALIDATION", 400, "flex_bonus_pct is required for FLEX bids")
            require_number(body, "flex_bonus_pct", minimum=0, maximum=1)
        if present("input_share_pct"):
            require_number(body, "input_share_pct", minimum=0, maximum=1)
    elif lease_type == "SHARE":
        for f in ("landlord_share_pct", "input_share_pct"):
            if not partial or present(f):
                if not present(f):
                    raise ApiError("ERR_VALIDATION", 400, f"{f} is required for SHARE bids")
                require_number(body, f, minimum=0, maximum=1)


@bp.route("/bids", methods=["POST"])
def create_bid():
    user_id, role = get_caller()
    require_role(role, {"Tenant"})
    body = get_json_body()
    offering_id = require_string(body, "offering_id")
    lease_type = require_enum(body, "lease_type", LEASE_TYPES)
    _validate_conditional_params(body, lease_type, partial=False)
    ce_bid = require_nonneg_int(body, "cash_equivalent_bid_cents_per_acre")

    # Existence
    offering = db.offerings.get(offering_id)
    if offering is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Offering {offering_id} not found")
    tenant = db.tenants.get(user_id)
    if tenant is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Tenant {user_id} not found")

    # State: tenant APPROVED; offering OPEN
    if tenant["status"] != "APPROVED":
        raise ApiError("ERR_TENANT_NOT_APPROVED", 409, "Tenant is not APPROVED")
    if offering["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Offering in state {offering['status']} is not accepting bids")

    # Deadline window
    if CLOCK.get() > offering["bid_deadline"]:
        raise ApiError("ERR_BID_WINDOW_CLOSED", 409, "Bid deadline has passed")

    # Minimum bid
    if ce_bid < offering["min_bid_per_acre_cents"]:
        raise ApiError("ERR_BID_BELOW_MINIMUM", 409,
                       "cash_equivalent_bid_cents_per_acre below minimum")

    rec = new_common()
    rec.update({
        "offering_id": offering_id,
        "tenant_id": user_id,
        "lease_type": lease_type,
        "cash_bid_per_acre_cents": body.get("cash_bid_per_acre_cents"),
        "flex_base_per_acre_cents": body.get("flex_base_per_acre_cents"),
        "flex_bonus_pct": body.get("flex_bonus_pct"),
        "flex_cap_cents": body.get("flex_cap_cents"),
        "revenue_trigger_cents": body.get("revenue_trigger_cents"),
        "landlord_share_pct": body.get("landlord_share_pct"),
        "input_share_pct": body.get("input_share_pct"),
        "cash_equivalent_bid_cents_per_acre": ce_bid,
        "evaluation_score": None,
        "accepted_at": None,
        "status": "SUBMITTED",
    })
    db.bids[rec["id"]] = rec
    recompute_offering_scores(offering_id)
    return success_object(serialize("bid", rec), status=201)


@bp.route("/bids/<bidId>", methods=["GET"])
def get_bid(bidId):
    _, role = get_caller()
    require_role(role, READ_ROLES)
    rec = db.bids.get(bidId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Bid {bidId} not found")
    return success_object(serialize("bid", rec))


@bp.route("/bids", methods=["GET"])
def list_bids():
    _, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.bids.values(), key=lambda r: r["created_at"])
    for param, field in (("offering_id", "offering_id"), ("tenant_id", "tenant_id"),
                         ("status", "status")):
        q = request.args.get(param)
        if q is not None:
            items = [r for r in items if r[field] == q]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize("bid", r) for r in page], limit, offset, total)


@bp.route("/bids/<bidId>", methods=["PATCH"])
def revise_bid(bidId):
    user_id, role = get_caller()
    require_role(role, {"Tenant"})
    body = get_json_body()

    rec = db.bids.get(bidId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Bid {bidId} not found")

    # Ownership
    if rec["tenant_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller does not own this bid")

    # State: only SUBMITTED bids are revisable
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Bid in state {rec['status']} cannot be revised")

    # OCC
    occ_check(body, "expected_bid_version", rec["version"])

    # Validate any provided fields against type rules (partial)
    _validate_conditional_params(body, rec["lease_type"], partial=True)
    if "cash_equivalent_bid_cents_per_acre" in body and body["cash_equivalent_bid_cents_per_acre"] is not None:
        require_nonneg_int(body, "cash_equivalent_bid_cents_per_acre")

    # Apply revisions
    for f in ("cash_bid_per_acre_cents", "flex_base_per_acre_cents", "flex_bonus_pct",
              "flex_cap_cents", "revenue_trigger_cents", "landlord_share_pct",
              "input_share_pct", "cash_equivalent_bid_cents_per_acre"):
        if f in body and body[f] is not None:
            rec[f] = body[f]

    # Min-bid check against revised figure
    offering = db.offerings.get(rec["offering_id"])
    if offering is not None and rec["cash_equivalent_bid_cents_per_acre"] < offering["min_bid_per_acre_cents"]:
        raise ApiError("ERR_BID_BELOW_MINIMUM", 409,
                       "cash_equivalent_bid_cents_per_acre below minimum")

    touch(rec)
    recompute_offering_scores(rec["offering_id"])
    return success_object(serialize("bid", rec))


@bp.route("/bids/<bidId>/withdraw", methods=["POST"])
def withdraw_bid(bidId):
    user_id, role = get_caller()
    require_role(role, {"Tenant"})
    rec = db.bids.get(bidId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Bid {bidId} not found")
    if rec["tenant_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller does not own this bid")
    if rec["status"] not in ("SUBMITTED", "SHORTLISTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Bid in state {rec['status']} cannot be withdrawn")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    recompute_offering_scores(rec["offering_id"])
    return success_object(serialize("bid", rec))


@bp.route("/bids/<bidId>/shortlist", methods=["POST"])
def shortlist_bid(bidId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.bids.get(bidId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Bid {bidId} not found")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Bid in state {rec['status']} cannot be shortlisted")
    offering = db.offerings.get(rec["offering_id"])
    if offering is None or offering["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Offering is not OPEN")
    rec["status"] = "SHORTLISTED"
    touch(rec)
    recompute_offering_scores(rec["offering_id"])
    return success_object(serialize("bid", rec))


@bp.route("/bids/<bidId>/demote", methods=["POST"])
def demote_bid(bidId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.bids.get(bidId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Bid {bidId} not found")
    if rec["status"] != "SHORTLISTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Bid in state {rec['status']} cannot be demoted")
    rec["status"] = "SUBMITTED"
    touch(rec)
    recompute_offering_scores(rec["offering_id"])
    return success_object(serialize("bid", rec))
