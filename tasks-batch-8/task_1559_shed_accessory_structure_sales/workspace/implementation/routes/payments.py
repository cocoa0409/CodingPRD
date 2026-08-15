"""Payment endpoints: order-level cash collection, RTO contract payments,
payment reads. Idempotency per PRD §2.9."""

import math
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request, g

import db
from errors import (
    invalid_request, invalid_state, ApiError,
    ERR_OVERPAYMENT, ERR_ORDER_NOT_PAYABLE, ERR_IDEMPOTENCY_CONFLICT,
)
from middleware import authenticate, require_roles, check_customer_owns_order
from response import success_object, success_list
from services.common import (
    new_id, get_body, require, check_enum, get_order, get_payment,
    get_rto_contract, paginate,
)
from services.pricing import db_parse_date, INSTALLMENT_INTERVAL_DAYS
from services.cascade import maybe_close_order, bump, touch

bp = Blueprint("payments", __name__)

READ_ROLES = ("Customer", "SalesRep", "PermitCoordinator", "InstallCrew",
              "FinanceManager", "OperationsAdmin")

PAYABLE_ORDER_STATES = ("SITE_REVIEW", "PERMIT_REVIEW", "READY_TO_SCHEDULE",
                        "SCHEDULED", "IN_PROGRESS", "COMPLETED")


def _recompute_collected(order: dict):
    order["collected_cents"] = sum(
        p["amount_cents"] for p in db.payments.values()
        if p["order_id"] == order["id"] and p["kind"] in ("DEPOSIT", "BALANCE"))


@bp.post("/api/orders/<oid>/payments")
def record_order_payment(oid):
    authenticate()
    require_roles("FinanceManager", "Customer")
    body = get_body()
    amount_cents = require(body, "amount_cents", "int")
    if amount_cents <= 0:
        raise invalid_request("amount_cents must be a positive whole-cent amount")
    method = require(body, "method", "str")
    check_enum(method, {"CASH", "CARD", "CHECK"}, "method")
    idempotency_key = require(body, "idempotency_key", "str")

    order = get_order(oid)
    check_customer_owns_order(order)

    # State gate (§3.6)
    if order["status"] not in PAYABLE_ORDER_STATES:
        raise invalid_state("Order-level collection is not open in the order's current state")

    # Post-state checks in PRD §3.6 order:
    # 1) overpayment, 2) RTO order not payable, 3) idempotency conflict
    if order["purchase_type"] == "CASH":
        total = (order["final_total_cents"] if order["status"] == "COMPLETED"
                 else order["quoted_total_cents"])
        if order["collected_cents"] + amount_cents > total:
            raise ApiError(ERR_OVERPAYMENT, "Payment amount exceeds remaining amount due", 422)
    if order["purchase_type"] == "RTO":
        raise ApiError(ERR_ORDER_NOT_PAYABLE,
                       "Cash payments are not accepted on an RTO order", 409)

    for p in db.payments.values():
        if (p.get("idempotency_key") == idempotency_key
                and p.get("order_id") == order["id"] and p.get("rto_contract_id") is None):
            if p["amount_cents"] == amount_cents and p["method"] == method:
                return success_object(p, 201)
            raise ApiError(ERR_IDEMPOTENCY_CONFLICT,
                           "idempotency_key reused with a different payload", 409)

    kind = "DEPOSIT" if order["collected_cents"] == 0 else "BALANCE"
    now = db.now_iso()
    payment = {
        "id": new_id(),
        "order_id": order["id"],
        "rto_contract_id": None,
        "kind": kind,
        "amount_cents": amount_cents,
        "method": method,
        "idempotency_key": idempotency_key,
        "applied_to_late_fees_cents": 0,
        "applied_to_principal_cents": 0,
        "recorded_by": g.user_id,
        "created_at": now,
    }
    db.payments[payment["id"]] = payment
    _recompute_collected(order)
    touch(order)
    maybe_close_order(order)
    return success_object(payment, 201)


