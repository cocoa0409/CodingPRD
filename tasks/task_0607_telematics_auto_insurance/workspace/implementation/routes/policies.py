"""Policy endpoints: bind, lifecycle, advance-period, risk snapshots
(PRD §3.4, §3.6, §3.7, §3.11)."""
from flask import Blueprint, request

import clock
import db
from common import (
    find_or_404,
    new_record,
    pagination,
    paginate,
    require_str,
    serialize,
    touch,
)
from common import get_body
from errors import ApiError
from middleware import auth_context, require_role
from response import array_response, object_response
from services import ledger

bp = Blueprint("policies", __name__)

ALL_ROLES = ["DriverUser", "UnderwritingOps", "ClaimsAdjuster"]


@bp.post("/policies")
def bind_policy():
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    body = get_body()
    quote_id = require_str(body, "quote_id")
    quote = find_or_404(db.quotes, quote_id)

    # Precedence per PRD §3.12: state-transition preconditions first
    # (ERR_QUOTE_NOT_OPEN), then the referential rule (ERR_RATE_PLAN_RETIRED),
    # then the temporal rule (ERR_QUOTE_EXPIRED). §3.12 fixes the global order as
    # "referential, safety, temporal, ...", so the retired-plan (referential)
    # check is reported before the expired-quote (temporal) check when both hold.
    if quote["status"] != "OPEN":
        raise ApiError("ERR_QUOTE_NOT_OPEN")
    plan = db.rate_plans[quote["rate_plan_id"]]
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_RATE_PLAN_RETIRED")
    if clock.now() > clock.parse_iso(quote["expires_at"]):
        raise ApiError("ERR_QUOTE_EXPIRED")

    pol = new_record(
        {
            "driver_id": quote["driver_id"],
            "quote_id": quote["id"],
            "rate_plan_id": quote["rate_plan_id"],
            "bound_premium_cents": quote["quoted_annual_premium_cents"],
            "current_risk_score": quote["locked_risk_score"],
            "current_risk_multiplier": quote["risk_multiplier"],
            "period_index": 0,
            "billing_status": "PERIOD_OPEN",
            "telematics_status": "CAPTURING",
            "lifecycle_status": "ACTIVE",
        }
    )
    db.policies[pol["id"]] = pol

    quote["status"] = "BOUND"
    touch(quote)

    # First risk-score snapshot at bind with trigger reason MANUAL (PRD §3.4).
    ledger.append_snapshot(pol, "MANUAL")

    return object_response(serialize(pol), 201)


@bp.get("/policies")
def list_policies():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    limit, offset = pagination()
    items = list(db.policies.values())
    for key in ("driver_id", "quote_id", "rate_plan_id", "lifecycle_status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p[key] == val]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)


@bp.get("/policies/<rid>")
def get_policy(rid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    rec = find_or_404(db.policies, rid)
    return object_response(serialize(rec), 200)


@bp.post("/policies/<rid>/lapse")
def lapse_policy(rid):
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    pol = find_or_404(db.policies, rid)
    if pol["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")
    # Blocked by an ISSUED statement awaiting settlement (PRD §3.7).
    for s in db.statements.values():
        if s["policy_id"] == pol["id"] and s["status"] == "ISSUED":
            raise ApiError("ERR_UNSETTLED_STATEMENT")
    pol["lifecycle_status"] = "LAPSED"
    pol["telematics_status"] = "SUSPENDED"
    touch(pol)
    return object_response(serialize(pol), 200)


@bp.post("/policies/<rid>/cancel")
def cancel_policy(rid):
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    pol = find_or_404(db.policies, rid)
    if pol["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")
    # Blocked while any claim is FNOL/UNDER_REVIEW/REOPENED (PRD §3.7).
    for c in db.claims.values():
        if c["policy_id"] == pol["id"] and c["status"] in (
            "FNOL",
            "UNDER_REVIEW",
            "REOPENED",
        ):
            raise ApiError("ERR_OPEN_CLAIM_BLOCKS_CANCEL")
    pol["lifecycle_status"] = "CANCELLED"
    pol["telematics_status"] = "SUSPENDED"
    touch(pol)
    return object_response(serialize(pol), 200)


@bp.post("/policies/<rid>/advance-period")
def advance_period(rid):
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    pol = find_or_404(db.policies, rid)
    if pol["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")
    if pol["billing_status"] != "PERIOD_SETTLED":
        raise ApiError("ERR_PERIOD_NOT_SETTLED")
    pol["period_index"] += 1
    pol["billing_status"] = "PERIOD_OPEN"
    touch(pol)
    return object_response(serialize(pol), 200)


@bp.get("/policies/<rid>/risk-snapshots")
def list_snapshots(rid):
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    pol = find_or_404(db.policies, rid)
    limit, offset = pagination()
    items = [s for s in db.risk_snapshots.values() if s["policy_id"] == pol["id"]]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)
