"""Refund claims: the waterfall, review, the decision fork and payment (PRD 3.7)."""

from flask import Blueprint

import db
import helpers
import middleware
import response
import shape
from errors import ApiError
from middleware import (AUDIT_MANAGER, LICENSEE_AGENT, RETURNS_EXAMINER,
                        TAX_SUPERVISOR)
from services import calc, cascade, derive

bp = Blueprint("refunds", __name__, url_prefix="/mft")

FILE_ROLES = (LICENSEE_AGENT, RETURNS_EXAMINER)
READ_ROLES = (RETURNS_EXAMINER, TAX_SUPERVISOR, AUDIT_MANAGER, LICENSEE_AGENT)

RECOMMENDATIONS = ["APPROVE", "PARTIAL", "DENY"]
DECISIONS = ["APPROVED", "PARTIALLY_APPROVED", "DENIED"]

TAX_PAID = "SCH_1_RECEIVED_TAX_PAID"


def _owner(row):
    return row["licensee_id"]


def _statutory_basis(claim_type, claimed_gallons, equipment_class):
    """Step one of PRD 3.7; the reefer cap clamps, it does not error."""
    if claim_type == "PTO":
        pct = calc.PTO_ALLOCATION_PCT[equipment_class]
        return calc.g2(claimed_gallons * pct)
    if claim_type == "REFRIGERATION_UNIT":
        if claimed_gallons > calc.REEFER_MONTHLY_CAP_GALLONS:
            return calc.REEFER_MONTHLY_CAP_GALLONS
        return calc.g2(claimed_gallons)
    return calc.g2(claimed_gallons)


def _consumed_gallons(licensee_id, period_month, exclude_id=None):
    """Gallons already reserved by the claimant's non-denied claims."""
    total = calc.ZERO
    for claim in db.ordered(db.refund_claims):
        if claim["licensee_id"] != licensee_id:
            continue
        if claim["period_month"] != period_month:
            continue
        if claim["id"] == exclude_id or claim["status"] == "DENIED":
            continue
        total += claim["allowable_gallons"]
    return calc.g2(total)


@bp.post("/refund-claims")
def file_claim():
    user_id, role = middleware.require(*FILE_ROLES)
    body = shape.body()
    candidate = body.get("licensee_id")
    if isinstance(candidate, str) and candidate:
        middleware.scope_guard(user_id, role, candidate)
    licensee_id = shape.req_id(body, "licensee_id")
    claim_type = shape.req_enum(body, "claim_type", calc.CLAIM_TYPES)
    period_month = shape.req_month(body, "period_month")
    claimed_gallons = shape.req_gallons(body, "claimed_gallons", gt=calc.ZERO)
    # equipment_class is required when and only when claim_type is PTO.
    equipment_class = body.get("equipment_class")
    if claim_type == "PTO":
        equipment_class = shape.req_str(body, "equipment_class")
    elif equipment_class is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "equipment_class is only accepted on a PTO claim.")

    licensee = helpers.body_licensee(licensee_id)
    if licensee["status"] == "REVOKED":
        raise ApiError("ERR_LICENSEE_REVOKED")

    # Band 10: an open audit freezes claims that have not yet been filed.
    if derive.open_audit_count(licensee_id) > 0:
        raise ApiError("ERR_REFUND_BLOCKED_BY_AUDIT")

    # Band 12: the period's filed return is the only source of the pool.
    basis_return = derive.filed_return_for_period(licensee_id, period_month)
    if basis_return is None:
        raise ApiError("ERR_REFUND_PERIOD_NOT_FILED")

    # Band 13: equipment-class legality.
    if claim_type == "PTO" and equipment_class not in calc.EQUIPMENT_CLASSES:
        raise ApiError("ERR_EQUIPMENT_CLASS_INVALID")
    if claim_type == "REFRIGERATION_UNIT":
        ceiling = calc.REEFER_MONTHLY_CAP_GALLONS * calc.REEFER_REJECT_FACTOR
        if claimed_gallons > ceiling:
            raise ApiError("ERR_EQUIPMENT_CLASS_INVALID")

    basis = _statutory_basis(claim_type, claimed_gallons, equipment_class)

    # Band 14: the waterfall against the period's tax-paid pool.
    pool = helpers.product_schedule_gallons(basis_return["id"], TAX_PAID,
                                           calc.REFUND_PRODUCT)
    remaining = calc.g2(pool - _consumed_gallons(licensee_id, period_month))
    if basis > remaining:
        raise ApiError("ERR_REFUND_EXCEEDS_TAX_PAID")

    row = db.base_row()
    row.update({
        "licensee_id": licensee_id,
        "claim_type": claim_type,
        "period_month": period_month,
        "claimed_gallons": claimed_gallons,
        "equipment_class": equipment_class,
        "allowable_gallons": basis,
        "refund_amount_cents": calc.rate_cents(basis, calc.REFUND_PRODUCT),
        "status": "SUBMITTED",
        "status_before_hold": None,
        "hold_reason": None,
        "recommendation": None,
        "recommended_gallons": None,
        "reviewer_user_id": None,
        "decider_user_id": None,
        "payment_reference": None,
    })
    db.refund_claims[row["id"]] = row
    return response.object_response(derive.refund_claim_json(row), 201)


