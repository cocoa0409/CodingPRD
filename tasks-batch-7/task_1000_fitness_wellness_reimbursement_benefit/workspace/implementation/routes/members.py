"""Member and dependent endpoints."""
from flask import Blueprint, request, g

from db import STORE
from errors import (err, ERR_MEMBER_NOT_FOUND, ERR_PLAN_NOT_FOUND, ERR_EMPLOYER_NOT_FOUND,
                    ERR_DEPENDENT_NOT_FOUND, ERR_PLAN_NOT_ACTIVE, ERR_MEMBER_NOT_ELIGIBLE,
                    ERR_MEMBER_TERMINATED, ERR_TIER_NOT_DEFINED,
                    ERR_DEPENDENT_AGE_INELIGIBLE, ERR_DEPENDENT_INACTIVE)
from middleware import require_roles, is_member, member_owns
from response import success, paginate
from services.core import (new_entity, touch, serialize, sort_created,
                           tier_for, recompute_member_allowances,
                           terminate_member_cascade, ELIGIBILITY_WAIT_DAYS)
from util import body_json, req, as_str, check_enum, parse_dt, add_years, fmt_ts
from datetime import timedelta

bp = Blueprint("members", __name__)

TIER_CODES = ("INDIVIDUAL", "COUPLE", "FAMILY")
RELATIONSHIPS = ("SPOUSE", "CHILD", "DOMESTIC_PARTNER")


def get_member(mid):
    m = STORE.members.get(mid)
    if m is None:
        raise err(ERR_MEMBER_NOT_FOUND, 404, "member id does not resolve")
    return m


@bp.post("/api/members")
def create_member():
    require_roles("BenefitsAdmin")
    body = body_json()
    employer_id = as_str(req(body, "employer_id"), "employer_id")
    plan_id = as_str(req(body, "plan_id"), "plan_id")
    external_ref = as_str(req(body, "external_ref"), "external_ref")
    full_name = as_str(req(body, "full_name"), "full_name")
    tier_code = check_enum(req(body, "tier_code"), TIER_CODES, "tier_code")
    hire_date_raw = req(body, "hire_date")
    # existence: body FKs
    if employer_id not in STORE.employers:
        raise err(ERR_EMPLOYER_NOT_FOUND, 404, "employer id does not resolve")
    plan = STORE.plans.get(plan_id)
    if plan is None:
        raise err(ERR_PLAN_NOT_FOUND, 404, "plan id does not resolve")
    hire = parse_dt(hire_date_raw)
    # state: registration only possible against an ACTIVE plan
    if plan["status"] != "ACTIVE":
        raise err(ERR_PLAN_NOT_ACTIVE, 409, "member registration requires plan ACTIVE")
    # business: tier must be defined among the plan's tiers
    if tier_for(plan_id, tier_code) is None:
        raise err(ERR_TIER_NOT_DEFINED, 422, "member tier_code absent from the plan's tiers")
    eligibility = hire + timedelta(days=ELIGIBILITY_WAIT_DAYS)
    m = new_entity()
    status = "ELIGIBLE" if STORE.clock >= eligibility else "PENDING"
    m.update({
        "employer_id": employer_id,
        "plan_id": plan_id,
        "external_ref": external_ref,
        "full_name": full_name,
        "tier_code": tier_code,
        "hire_date": hire_date_raw,
        "eligibility_date": fmt_ts(eligibility),
        "eligibility_status": status,
        "_hire_dt": hire,
        "_eligibility_dt": eligibility,
    })
    STORE.members[m["id"]] = m
    return success(serialize(m), 201)


@bp.get("/api/members/<mid>")
def read_member(mid):
    require_roles("BenefitsAdmin", "Auditor", "Member")
    if is_member() and g.user_id != mid:
        from errors import ERR_FORBIDDEN_OWNERSHIP
        raise err(ERR_FORBIDDEN_OWNERSHIP, 403, "member may read only their own record")
    return success(serialize(get_member(mid)))


@bp.get("/api/members")
def list_members():
    require_roles("BenefitsAdmin", "Auditor")
    items = sort_created(STORE.members.values())
    employer_id = request.args.get("employer_id")
    plan_id = request.args.get("plan_id")
    eligibility_status = request.args.get("eligibility_status")
    if employer_id is not None:
        items = [m for m in items if m["employer_id"] == employer_id]
    if plan_id is not None:
        items = [m for m in items if m["plan_id"] == plan_id]
    if eligibility_status is not None:
        items = [m for m in items if m["eligibility_status"] == eligibility_status]
    return paginate([serialize(m) for m in items])


