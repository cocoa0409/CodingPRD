from flask import Blueprint, request

import errors
from errors import err
from db import db
from models import make_common, touch, serialize
from clock import parse_iso8601
from middleware import get_identity, require_role
from helpers import (get_json_body, lookup, parse_pagination, paginate,
                     sort_by_created, require_tenant_owns_lease)
from response import success, list_response
from services import calc

bp = Blueprint("insurance", __name__)

TIERS = {"BASIC", "STANDARD", "PREMIUM"}


def _coverage_overlap(lease_id, start, end, exclude_id=None):
    """Half-open [start, end) intervals must be disjoint; adjacency allowed."""
    for p in db.insurance_policies.values():
        if p["lease_id"] != lease_id:
            continue
        if exclude_id is not None and p["id"] == exclude_id:
            continue
        p_start = p["coverage_start"]
        p_end = p["coverage_end"]  # None => +inf
        # half-open overlap: start < p_end and p_start < end
        cond1 = (p_end is None) or (start < p_end)
        cond2 = (end is None) or (p_start < end)
        if cond1 and cond2:
            return True
    return False


@bp.post("/insurance-policies")
def create_policy():
    user_id, role = get_identity()
    require_role(role, {"FacilityManager", "Tenant"})
    body = get_json_body()

    lease_id = body.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id:
        raise err(errors.ERR_INVALID_REQUEST, "lease_id is required")
    lease = lookup(db.leases, lease_id, "lease")
    require_tenant_owns_lease(user_id, role, lease)

    coverage_tier = body.get("coverage_tier")
    coverage_start_raw = body.get("coverage_start")
    if coverage_tier not in TIERS:
        raise err(errors.ERR_INVALID_REQUEST, "coverage_tier must be BASIC, STANDARD, or PREMIUM")
    coverage_start = parse_iso8601(coverage_start_raw) if coverage_start_raw is not None else None
    if coverage_start is None:
        raise err(errors.ERR_INVALID_REQUEST, "coverage_start is required and must be ISO 8601")

    if _coverage_overlap(lease_id, coverage_start, None):
        raise err(errors.ERR_COVERAGE_OVERLAP, "Coverage interval overlaps an existing policy")

    policy = make_common()
    policy.update({
        "lease_id": lease_id,
        "coverage_tier": coverage_tier,
        "coverage_limit_cents": calc.TIER_LIMIT[coverage_tier],
        "monthly_premium_cents": calc.TIER_PREMIUM[coverage_tier],
        "coverage_start": coverage_start,
        "coverage_end": None,
        "status": "ACTIVE",
    })
    db.insurance_policies[policy["id"]] = policy
    return success(serialize(policy), 201)


@bp.get("/insurance-policies/<policy_id>")
def get_policy(policy_id):
    user_id, role = get_identity()
    policy = lookup(db.insurance_policies, policy_id, "insurance policy")
    lease = db.leases.get(policy["lease_id"])
    if lease is not None:
        require_tenant_owns_lease(user_id, role, lease)
    return success(serialize(policy), 200)


@bp.get("/insurance-policies")
def list_policies():
    user_id, role = get_identity()
    limit, offset = parse_pagination()
    items = list(db.insurance_policies.values())
    lease_id = request.args.get("lease_id")
    status = request.args.get("status")
    if lease_id is not None:
        items = [p for p in items if p["lease_id"] == lease_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if role == "Tenant":
        owned = {l["id"] for l in db.leases.values() if l["tenant_id"] == user_id}
        items = [p for p in items if p["lease_id"] in owned]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize(p) for p in page], total, limit, offset)


@bp.delete("/insurance-policies/<policy_id>")
def cancel_policy(policy_id):
    user_id, role = get_identity()
    require_role(role, {"FacilityManager", "Tenant"})
    policy = lookup(db.insurance_policies, policy_id, "insurance policy")
    lease = db.leases.get(policy["lease_id"])
    if lease is not None:
        require_tenant_owns_lease(user_id, role, lease)

    if policy["status"] not in ("ACTIVE", "LAPSED"):
        raise err(errors.ERR_INVALID_STATE, "Policy must be ACTIVE or LAPSED to cancel")

    policy["status"] = "CANCELLED"
    policy["coverage_end"] = db.clock.now()
    touch(policy)
    return success(serialize(policy), 200)
