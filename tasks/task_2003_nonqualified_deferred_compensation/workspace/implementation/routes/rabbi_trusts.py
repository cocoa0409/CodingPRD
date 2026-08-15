"""Rabbi trust endpoints."""
from flask import Blueprint, request

import db
from errors import (
    ERR_PLAN_NOT_ACTIVE,
    ERR_TRUST_EXISTS,
    ERR_NEGATIVE_TRUST_ASSETS,
    ERR_CIC_FUNDING_MISMATCH,
    ERR_NO_VERIFIED_CIC,
    raise_err,
)
from middleware import user_context, require_role
from response import ok_object
from routes.plans import _list_response
from services.core import body, req_int, req_enum, get_or_404, stamp_new, touch, recompute_trust
from util import CLOCK

bp = Blueprint("rabbi_trusts", __name__)

EVENT_TYPES = {"CONTRIBUTION", "VALUATION_ADJUSTMENT", "CIC_MANDATORY_FUNDING", "TRUST_DISTRIBUTION"}


def trust_view(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "plan_id": t["plan_id"],
        "funding_target_bp": t["funding_target_bp"],
        "assets_cents": t["assets_cents"],
        "cic_funding_required": t["cic_funding_required"],
        "required_funding_cents": t["required_funding_cents"],
        "posture": t["posture"],
        "funding_events": list(t["funding_events"]),
    }


@bp.post("/api/rabbi-trusts")
def create_trust():
    data = body()
    from errors import ERR_INVALID_REQUEST

    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise_err(ERR_INVALID_REQUEST, "plan_id is required and must be a string")
    target = req_int(data, "funding_target_bp", 0, 20000)

    user_id, role = user_context()
    require_role(role, {"PlanSponsor"})
    plan = get_or_404(db.plans, plan_id, "Plan")
    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to establish a rabbi trust")

    for t in db.rabbi_trusts.values():
        if t["plan_id"] == plan_id:
            raise_err(ERR_TRUST_EXISTS, "Plan already has a rabbi trust")

    trust = stamp_new(
        {
            "plan_id": plan_id,
            "funding_target_bp": target,
            "assets_cents": 0,
            "cic_funding_required": False,
            "required_funding_cents": 0,
            "posture": "UNFUNDED",
            "funding_events": [],
        }
    )
    db.rabbi_trusts[trust["id"]] = trust
    recompute_trust(trust)
    return ok_object(trust_view(trust), 201)


@bp.get("/api/rabbi-trusts")
def list_trusts():
    user_context()
    items = list(db.rabbi_trusts.values())
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        items = [t for t in items if t["plan_id"] == plan_id]
    for t in items:
        recompute_trust(t)
    return _list_response([trust_view(t) for t in items], request.args)


@bp.get("/api/rabbi-trusts/<trustId>")
def get_trust(trustId):
    user_context()
    t = get_or_404(db.rabbi_trusts, trustId, "RabbiTrust")
    recompute_trust(t)
    return ok_object(trust_view(t))


@bp.post("/api/rabbi-trusts/<trustId>/funding-events")
def post_funding_event(trustId):
    data = body()
    event_type = req_enum(data, "event_type", EVENT_TYPES)
    amount = req_int(data, "amount_cents")

    user_id, role = user_context()
    require_role(role, {"TrustOfficer"})
    trust = get_or_404(db.rabbi_trusts, trustId, "RabbiTrust")
    recompute_trust(trust)

    from errors import ERR_INVALID_REQUEST

    if event_type == "TRUST_DISTRIBUTION":
        raise_err(ERR_INVALID_REQUEST, "TRUST_DISTRIBUTION is system-posted only")
    if event_type == "CONTRIBUTION" and amount <= 0:
        raise_err(ERR_INVALID_REQUEST, "CONTRIBUTION amount must be positive")
    if event_type == "VALUATION_ADJUSTMENT" and amount == 0:
        raise_err(ERR_INVALID_REQUEST, "VALUATION_ADJUSTMENT amount must be non-zero")
    if event_type == "CIC_MANDATORY_FUNDING":
        if amount <= 0:
            raise_err(ERR_INVALID_REQUEST, "CIC_MANDATORY_FUNDING amount must be positive")
        has_verified = any(
            c["plan_id"] == trust["plan_id"] and c["status"] == "VERIFIED"
            for c in db.change_in_control_events.values()
        )
        if not has_verified:
            raise_err(ERR_NO_VERIFIED_CIC, "No VERIFIED change-in-control event exists for the plan")
        if amount != trust["required_funding_cents"]:
            raise_err(ERR_CIC_FUNDING_MISMATCH, "CIC_MANDATORY_FUNDING amount must equal required_funding_cents exactly")

    if trust["assets_cents"] + amount < 0:
        raise_err(ERR_NEGATIVE_TRUST_ASSETS, "Funding event would drive trust assets below zero")

    trust["funding_events"].append(
        {
            "event_type": event_type,
            "amount_cents": amount,
            "recorded_at": CLOCK.stamp(),
        }
    )
    recompute_trust(trust)
    touch(trust)
    return ok_object(trust_view(trust), 201)
