"""Logical clock and AssessmentTierPolicy endpoints."""
from flask import Blueprint, request

import db
import errors
import helpers
import sweeps
import util
from errors import ApiError
from middleware import body, paginate, require_roles
from response import ok, ok_list
from serializers import serialize

bp = Blueprint("admin", __name__, url_prefix="/vsa")

TIERS = ("TIER_1", "TIER_2", "TIER_3", "TIER_4")


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock():
    data = body()
    to_iso8601 = data.get("to_iso8601")
    if to_iso8601 is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "to_iso8601 is required")
    try:
        target = util.parse_dt(to_iso8601)
    except ValueError:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "to_iso8601 must be an ISO 8601 datetime")
    db.clock_dt = target
    sweeps.run_sweeps()
    return ok({"current_utc": util.iso(db.clock_dt)})


@bp.post("/tier-policies")
@require_roles("PlatformAdmin")
def create_policy():
    data = body()
    name = data.get("name")
    tier_matrix = data.get("tier_matrix")
    if not isinstance(name, str) or not name:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "name is required")
    if not isinstance(tier_matrix, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "tier_matrix is required")
    for key, value in tier_matrix.items():
        if not isinstance(key, str) or value not in TIERS:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "tier_matrix must map classification triples to TIER_1..TIER_4")
    active = data.get("active", True)
    if not isinstance(active, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "active must be a boolean")
    cadences = {}
    for n in (1, 2, 3, 4):
        field = "tier%d_reassessment_months" % n
        default = {1: 36, 2: 24, 3: 12, 4: 6}[n]
        value = data.get(field, default)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "%s must be a positive integer" % field)
        cadences[field] = value
    policy = {
        "name": name,
        "active": active,
        "tier_matrix": dict(tier_matrix),
        **cadences,
    }
    helpers.stamp_new("policies", policy)
    db.policies[policy["id"]] = policy
    # Exactly one active policy: a new active policy deactivates the incumbent.
    if active:
        for other in db.policies.values():
            if other["id"] != policy["id"] and other.get("active"):
                other["active"] = False
                helpers.touch("policies", other)
    return ok(serialize("policy", policy), 201)


@bp.get("/tier-policies")
@require_roles("PlatformAdmin", "RiskAnalyst", "SecurityApprover")
def list_policies():
    items = list(db.policies.values())
    raw_active = request.args.get("active")
    if raw_active is not None:
        wanted = raw_active.strip().lower()
        if wanted in ("true", "false"):
            flag = wanted == "true"
            items = [p for p in items if bool(p.get("active")) == flag]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("policy", p) for p in page], limit, offset, total)


@bp.get("/tier-policies/<pid>")
@require_roles("PlatformAdmin", "RiskAnalyst", "SecurityApprover")
def get_policy(pid):
    policy = helpers.get_policy(pid)
    return ok(serialize("policy", policy))
