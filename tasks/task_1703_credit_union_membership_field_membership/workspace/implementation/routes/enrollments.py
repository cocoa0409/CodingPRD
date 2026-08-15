"""Product enrollment endpoints."""
from flask import Blueprint, request

import db
from auth import require_roles, STAFF_ROLES
from errors import ApiError
from response import ok_object, paginate, now_iso
from serializers import serialize_enrollment
from services import calc
from services.sweep import new_id
from validators import get_body, req_str, req_enum

bp = Blueprint("enrollments", __name__)

PRODUCT_REQUIRED_TIER = {
    "MONEY_MARKET": "SELECT",
    "SHARE_CERTIFICATE": "SELECT",
    "PREMIER_LOAN": "PREMIER",
}


@bp.post("/credit-union/product-enrollments")
def create_enrollment():
    require_roles({"MembershipOfficer"})
    body = get_body()
    # Tier 4: syntactic
    member_id = req_str(body, "member_id")
    product_code = req_enum(body, "product_code", set(PRODUCT_REQUIRED_TIER))
    funding_share_account_id = req_str(body, "funding_share_account_id")
    # Tier 5: existence
    member = db.members.get(member_id)
    if member is None:
        raise ApiError("ERR_NOT_FOUND", f"member {member_id} not found")
    # Tier 7: member posture
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", "member is not ACTIVE")
    # Tier 9: funding account exists for this member and is OPEN
    account = db.accounts.get(funding_share_account_id)
    if (account is None or account["member_id"] != member_id
            or account["status"] != "OPEN"):
        raise ApiError("ERR_PRODUCT_FUNDING_ACCOUNT_INVALID",
                       "funding account does not exist for this member or is not OPEN")
    # Tier 10: one ACTIVE enrollment per (member, product_code)
    for e in db.enrollments.values():
        if (e["member_id"] == member_id and e["product_code"] == product_code
                and e["status"] == "ACTIVE"):
            raise ApiError("ERR_ALREADY_ENROLLED",
                           "member already has an ACTIVE enrollment for this product")
    # Tier 10: tier requirement on the current-point-in-time basis
    tier_now = calc.current_point_in_time_tier(member, db.clock.current_date())
    required_tier = PRODUCT_REQUIRED_TIER[product_code]
    if calc.TIER_RANK[tier_now] < calc.TIER_RANK[required_tier]:
        raise ApiError("ERR_TIER_REQUIREMENT_NOT_MET",
                       "member's enrollment-time tier is below the product's required tier")
    enrollment = {
        "id": new_id(),
        "member_id": member_id,
        "product_code": product_code,
        "funding_share_account_id": funding_share_account_id,
        "required_tier": required_tier,
        "tier_at_enrollment": tier_now,
        "status": "ACTIVE",
        "closure_reason": None,
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.enrollments[enrollment["id"]] = enrollment
    return ok_object(serialize_enrollment(enrollment), 201)


@bp.get("/credit-union/product-enrollments")
def list_enrollments():
    require_roles(STAFF_ROLES)
    items = list(db.enrollments.values())
    for f in ("member_id", "funding_share_account_id", "product_code", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e.get(f) == v]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return paginate([serialize_enrollment(e) for e in items])


@bp.get("/credit-union/product-enrollments/<eid>")
def get_enrollment(eid):
    require_roles(STAFF_ROLES)
    e = db.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", f"product enrollment {eid} not found")
    return ok_object(serialize_enrollment(e), 200)
