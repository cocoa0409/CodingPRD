"""Enrollment endpoints."""
from flask import Blueprint, request, g

from db import STORE
from errors import (err, ERR_ENROLLMENT_NOT_FOUND, ERR_MEMBER_NOT_FOUND,
                    ERR_PLAN_NOT_FOUND, ERR_MEMBER_NOT_ELIGIBLE,
                    ERR_MEMBER_TERMINATED, ERR_PLAN_NOT_ACTIVE,
                    ERR_TIER_NOT_DEFINED, ERR_ENROLLMENT_PERIOD_OVERLAP,
                    ERR_OPEN_CLAIMS_EXIST, ERR_INVALID_REQUEST)
from middleware import require_roles, is_member, member_owns
from response import success, paginate
from services.core import (new_entity, touch, serialize, sort_created,
                           tier_for, effective_allowance, claims_of_enrollment,
                           OPEN_REVIEW)
from util import body_json, req, as_str, quarter_key_of

bp = Blueprint("enrollments", __name__)

READ_ROLES = ("BenefitsAdmin", "Auditor", "Member")


def get_enrollment(eid):
    e = STORE.enrollments.get(eid)
    if e is None:
        raise err(ERR_ENROLLMENT_NOT_FOUND, 404, "enrollment id does not resolve")
    return e


@bp.post("/api/enrollments")
def create_enrollment():
    require_roles("BenefitsAdmin", "Member")
    body = body_json()
    member_id = as_str(req(body, "member_id"), "member_id")
    plan_id = as_str(req(body, "plan_id"), "plan_id")
    # existence
    m = STORE.members.get(member_id)
    if m is None:
        raise err(ERR_MEMBER_NOT_FOUND, 404, "member id does not resolve")
    plan = STORE.plans.get(plan_id)
    if plan is None:
        raise err(ERR_PLAN_NOT_FOUND, 404, "plan id does not resolve")
    # ownership: Member caller creates only their own enrollment
    member_owns(member_id)
    # state
    if m["eligibility_status"] == "TERMINATED":
        raise err(ERR_MEMBER_TERMINATED, 409, "member TERMINATED")
    if m["eligibility_status"] != "ELIGIBLE":
        raise err(ERR_MEMBER_NOT_ELIGIBLE, 409, "enrollment requires member ELIGIBLE")
    if plan["status"] != "ACTIVE":
        raise err(ERR_PLAN_NOT_ACTIVE, 409, "enrollment requires plan ACTIVE")
    # business: member tier must be defined among plan tiers
    tier = tier_for(plan_id, m["tier_code"])
    if tier is None:
        raise err(ERR_TIER_NOT_DEFINED, 422, "member tier_code absent from the plan's tiers")
    # business: pairwise disjoint plan periods under CLOSED interval semantics
    for other in STORE.enrollments.values():
        if other["member_id"] != member_id:
            continue
        op = STORE.plans.get(other["plan_id"])
        if op is None:
            continue
        if plan["_ps"] <= op["_pe"] and op["_ps"] <= plan["_pe"]:
            raise err(ERR_ENROLLMENT_PERIOD_OVERLAP, 409,
                      "member already has an enrollment whose plan period intersects")
    e = new_entity()
    e.update({
        "member_id": member_id,
        "plan_id": plan_id,
        "tier_code": m["tier_code"],
        "annual_allowance_cents": effective_allowance(tier, member_id),
        "quarterly_cap_cents": tier["quarterly_cap_cents"],
        "used_cents": 0,
        "reserved_cents": 0,
        "quarter_key": quarter_key_of(STORE.clock),
        "quarter_used_cents": 0,
        "status": "ACTIVE",
        "_tier_snapshot": {k: tier[k] for k in
                           ("tier_code", "annual_allowance_cents", "quarterly_cap_cents",
                            "per_claim_cap_cents", "visit_frequency_cap",
                            "dependent_cap_pct", "in_network_pct", "preferred_pct",
                            "out_of_network_pct")},
    })
    STORE.enrollments[e["id"]] = e
    return success(serialize(e), 201)


@bp.get("/api/enrollments/<eid>")
def read_enrollment(eid):
    require_roles(*READ_ROLES)
    e = get_enrollment(eid)
    member_owns(e["member_id"])
    return success(serialize(e))


@bp.get("/api/enrollments")
def list_enrollments():
    require_roles(*READ_ROLES)
    items = sort_created(STORE.enrollments.values())
    member_id = request.args.get("member_id")
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    if is_member():
        if member_id is not None and member_id != g.user_id:
            member_owns(member_id)
        items = [e for e in items if e["member_id"] == g.user_id]
    elif member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    if plan_id is not None:
        items = [e for e in items if e["plan_id"] == plan_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paginate([serialize(e) for e in items])


@bp.post("/api/enrollments/<eid>/close")
def close_enrollment(eid):
    require_roles("BenefitsAdmin")
    e = get_enrollment(eid)
    if e["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise err(ERR_ENROLLMENT_NOT_ACTIVE, 409, "close requires ACTIVE or EXHAUSTED")
    for c in claims_of_enrollment(eid):
        if c["review_status"] in OPEN_REVIEW:
            raise err(ERR_OPEN_CLAIMS_EXIST, 409,
                      "manual enrollment close blocked by open claims")
    e["status"] = "CLOSED"
    touch(e)
    return success(serialize(e))


@bp.get("/api/enrollments/<eid>/allowance")
def read_allowance(eid):
    require_roles(*READ_ROLES)
    e = get_enrollment(eid)
    member_owns(e["member_id"])
    remaining = e["annual_allowance_cents"] - e["used_cents"] - e["reserved_cents"]
    data = {
        "enrollment_id": e["id"],
        "annual_allowance_cents": e["annual_allowance_cents"],
        "used_cents": e["used_cents"],
        "reserved_cents": e["reserved_cents"],
        "remaining_cents": remaining,
        "quarter_key": e["quarter_key"],
        "quarter_used_cents": e["quarter_used_cents"],
        "quarterly_remaining_cents": e["quarterly_cap_cents"] - e["quarter_used_cents"],
    }
    return success(data)
