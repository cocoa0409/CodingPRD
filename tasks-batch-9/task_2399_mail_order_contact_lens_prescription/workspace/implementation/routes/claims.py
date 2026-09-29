"""Out-of-network reimbursement claims and the eight-step money computation."""

import uuid as _uuid

from flask import Blueprint

from db import db, make_row, now, sort_rows, today, touch
from errors import ApiError
from middleware import (
    ROLE_ADMIN,
    ROLE_COMPLIANCE,
    ROLE_CUSTOMER,
    identity,
    lookup,
    paginate,
    parse_body,
    parse_pagination,
    parse_query,
    require_owner,
    require_role,
)
from response import list_response, object_response
from services import calc
from services.events import append_event
from services.ledger import compute_allowance_used, reconcile_customer_id, settled_settlements_on_order

bp = Blueprint("claims", __name__)

CLAIM_STATUSES = ("DRAFT", "GENERATED", "SUBMITTED", "VOIDED")
VOID_REASONS = ("DISPUTE_UPHELD", "CUSTOMER_REQUEST", "PLAN_RETIRED")


def _claim_window_closed(order, plan):
    delivered_at = order.get("delivered_at")
    if delivered_at is None:
        return False
    elapsed = (today() - delivered_at.date()).days
    return elapsed > plan["claim_window_days"]


@bp.post("/reimbursement-claims")
def create_reimbursement_claim():
    user_id, role = identity()
    body = parse_body(
        {
            "order_id": {"type": "uuid", "required": True},
            "customer_id": {"type": "uuid", "required": True},
            "insurance_plan_id": {"type": "uuid", "required": True},
        }
    )
    require_role(role, [ROLE_CUSTOMER, ROLE_ADMIN])
    order = lookup("order", body["order_id"])
    customer = lookup("customer", body["customer_id"])
    plan = lookup("insurance_plan", body["insurance_plan_id"])
    require_owner(role, user_id, customer["id"])
    require_owner(role, user_id, order["customer_id"])
    if plan["status"] == "RETIRED":
        raise ApiError("ERR_PLAN_RETIRED")
    if plan["network_status"] != "OUT_OF_NETWORK":
        raise ApiError("ERR_PLAN_NOT_OUT_OF_NETWORK")
    row = make_row(
        {
            "order_id": body["order_id"],
            "customer_id": body["customer_id"],
            "insurance_plan_id": body["insurance_plan_id"],
            "refund_offset_cents": settled_settlements_on_order(body["order_id"]),
            "base_eligible_cents": None,
            "applied_allowance_cents": None,
            "coinsurance_cents": None,
            "pre_fee_subtotal_cents": None,
            "processing_fee_cents": None,
            "reimbursable_cents": None,
            "packet_reference": None,
            "submitted_at": None,
            "voided_reason": None,
            "status": "DRAFT",
        }
    )
    db.reimbursement_claims[row["id"]] = row
    return object_response(row, 201)


@bp.get("/reimbursement-claims/<claim_id>")
def get_reimbursement_claim(claim_id):
    user_id, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_CUSTOMER])
    claim = lookup("claim", claim_id)
    require_owner(role, user_id, claim["customer_id"])
    return object_response(claim)


@bp.get("/reimbursement-claims")
def list_reimbursement_claims():
    user_id, role = identity()
    filters = parse_query(
        {
            "order_id": {"type": "string"},
            "customer_id": {"type": "string"},
            "insurance_plan_id": {"type": "string"},
            "status": {"type": "enum", "values": CLAIM_STATUSES},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_CUSTOMER])
    rows = list(db.reimbursement_claims.values())
    if role == ROLE_CUSTOMER:
        rows = [r for r in rows if r["customer_id"] == user_id]
    for field in ("order_id", "customer_id", "insurance_plan_id", "status"):
        if filters[field]:
            rows = [r for r in rows if r[field] == filters[field]]
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/reimbursement-claims/<claim_id>/generate")
def generate_reimbursement_claim(claim_id):
    _, role = identity()
    parse_body({})
    require_role(role, [ROLE_COMPLIANCE, ROLE_ADMIN])
    claim = lookup("claim", claim_id)
    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    order = db.orders.get(claim["order_id"])
    if order is None or order["fulfillment_state"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    plan = db.insurance_plans.get(claim["insurance_plan_id"])
    customer = db.customers.get(claim["customer_id"])
    if plan is None:
        raise ApiError("ERR_INSURANCE_PLAN_NOT_FOUND")
    if plan["status"] == "RETIRED":
        raise ApiError("ERR_PLAN_RETIRED")
    if plan["network_status"] != "OUT_OF_NETWORK":
        raise ApiError("ERR_PLAN_NOT_OUT_OF_NETWORK")
    if plan["requires_itemized_receipt"] and not order.get("itemized_receipt_reference"):
        raise ApiError("ERR_ITEMIZED_RECEIPT_REQUIRED")
    if _claim_window_closed(order, plan):
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED")
    allowance_used = compute_allowance_used(customer) if customer is not None else 0
    if plan["annual_allowance_cents"] - allowance_used <= 0:
        raise ApiError("ERR_ALLOWANCE_EXHAUSTED")

    money = calc.claim_money(
        order, plan, settled_settlements_on_order(claim["order_id"]), allowance_used
    )
    claim.update(money)
    claim["packet_reference"] = "PKT-" + _uuid.uuid4().hex[:12].upper()
    claim["status"] = "GENERATED"
    touch(claim)
    reconcile_customer_id(claim["customer_id"])
    return object_response(claim)


@bp.post("/reimbursement-claims/<claim_id>/submit")
def submit_reimbursement_claim(claim_id):
    _, role = identity()
    parse_body({})
    require_role(role, [ROLE_COMPLIANCE, ROLE_ADMIN])
    claim = lookup("claim", claim_id)
    if claim["status"] != "GENERATED" or not claim.get("packet_reference"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    order = db.orders.get(claim["order_id"])
    plan = db.insurance_plans.get(claim["insurance_plan_id"])
    if order is not None and plan is not None and _claim_window_closed(order, plan):
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED")
    claim["status"] = "SUBMITTED"
    claim["submitted_at"] = now()
    touch(claim)
    return object_response(claim)


@bp.post("/reimbursement-claims/<claim_id>/void")
def void_reimbursement_claim(claim_id):
    user_id, role = identity()
    body = parse_body({"voided_reason": {"type": "enum", "values": VOID_REASONS, "required": True}})
    require_role(role, [ROLE_COMPLIANCE, ROLE_ADMIN])
    claim = lookup("claim", claim_id)
    if claim["status"] != "GENERATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    claim["status"] = "VOIDED"
    claim["voided_reason"] = body["voided_reason"]
    touch(claim)
    order = db.orders.get(claim["order_id"])
    prescription_id = order["prescription_id"] if order is not None else None
    if prescription_id is not None:
        append_event(
            prescription_id, "CLAIM_VOIDED", "ReimbursementClaim", claim["id"], (role, user_id)
        )
    reconcile_customer_id(claim["customer_id"])
    return object_response(claim)
