"""Renewal endpoints (PRD §3.9)."""
from flask import Blueprint, request

import calculations as calc
import db
from common import (
    find_or_404,
    get_body,
    new_record,
    pagination,
    paginate,
    require_int,
    require_str,
    serialize,
    touch,
)
from errors import ApiError
from middleware import auth_context, require_role
from response import array_response, object_response
from services import ledger

bp = Blueprint("renewals", __name__)


@bp.post("/renewals")
def create_renewal():
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    body = get_body()
    policy_id = require_str(body, "policy_id")
    expected_version = require_int(body, "expected_policy_version")

    pol = find_or_404(db.policies, policy_id)

    # OCC before business logic (PRD §2.9, §3.12).
    if expected_version != pol["version"]:
        raise ApiError("ERR_STALE_VERSION")

    plan = db.rate_plans[pol["rate_plan_id"]]
    recalculated_score = pol["current_risk_score"]
    renewal_multiplier = calc.risk_multiplier(recalculated_score)
    recalculated_premium = calc.renewal_premium_cents(
        plan["base_premium_cents"], renewal_multiplier
    )
    bank = ledger.bank_for_driver(pol["driver_id"])
    banked_discount = calc.renewal_banked_discount(bank["available_cents"])

    rec = new_record(
        {
            "policy_id": pol["id"],
            "prior_premium_cents": pol["bound_premium_cents"],
            "recalculated_risk_score": recalculated_score,
            "recalculated_premium_cents": recalculated_premium,
            "banked_discount_applied_cents": banked_discount,
            "status": "PROPOSED",
        }
    )
    db.renewals[rec["id"]] = rec

    # Opening increments the policy version (PRD §3.9).
    touch(pol)

    return object_response(serialize(rec), 201)


@bp.get("/renewals")
def list_renewals():
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    limit, offset = pagination()
    items = list(db.renewals.values())
    for key in ("policy_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r[key] == val]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)


@bp.get("/renewals/<rid>")
def get_renewal(rid):
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    rec = find_or_404(db.renewals, rid)
    return object_response(serialize(rec), 200)


@bp.post("/renewals/<rid>/accept")
def accept_renewal(rid):
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    renewal = find_or_404(db.renewals, rid)
    body = get_body()
    expected_version = require_int(body, "expected_policy_version")
    pol = db.policies[renewal["policy_id"]]

    # OCC before business logic (PRD §2.9, §3.12).
    if expected_version != pol["version"]:
        raise ApiError("ERR_STALE_VERSION")

    if renewal["status"] != "PROPOSED":
        raise ApiError("ERR_RENEWAL_NOT_PROPOSED")
    if pol["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")

    bank = ledger.bank_for_driver(pol["driver_id"])
    swept = renewal["banked_discount_applied_cents"]
    # The sweep may not exceed the bank's available_cents (PRD §3.9).
    if swept > bank["available_cents"]:
        raise ApiError("ERR_DISCOUNT_OVERDRAW")

    pol["bound_premium_cents"] = (
        renewal["recalculated_premium_cents"] - swept
    )
    touch(pol)

    if swept > 0:
        ledger.redeem(bank, swept, "RENEWAL_REDEEM")

    renewal["status"] = "ACCEPTED"
    touch(renewal)

    return object_response(serialize(renewal), 200)


@bp.post("/renewals/<rid>/decline")
def decline_renewal(rid):
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    renewal = find_or_404(db.renewals, rid)
    if renewal["status"] != "PROPOSED":
        raise ApiError("ERR_RENEWAL_NOT_PROPOSED")
    renewal["status"] = "DECLINED"
    touch(renewal)
    return object_response(serialize(renewal), 200)
