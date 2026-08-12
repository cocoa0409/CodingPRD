from flask import Blueprint, request
from middleware import get_caller, require_role, get_json_body
from services.common import (require_string, require_int, require_datetime,
                             require_nonneg_int, parse_pagination)
from response import success_object, success_list
from errors import ApiError
from db import db, new_common, touch, CLOCK
from services.serialize import serialize
from services.core import recompute_offering_scores

bp = Blueprint("offerings", __name__)
READ_ROLES = {"FarmManager", "Landlord", "Tenant"}


@bp.route("/offerings", methods=["POST"])
def create_offering():
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    field_id = require_string(body, "field_id")
    term_years = require_int(body, "term_years", minimum=1, maximum=5)
    term_start = require_datetime(body, "term_start_date")
    min_bid = require_nonneg_int(body, "min_bid_per_acre_cents")
    ref_yield = require_int(body, "reference_yield_bu_per_acre", minimum=1)
    ref_price = require_int(body, "reference_price_cents_per_bu", minimum=1)
    deadline = require_datetime(body, "bid_deadline")

    if field_id not in db.fields:
        raise ApiError("ERR_NOT_FOUND", 404, f"Field {field_id} not found")

    rec = new_common()
    rec.update({
        "field_id": field_id,
        "term_years": term_years,
        "term_start_date": term_start,
        "min_bid_per_acre_cents": min_bid,
        "reference_yield_bu_per_acre": ref_yield,
        "reference_price_cents_per_bu": ref_price,
        "bid_deadline": deadline,
        "status": "OPEN",
        "eligible_bid_count": 0,
    })
    db.offerings[rec["id"]] = rec
    return success_object(serialize("offering", rec), status=201)


@bp.route("/offerings/<offeringId>", methods=["GET"])
def get_offering(offeringId):
    _, role = get_caller()
    require_role(role, READ_ROLES)
    rec = db.offerings.get(offeringId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Offering {offeringId} not found")
    return success_object(serialize("offering", rec))


@bp.route("/offerings", methods=["GET"])
def list_offerings():
    _, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.offerings.values(), key=lambda r: r["created_at"])
    field_q = request.args.get("field_id")
    if field_q is not None:
        items = [r for r in items if r["field_id"] == field_q]
    status_q = request.args.get("status")
    if status_q is not None:
        items = [r for r in items if r["status"] == status_q]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize("offering", r) for r in page], limit, offset, total)


@bp.route("/offerings/<offeringId>/close", methods=["POST"])
def close_offering(offeringId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.offerings.get(offeringId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Offering {offeringId} not found")
    if rec["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Offering in state {rec['status']} cannot be closed")
    rec["status"] = "CLOSED"
    touch(rec)
    return success_object(serialize("offering", rec))


@bp.route("/offerings/<offeringId>/award", methods=["POST"])
def award_offering(offeringId):
    user_id, role = get_caller()
    require_role(role, {"Landlord"})
    body = get_json_body()
    bid_id = require_string(body, "bid_id")

    rec = db.offerings.get(offeringId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Offering {offeringId} not found")

    # Ownership: caller must own the offering's field
    field = db.fields.get(rec["field_id"])
    if field is None or field["landlord_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Caller does not own the offering's field")

    # bid_id must resolve and belong to this offering
    bid = db.bids.get(bid_id)
    if bid is None or bid["offering_id"] != offeringId:
        raise ApiError("ERR_NOT_FOUND", 404, f"Bid {bid_id} not found on this offering")

    # State: offering CLOSED, bid SHORTLISTED
    if rec["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Offering in state {rec['status']} cannot be awarded")
    if bid["status"] != "SHORTLISTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Bid in state {bid['status']} cannot be awarded")

    # Side effects
    bid["status"] = "ACCEPTED"
    bid["accepted_at"] = CLOCK.get()
    touch(bid)
    for other in db.bids.values():
        if (other["offering_id"] == offeringId and other["id"] != bid["id"]
                and other["status"] in ("SUBMITTED", "SHORTLISTED")):
            other["status"] = "REJECTED"
            touch(other)
    rec["status"] = "AWARDED"
    rec["eligible_bid_count"] = 0
    touch(rec)
    recompute_offering_scores(offeringId)
    return success_object(serialize("offering", rec))


@bp.route("/offerings/<offeringId>/cancel", methods=["POST"])
def cancel_offering(offeringId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.offerings.get(offeringId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Offering {offeringId} not found")
    if rec["status"] not in ("OPEN", "CLOSED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Offering in state {rec['status']} cannot be cancelled")
    for bid in db.bids.values():
        if bid["offering_id"] == offeringId and bid["status"] in ("SUBMITTED", "SHORTLISTED"):
            bid["status"] = "REJECTED"
            touch(bid)
    rec["status"] = "CANCELLED"
    rec["eligible_bid_count"] = 0
    touch(rec)
    recompute_offering_scores(offeringId)
    return success_object(serialize("offering", rec))