def _member_state_transition(mid, target, allowed_from):
    m = get_member(mid)
    if m["eligibility_status"] == "TERMINATED":
        raise err(ERR_MEMBER_TERMINATED, 409, "member TERMINATED; all member operations blocked")
    if m["eligibility_status"] not in allowed_from:
        raise err(ERR_MEMBER_NOT_ELIGIBLE, 409,
                  f"member not in required state for {target}")
    m["eligibility_status"] = target
    touch(m)
    return m


@bp.post("/api/members/<mid>/suspend")
def suspend_member(mid):
    require_roles("BenefitsAdmin")
    return success(serialize(_member_state_transition(mid, "SUSPENDED", ("ELIGIBLE",))))


@bp.post("/api/members/<mid>/reinstate")
def reinstate_member(mid):
    require_roles("BenefitsAdmin")
    return success(serialize(_member_state_transition(mid, "ELIGIBLE", ("SUSPENDED",))))


@bp.post("/api/members/<mid>/terminate")
def terminate_member(mid):
    require_roles("BenefitsAdmin")
    m = get_member(mid)
    if m["eligibility_status"] == "TERMINATED":
        raise err(ERR_MEMBER_TERMINATED, 409, "member already TERMINATED")
    if m["eligibility_status"] not in ("ELIGIBLE", "SUSPENDED"):
        raise err(ERR_MEMBER_NOT_ELIGIBLE, 409, "terminate requires ELIGIBLE or SUSPENDED")
    terminate_member_cascade(m)
    m["eligibility_status"] = "TERMINATED"
    touch(m)
    return success(serialize(m))


# ---------------------------------------------------------------------------
# Dependents
# ---------------------------------------------------------------------------

@bp.post("/api/members/<mid>/dependents")
def add_dependent(mid):
    require_roles("BenefitsAdmin", "Member")
    member_owns(mid)
    m = get_member(mid)
    body = body_json()
    full_name = as_str(req(body, "full_name"), "full_name")
    relationship = check_enum(req(body, "relationship"), RELATIONSHIPS, "relationship")
    birth_raw = req(body, "birth_date")
    birth = parse_dt(birth_raw)
    # state: member TERMINATED blocks all member-scoped operations
    if m["eligibility_status"] == "TERMINATED":
        raise err(ERR_MEMBER_TERMINATED, 409, "member TERMINATED; all member operations blocked")
    # business: CHILD must be younger than 26 at the plan's period_start
    if relationship == "CHILD":
        plan = STORE.plans.get(m["plan_id"])
        if plan is not None and plan["_ps"] >= add_years(birth, 26):
            raise err(ERR_DEPENDENT_AGE_INELIGIBLE, 422,
                      "CHILD dependent aged >= 26 at plan period_start")
    d = new_entity()
    d.update({
        "member_id": mid,
        "full_name": full_name,
        "relationship": relationship,
        "birth_date": birth_raw,
        "status": "ACTIVE",
        "_birth_dt": birth,
    })
    STORE.dependents[d["id"]] = d
    recompute_member_allowances(mid)
    return success(serialize(d), 201)


@bp.get("/api/members/<mid>/dependents")
def list_dependents(mid):
    require_roles("BenefitsAdmin", "Auditor", "Member")
    member_owns(mid)
    get_member(mid)
    items = [d for d in sort_created(STORE.dependents.values()) if d["member_id"] == mid]
    return paginate([serialize(d) for d in items])


@bp.post("/api/dependents/<did>/deactivate")
def deactivate_dependent(did):
    require_roles("BenefitsAdmin", "Member")
    d = STORE.dependents.get(did)
    if d is None:
        raise err(ERR_DEPENDENT_NOT_FOUND, 404, "dependent id does not resolve")
    member_owns(d["member_id"])
    if d["status"] != "ACTIVE":
        raise err(ERR_DEPENDENT_INACTIVE, 409, "dependent already INACTIVE")
    d["status"] = "INACTIVE"
    touch(d)
    recompute_member_allowances(d["member_id"])
    return success(serialize(d))
