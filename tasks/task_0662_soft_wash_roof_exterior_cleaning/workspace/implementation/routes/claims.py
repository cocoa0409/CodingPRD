from flask import Blueprint, request

from db import db, common_create_fields, touch
from errors import ApiError
from middleware import get_identity, require_role
from response import success, list_response
from services import serialize
from services.common import (
    get_body, require_fields, as_str,
    get_visit, get_claim,
    get_pagination, paginate, sorted_by_creation,
)

bp = Blueprint("claims", __name__)


def _owning_customer_id(visit):
    prop = db.properties.get(visit["property_id"])
    if prop is None:
        return None
    return prop["customer_id"]


@bp.post("/satisfaction-claims")
def create_claim():
    user_id, role = get_identity()
    require_role(role, {"Customer"})
    body = get_body()
    require_fields(body, ["visit_id", "reason"])
    visit = get_visit(body["visit_id"])
    reason = as_str(body["reason"], "reason")
    # Ownership: customer must own the visit's property.
    owner = _owning_customer_id(visit)
    if owner != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer")
    # Claim filed against a COMPLETED visit (§3.10).
    if visit["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "Claim can only be filed against a COMPLETED visit")
    c = common_create_fields()
    c.update({
        "visit_id": visit["id"],
        "reason": reason,
        "reclean_visit_id": None,
        "status": "OPEN",
    })
    db.satisfaction_claims[c["id"]] = c
    return success(serialize.claim_view(c), 201)


@bp.get("/satisfaction-claims")
def list_claims():
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "Customer"})
    visit_id = request.args.get("visit_id")
    reclean_visit_id = request.args.get("reclean_visit_id")
    status = request.args.get("status")
    limit, offset = get_pagination()
    items = []
    for c in db.satisfaction_claims.values():
        if visit_id is not None and c["visit_id"] != visit_id:
            continue
        if reclean_visit_id is not None and c["reclean_visit_id"] != reclean_visit_id:
            continue
        if status is not None and c["status"] != status:
            continue
        if role == "Customer":
            visit = db.visits.get(c["visit_id"])
            if visit is None or _owning_customer_id(visit) != user_id:
                continue
        items.append(c)
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize.claim_view(c) for c in page], limit, offset, total)


@bp.get("/satisfaction-claims/<cid>")
def get_one_claim(cid):
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "Customer"})
    c = get_claim(cid)
    if role == "Customer":
        visit = db.visits.get(c["visit_id"])
        if visit is None or _owning_customer_id(visit) != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer")
    return success(serialize.claim_view(c), 200)


@bp.post("/satisfaction-claims/<cid>/approve")
def approve_claim(cid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    c = get_claim(cid)
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN claim can be approved")
    source_visit = db.visits.get(c["visit_id"])
    if source_visit is None or source_visit["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "Linked visit is not COMPLETED")

    # Hop 1: spawn a free re-clean Visit (same property/scope), REQUESTED.
    reclean = common_create_fields()
    reclean.update({
        "property_id": source_visit["property_id"],
        "quote_id": source_visit["quote_id"],
        "plan_id": source_visit["plan_id"],
        "route_id": source_visit["route_id"],
        "scheduled_date": source_visit["scheduled_date"],
        "duration_minutes": source_visit["duration_minutes"],
        "provisional_cost_cents": None,
        "final_cost_cents": None,
        "reclean_of_visit_id": source_visit["id"],
        "billing_status": "UNBILLED",
        "status": "REQUESTED",
    })
    db.visits[reclean["id"]] = reclean

    c["status"] = "APPROVED"
    c["reclean_visit_id"] = reclean["id"]
    touch(c)

    # Hop 2: source visit COMPLETED -> RECLEAN_REQUESTED.
    source_visit["status"] = "RECLEAN_REQUESTED"
    touch(source_visit)

    return success(serialize.claim_view(c), 200)


@bp.post("/satisfaction-claims/<cid>/reject")
def reject_claim(cid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    c = get_claim(cid)
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN claim can be rejected")
    c["status"] = "REJECTED"
    touch(c)
    return success(serialize.claim_view(c), 200)
