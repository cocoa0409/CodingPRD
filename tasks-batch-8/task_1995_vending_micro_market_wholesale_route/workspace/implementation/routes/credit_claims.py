"""CreditClaim endpoints (scaffold §1.5; lifecycle per PRD §3.7)."""
from flask import Blueprint, request
import db
from middleware import get_auth, require_role, require_operator_ownership
from response import success_object, success_list, parse_pagination
from util import get_json_body, req_string, req_array, stamp_new, touch
from errors import (
    ApiError, ERR_ORDER_NOT_FOUND, ERR_PRODUCT_NOT_FOUND, ERR_CREDIT_CLAIM_NOT_FOUND,
    ERR_INVALID_REQUEST, ERR_INVALID_QUANTITY, ERR_ORDER_NOT_DELIVERED,
    ERR_CLAIM_WINDOW_EXPIRED, ERR_LINE_NOT_CREDITABLE, ERR_CLAIM_EXCEEDS_DELIVERED_QTY,
    ERR_CLAIM_NOT_SUBMITTED, ERR_CLAIM_NOT_VOIDABLE,
)
from services import pricing
import clock

bp = Blueprint("credit_claims", __name__)

NON_TERMINAL_CLAIM_STATUSES = {"SUBMITTED", "APPROVED", "SETTLED"}


def view(c):
    return {k: v for k, v in c.items()}


@bp.post("/wholesale/credit-claims")
def create_claim():
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["OperatorManager"])
    order_id = req_string(body, "order_id")
    lines = req_array(body, "lines")
    # Tier 2 shape
    for row in lines:
        if not isinstance(row, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "lines rows must be objects")
        pid = row.get("product_id")
        if not isinstance(pid, str) or not pid:
            raise ApiError(ERR_INVALID_REQUEST, 400, "lines[].product_id required")
        qty = row.get("quantity_units")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ApiError(ERR_INVALID_QUANTITY, 400, "quantity_units must be a positive integer")
        exp = row.get("expiration_date")
        if not isinstance(exp, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "lines[].expiration_date required")
        try:
            clock.parse_date(exp)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "expiration_date must be YYYY-MM-DD")
    # Tier 6: body-referenced existence
    order = db.orders.get(order_id)
    if order is None:
        raise ApiError(ERR_ORDER_NOT_FOUND, 404, "ReplenishmentOrder id does not exist")
    require_operator_ownership(role, user_id, order["operator_id"])
    for row in lines:
        if row["product_id"] not in db.products:
            raise ApiError(ERR_PRODUCT_NOT_FOUND, 404, "Product id does not exist")
    # Tier 8: referenced order must be DELIVERED
    if order["fulfillment_status"] != "DELIVERED":
        raise ApiError(ERR_ORDER_NOT_DELIVERED, 409,
                       "Credit claim create requires referenced order fulfillment_status == DELIVERED")
    # Tier 9: temporal — per-line window/creditability (whole claim rejected)
    current_date = clock.now().date()
    line_pcts = []
    for row in lines:
        exp_date = clock.parse_date(row["expiration_date"])
        days_to_expiry = (exp_date - current_date).days
        if days_to_expiry < 0:
            if -days_to_expiry > pricing.CLAIM_WINDOW_DAYS:
                raise ApiError(ERR_CLAIM_WINDOW_EXPIRED, 422,
                               "Expired line claimed more than 30 days after expiration_date")
            pct = 100
        elif days_to_expiry <= pricing.DEEP_SHORT_DATE_DAYS:
            pct = 75
        elif days_to_expiry <= pricing.SHORT_DATE_DAYS:
            pct = 50
        else:
            raise ApiError(ERR_LINE_NOT_CREDITABLE, 422,
                           "Claim line with days_to_expiry > 14 earns no credit")
        line_pcts.append(pct)
    # Tier 11: aggregate delivered-quantity gate
    order_line_by_product = {l["product_id"]: l for l in order["lines"]}
    for row in lines:
        pid = row["product_id"]
        order_line = order_line_by_product.get(pid)
        product = db.products[pid]
        delivered = (order_line["quantity_cases"] * product["case_pack_qty"]) if order_line else 0
        cumulative = row["quantity_units"]
        for c in db.credit_claims.values():
            if c["order_id"] != order_id or c["status"] not in NON_TERMINAL_CLAIM_STATUSES:
                continue
            for cl in c["lines"]:
                if cl["product_id"] == pid:
                    cumulative += cl["quantity_units"]
        if cumulative > delivered:
            raise ApiError(ERR_CLAIM_EXCEEDS_DELIVERED_QTY, 422,
                           "Cumulative claimed units exceed delivered units")
    # Compute pinned line credits
    new_lines = []
    requested_total = 0
    for row, pct in zip(lines, line_pcts):
        pid = row["product_id"]
        order_line = order_line_by_product.get(pid)
        product = db.products[pid]
        if order_line is not None:
            credit = pricing.line_credit(order_line, row["quantity_units"], pct, product["case_pack_qty"])
        else:
            credit = 0  # unreachable (aggregate gate already failed), kept defensive
        new_lines.append({
            "product_id": pid,
            "quantity_units": row["quantity_units"],
            "expiration_date": row["expiration_date"],
            "line_credit_cents": credit,
        })
        requested_total += credit
    claim = stamp_new({
        "operator_id": order["operator_id"],
        "order_id": order_id,
        "lines": new_lines,
        "requested_credit_cents": requested_total,
        "applied_cents": 0,
        "status": "SUBMITTED",
    })
    db.credit_claims[claim["id"]] = claim
    return success_object(view(claim), 201)