@bp.get("/api/orders/<oid>/payments")
def list_order_payments(oid):
    authenticate()
    require_roles(*READ_ROLES)
    order = get_order(oid)
    check_customer_owns_order(order)
    rows = [p for p in db.payments.values() if p["order_id"] == oid]
    rows.sort(key=lambda p: p["created_at"])
    limit, offset = paginate(request.args, rows)
    return success_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.get("/api/payments/<pid>")
def read_payment(pid):
    authenticate()
    require_roles(*READ_ROLES)
    payment = get_payment(pid)
    if g.role == "Customer":
        order = db.orders.get(payment["order_id"])
        if order is None or order["customer_id"] != g.user_id:
            from errors import forbidden
            raise forbidden("Customer may only access their own resources")
    return success_object(payment)


# ---------------------------------------------------------------------------
# RTO contract payments
# ---------------------------------------------------------------------------

@bp.post("/api/rto-contracts/<rid>/payments")
def record_rto_payment(rid):
    authenticate()
    require_roles("FinanceManager", "Customer")
    body = get_body()
    amount_cents = require(body, "amount_cents", "int")
    if amount_cents <= 0:
        raise invalid_request("amount_cents must be a positive whole-cent amount")
    method = require(body, "method", "str")
    check_enum(method, {"CASH", "CARD", "CHECK"}, "method")
    idempotency_key = require(body, "idempotency_key", "str")

    contract = get_rto_contract(rid)
    order = db.orders.get(contract["order_id"])
    if g.role == "Customer" and (order is None or order["customer_id"] != g.user_id):
        from errors import forbidden
        raise forbidden("Customer may only access their own resources")

    # Terminal contracts reject payments
    if contract["status"] in ("PAID_OFF", "DEFAULTED"):
        raise ApiError(ERR_ORDER_NOT_PAYABLE,
                       "RTO payments are not accepted on a terminal contract", 409)
    if amount_cents > contract["remaining_balance_cents"] + contract["accrued_late_fees_cents"]:
        raise ApiError(ERR_OVERPAYMENT, "Payment amount exceeds remaining amount due", 422)

    for p in db.payments.values():
        if (p.get("idempotency_key") == idempotency_key
                and p.get("rto_contract_id") == contract["id"]):
            if p["amount_cents"] == amount_cents and p["method"] == method:
                return success_object(p, 201)
            raise ApiError(ERR_IDEMPOTENCY_CONFLICT,
                           "idempotency_key reused with a different payload", 409)

    # Waterfall: late fees first, remainder to principal
    applied_late = min(amount_cents, contract["accrued_late_fees_cents"])
    applied_principal = amount_cents - applied_late

    now = db.now_iso()
    payment = {
        "id": new_id(),
        "order_id": contract["order_id"],
        "rto_contract_id": contract["id"],
        "kind": "RTO_PAYMENT",
        "amount_cents": amount_cents,
        "method": method,
        "idempotency_key": idempotency_key,
        "applied_to_late_fees_cents": applied_late,
        "applied_to_principal_cents": applied_principal,
        "recorded_by": g.user_id,
        "created_at": now,
    }
    db.payments[payment["id"]] = payment

    contract["accrued_late_fees_cents"] -= applied_late
    contract["amount_applied_cents"] += applied_principal
    contract["remaining_balance_cents"] = (contract["total_contract_cents"]
                                           - contract["amount_applied_cents"])
    touch(contract)

    if contract["remaining_balance_cents"] == 0:
        contract["status"] = "PAID_OFF"
    elif contract["status"] == "DELINQUENT":
        # Cure check: zero unpaid past-due installments and zero accrued late fees
        current_date = db_parse_date(db.get_clock()[0:10])
        covered = (contract["amount_applied_cents"] // contract["monthly_payment_cents"])
        first_due = db_parse_date(contract["first_due_date"])
        unpaid_past_due = 0
        from services.pricing import GRACE_DAYS
        for k in range(1, contract["term_months"] + 1):
            due_k = first_due + timedelta(days=INSTALLMENT_INTERVAL_DAYS * (k - 1))
            if (due_k + timedelta(days=GRACE_DAYS)) < current_date:
                if k > covered:
                    unpaid_past_due += 1
        if unpaid_past_due == 0 and contract["accrued_late_fees_cents"] == 0:
            contract["status"] = "ACTIVE"
    return success_object(payment, 201)


@bp.get("/api/rto-contracts/<rid>/payments")
def list_rto_payments(rid):
    authenticate()
    require_roles(*READ_ROLES)
    contract = get_rto_contract(rid)
    if g.role == "Customer":
        order = db.orders.get(contract["order_id"])
        if order is None or order["customer_id"] != g.user_id:
            from errors import forbidden
            raise forbidden("Customer may only access their own resources")
    rows = [p for p in db.payments.values() if p.get("rto_contract_id") == rid]
    rows.sort(key=lambda p: p["created_at"])
    limit, offset = paginate(request.args, rows)
    return success_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.get("/api/orders/<oid>/rto-contract")
def get_order_rto_contract(oid):
    authenticate()
    require_roles(*READ_ROLES)
    order = get_order(oid)
    check_customer_owns_order(order)
    rows = [r for r in db.rto_contracts.values() if r["order_id"] == oid]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = paginate(request.args, rows)
    return success_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.get("/api/rto-contracts/<rid>")
def read_rto_contract(rid):
    authenticate()
    require_roles(*READ_ROLES)
    contract = get_rto_contract(rid)
    if g.role == "Customer":
        order = db.orders.get(contract["order_id"])
        if order is None or order["customer_id"] != g.user_id:
            from errors import forbidden
            raise forbidden("Customer may only access their own resources")
    return success_object(contract)


@bp.post("/api/billing/run")
def billing_run():
    authenticate()
    require_roles("FinanceManager")
    from services.pricing import GRACE_DAYS, DEFAULT_AFTER_DAYS, compute_late_fee_cents

    current_date = db_parse_date(db.get_clock()[0:10])
    contracts = [c for c in db.rto_contracts.values() if c["status"] in ("ACTIVE", "DELINQUENT")]
    contracts.sort(key=lambda c: (c["first_due_date"], c["created_at"]))

    marked_delinquent = 0
    defaulted = 0
    for c in contracts:
        first_due = db_parse_date(c["first_due_date"])
        installments_due = 0
        for k in range(1, c["term_months"] + 1):
            due_k = first_due + timedelta(days=INSTALLMENT_INTERVAL_DAYS * (k - 1))
            if (due_k + timedelta(days=GRACE_DAYS)) < current_date:
                installments_due += 1
        covered = c["amount_applied_cents"] // c["monthly_payment_cents"]
        if c["status"] == "ACTIVE" and installments_due > covered:
            c["status"] = "DELINQUENT"
            c["delinquency_episodes"] += 1
            c["accrued_late_fees_cents"] += compute_late_fee_cents(c["monthly_payment_cents"])
            touch(c)
            marked_delinquent += 1
        if c["status"] == "DELINQUENT":
            covered = c["amount_applied_cents"] // c["monthly_payment_cents"]
            earliest_uncovered = first_due + timedelta(days=INSTALLMENT_INTERVAL_DAYS * covered)
            if (current_date - earliest_uncovered).days >= DEFAULT_AFTER_DAYS:
                c["status"] = "DEFAULTED"
                c["written_off_cents"] = c["remaining_balance_cents"]
                c["remaining_balance_cents"] = 0
                touch(c)
                defaulted += 1
                order = db.orders.get(c["order_id"])
                if order is not None and order["structure_state"] == "INSTALLED":
                    order["structure_state"] = "REPOSSESSION_PENDING"
                    bump(order)

    # Repossession executed during the sweep
    for order in db.orders.values():
        if order["structure_state"] == "REPOSSESSION_PENDING":
            order["structure_state"] = "REPOSSESSED"
            bump(order)

    return success_object({
        "contracts_marked_delinquent": marked_delinquent,
        "contracts_defaulted": defaulted,
    })
