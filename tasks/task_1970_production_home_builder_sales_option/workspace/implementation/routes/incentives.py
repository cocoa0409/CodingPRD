"""IncentiveRequest endpoints: create / list / get / decide (PRD section 3.7)."""

import db
from constants import (
    READ_ROLES,
    ROLE_BUYER,
    INCENTIVE_TYPES,
    INCENTIVE_DECIDE_ACTIONS,
    AUTO_APPROVE_LIMIT_CENTS,
)
from errors import (
    ApiError,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_INCENTIVE_NOT_FOUND,
    ERR_AGREEMENT_INVALID_STATE,
    ERR_INCENTIVE_INVALID_STATE,
    ERR_INCENTIVE_BUDGET_EXCEEDED,
    ERR_INCENTIVE_CAP_EXCEEDED,
)
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from services import (
    ser_incentive,
    community_budget_remaining_cents,
    incentives_total_cents,
    incentive_cap_cents,
)
from util import (
    body_json,
    check_shape,
    require_fk,
    pagination_params,
    paginate,
    apply_filters,
)

bp = make_blueprint("incentives")

CREATE_SPEC = {
    "agreement_id": {"type": "string", "required": True},
    "incentive_type": {"type": "enum", "required": True, "values": INCENTIVE_TYPES},
    "amount_cents": {"type": "integer", "required": True, "min": 1},
}

DECIDE_SPEC = {
    "action": {"type": "enum", "required": True, "values": INCENTIVE_DECIDE_ACTIONS},
}


@bp.post("/incentive-requests")
def create_incentive():
    authenticate(["SalesAgent"])
    body = body_json()
    check_shape(body, CREATE_SPEC)
    agreement = require_fk("agreements", body["agreement_id"], ERR_AGREEMENT_NOT_FOUND, "agreement")
    # State tier (priority 7) beats the fiscal checks (priority 11).
    if agreement["status"] not in ("PENDING_CONTINGENCIES", "CONTINGENCIES_CLEARED"):
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, 409, "agreement is not in an incentable state")
    community = db.get("communities", agreement["community_id"])
    remaining = community_budget_remaining_cents(community)
    # Intake guard: the request cannot exceed the money available.
    if body["amount_cents"] > remaining:
        raise ApiError(ERR_INCENTIVE_BUDGET_EXCEEDED, 402, "amount exceeds the community's remaining incentive budget")
    # Auto-approval: at or below the limit (equality qualifies) with budget and
    # cap available; otherwise the request lands in SUBMITTED.
    amount = body["amount_cents"]
    cap = incentive_cap_cents(agreement)
    auto = (
        amount <= AUTO_APPROVE_LIMIT_CENTS
        and remaining - amount >= 0
        and incentives_total_cents(agreement["id"]) + amount <= cap
    )
    request_ent = db.new_entity("incentive_requests", {
        "agreement_id": agreement["id"],
        "incentive_type": body["incentive_type"],
        "amount_cents": amount,
        "status": "APPROVED" if auto else "SUBMITTED",
        "auto_approved": auto,
        "decided_at": db.fmt_ts(db.now()) if auto else None,
    })
    if auto:
        # Budget debit and incentives_total accrual are derived from the
        # APPROVED status; the agreement mutation still bumps its version.
        db.touch(agreement)
    return success_obj(ser_incentive(request_ent), 201)


@bp.get("/incentive-requests")
def list_incentives():
    user_id, role = authenticate(READ_ROLES)
    limit, offset = pagination_params()
    items = db.all_of("incentive_requests")
    if role == ROLE_BUYER:
        items = [
            r for r in items
            if (db.get("agreements", r["agreement_id"]) or {}).get("buyer_id") == user_id
        ]
    items = apply_filters(items, ["agreement_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([ser_incentive(r) for r in page], limit, offset, total, has_more)


@bp.get("/incentive-requests/<iid>")
def get_incentive(iid):
    authenticate(READ_ROLES)
    request_ent = require_fk("incentive_requests", iid, ERR_INCENTIVE_NOT_FOUND, "incentive request")
    return success_obj(ser_incentive(request_ent), 200)


@bp.post("/incentive-requests/<iid>/decide")
def decide_incentive(iid):
    authenticate(["SalesDirector"])
    body = body_json()
    check_shape(body, DECIDE_SPEC)
    request_ent = require_fk("incentive_requests", iid, ERR_INCENTIVE_NOT_FOUND, "incentive request")
    if request_ent["status"] != "SUBMITTED":
        raise ApiError(ERR_INCENTIVE_INVALID_STATE, 409, "only a SUBMITTED request can be decided")
    agreement = db.get("agreements", request_ent["agreement_id"])
    if body["action"] == "APPROVE":
        # Approval re-runs both money guards in order: budget, then cap.
        community = db.get("communities", agreement["community_id"])
        if community_budget_remaining_cents(community) - request_ent["amount_cents"] < 0:
            raise ApiError(ERR_INCENTIVE_BUDGET_EXCEEDED, 402, "amount exceeds the community's remaining incentive budget")
        if incentives_total_cents(agreement["id"]) + request_ent["amount_cents"] > incentive_cap_cents(agreement):
            raise ApiError(ERR_INCENTIVE_CAP_EXCEEDED, 402, "cumulative approved incentives exceed the agreement cap")
        request_ent["status"] = "APPROVED"
        request_ent["decided_at"] = db.fmt_ts(db.now())
        db.touch(request_ent)
        db.touch(agreement)
    else:
        # Denial stamps decided_at with no ledger movement.
        request_ent["status"] = "DENIED"
        request_ent["decided_at"] = db.fmt_ts(db.now())
        db.touch(request_ent)
    return success_obj(ser_incentive(request_ent), 200)