@bp.get("/refund-claims/<claim_id>")
def read_claim(claim_id):
    user_id, role = middleware.require(*READ_ROLES)
    row = helpers.ensure("refund_claim", helpers.peek(
        "refund_claim", claim_id, user_id, role, _owner))
    return response.object_response(derive.refund_claim_json(row))


@bp.get("/refund-claims")
def list_claims():
    user_id, role = middleware.require(*READ_ROLES)
    rows = db.ordered(db.refund_claims)
    rows = helpers.agent_narrow(rows, _owner, user_id, role)
    rows = helpers.filter_by(rows, {
        "licensee_id": "licensee_id",
        "claim_type": "claim_type",
        "period_month": "period_month",
        "status": "status",
    })
    return response.list_response(rows, derive.refund_claim_json)


@bp.post("/refund-claims/<claim_id>/review")
def review_claim(claim_id):
    user_id, role = middleware.require(RETURNS_EXAMINER)
    peeked = helpers.peek("refund_claim", claim_id, user_id, role, _owner)
    body = shape.body()
    recommendation = shape.req_enum(body, "recommendation", RECOMMENDATIONS)
    if recommendation == "PARTIAL":
        recommended = shape.req_gallons(body, "recommended_gallons",
                                       gt=calc.ZERO)
    else:
        recommended = shape.opt_gallons(body, "recommended_gallons",
                                        gt=calc.ZERO)
    row = helpers.ensure("refund_claim", peeked)

    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_REFUND_STATE_INVALID")
    if recommendation == "PARTIAL" and recommended > row["allowable_gallons"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "recommended_gallons may not exceed the claim's allowable_gallons.")

    row["recommendation"] = recommendation
    row["recommended_gallons"] = recommended
    row["reviewer_user_id"] = user_id
    row["status"] = "REVIEWED"
    db.touch(row)
    return response.object_response(derive.refund_claim_json(row))


@bp.post("/refund-claims/<claim_id>/decide")
def decide_claim(claim_id):
    user_id, role = middleware.require(TAX_SUPERVISOR)
    peeked = helpers.peek("refund_claim", claim_id, user_id, role, _owner)
    body = shape.body()
    decision = shape.req_enum(body, "decision", DECISIONS)
    row = helpers.ensure("refund_claim", peeked)

    if row["status"] != "REVIEWED":
        raise ApiError("ERR_REFUND_STATE_INVALID")
    if row["reviewer_user_id"] is not None and user_id == row["reviewer_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision == "APPROVED":
        if row["refund_amount_cents"] < calc.MIN_REFUND_CENTS:
            raise ApiError("ERR_REFUND_BELOW_MINIMUM")
    elif decision == "PARTIALLY_APPROVED":
        if (row["recommendation"] != "PARTIAL"
                or row["recommended_gallons"] is None):
            raise ApiError("ERR_DECISION_AMOUNT_INVALID")
        reduced = calc.g2(row["recommended_gallons"])
        amount = calc.rate_cents(reduced, calc.REFUND_PRODUCT)
        # The floor is re-checked against the recomputed amount; on failure
        # nothing at all is written.
        if amount < calc.MIN_REFUND_CENTS:
            raise ApiError("ERR_REFUND_BELOW_MINIMUM")
        row["allowable_gallons"] = reduced
        row["refund_amount_cents"] = amount
    else:
        row["allowable_gallons"] = calc.ZERO
        row["refund_amount_cents"] = 0

    row["status"] = decision
    row["decider_user_id"] = user_id
    db.touch(row)
    return response.object_response(derive.refund_claim_json(row))


@bp.post("/refund-claims/<claim_id>/pay")
def pay_claim(claim_id):
    user_id, role = middleware.require(TAX_SUPERVISOR)
    peeked = helpers.peek("refund_claim", claim_id, user_id, role, _owner)
    body = shape.body()
    payment_reference = shape.req_str(body, "payment_reference")
    row = helpers.ensure("refund_claim", peeked)

    if row["status"] not in ("APPROVED", "PARTIALLY_APPROVED"):
        raise ApiError("ERR_REFUND_STATE_INVALID")
    if row["decider_user_id"] is not None and user_id == row["decider_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    row["status"] = "PAID"
    row["payment_reference"] = payment_reference
    db.touch(row)
    cascade.post_ledger(row["licensee_id"], "REFUND",
                        -row["refund_amount_cents"], "RefundClaim", row["id"],
                        "Refund paid under reference %s" % payment_reference)
    return response.object_response(derive.refund_claim_json(row))