@bp.get("/wholesale/credit-claims")
def list_claims():
    get_auth()
    limit, offset = parse_pagination(request.args)
    op_f = request.args.get("operator_id")
    order_f = request.args.get("order_id")
    items = list(db.credit_claims.values())
    if op_f is not None:
        items = [c for c in items if c["operator_id"] == op_f]
    if order_f is not None:
        items = [c for c in items if c["order_id"] == order_f]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    return success_list([view(c) for c in items[offset:offset + limit]], limit, offset, total)


@bp.get("/wholesale/credit-claims/<claimId>")
def get_claim(claimId):
    get_auth()
    c = db.credit_claims.get(claimId)
    if c is None:
        raise ApiError(ERR_CREDIT_CLAIM_NOT_FOUND, 404, "CreditClaim id does not exist")
    return success_object(view(c))


@bp.post("/wholesale/credit-claims/<claimId>/approve")
def approve_claim(claimId):
    user_id, role = get_auth()
    get_json_body(required=False)
    require_role(role, ["CreditAdjuster"])
    claim = db.credit_claims.get(claimId)
    if claim is None:
        raise ApiError(ERR_CREDIT_CLAIM_NOT_FOUND, 404, "CreditClaim id does not exist")
    if claim["status"] != "SUBMITTED":
        raise ApiError(ERR_CLAIM_NOT_SUBMITTED, 409, "approve requires claim SUBMITTED")
    operator = db.operators[claim["operator_id"]]
    claim["status"] = "APPROVED"
    # CASCADE link 1: balance += requested_credit_cents
    operator["credit_balance_cents"] += claim["requested_credit_cents"]
    touch(operator)
    # CASCADE link 2: auto-apply to oldest OPEN order; link 3 handled inside
    pricing.auto_apply_credit(operator, claim)
    # Claim auto-SETTLED when whole credit absorbed
    if claim["applied_cents"] == claim["requested_credit_cents"]:
        claim["status"] = "SETTLED"
    touch(claim)
    return success_object(view(claim))


@bp.post("/wholesale/credit-claims/<claimId>/reject")
def reject_claim(claimId):
    user_id, role = get_auth()
    get_json_body(required=False)
    require_role(role, ["CreditAdjuster"])
    claim = db.credit_claims.get(claimId)
    if claim is None:
        raise ApiError(ERR_CREDIT_CLAIM_NOT_FOUND, 404, "CreditClaim id does not exist")
    if claim["status"] != "SUBMITTED":
        raise ApiError(ERR_CLAIM_NOT_SUBMITTED, 409, "reject requires claim SUBMITTED")
    claim["status"] = "REJECTED"
    touch(claim)
    return success_object(view(claim))


@bp.post("/wholesale/credit-claims/<claimId>/void")
def void_claim(claimId):
    user_id, role = get_auth()
    get_json_body(required=False)
    require_role(role, ["CreditAdjuster"])
    claim = db.credit_claims.get(claimId)
    if claim is None:
        raise ApiError(ERR_CREDIT_CLAIM_NOT_FOUND, 404, "CreditClaim id does not exist")
    operator = db.operators.get(claim["operator_id"])
    if (claim["status"] != "APPROVED" or claim["applied_cents"] != 0
            or operator["credit_balance_cents"] < claim["requested_credit_cents"]):
        raise ApiError(ERR_CLAIM_NOT_VOIDABLE, 409,
                       "void requires APPROVED with applied_cents == 0 and sufficient pooled balance")
    operator["credit_balance_cents"] -= claim["requested_credit_cents"]
    touch(operator)
    claim["status"] = "VOIDED"
    touch(claim)
    return success_object(view(claim))
