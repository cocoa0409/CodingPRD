"""PaymentPlan, Payment, and refund endpoints (PRD §3.6, §3.7, §2.6)."""
from flask import Blueprint, request

import db
import common
import errors
import services
import calculations
from middleware import require_roles
from response import success

ALL_ROLES = ("ShopManager", "BridalConsultant", "Seamstress", "FinanceClerk")

bp = Blueprint("payment_plans", __name__)


def _plan_view(plan):
    """Recompute the derived ledger on read and return a serialized view."""
    services.refresh_plan_ledger(plan)
    return common.serialize(plan)


@bp.route("/payment-plans", methods=["POST"])
@require_roles("FinanceClerk", "ShopManager")
def create_plan():
    body = common.get_body()
    gown_order_id = common.as_str(body, "gown_order_id")
    order = services.get_order(gown_order_id)  # FK existence
    term_installments = common.as_int(body, "term_installments", minimum=1)
    deposit_cents = common.as_int(body, "deposit_cents", minimum=0)

    # plan_total snapshot = order.quoted_total_cents + sum(ACTIVE accessory prices).
    plan_total = order["quoted_total_cents"] + sum(
        services.active_accessory_prices(gown_order_id)
    )

    # Deposit floor (priority 10).
    min_deposit = calculations.min_deposit_cents(plan_total)
    if deposit_cents < min_deposit:
        errors.raise_error(errors.ERR_DEPOSIT_BELOW_FLOOR, "Deposit below floor")

    installment = calculations.base_installment_cents(plan_total, deposit_cents, term_installments)

    obj = {
        "id": db.new_id(),
        "gown_order_id": gown_order_id,
        "plan_total_cents": plan_total,
        "term_installments": term_installments,
        "deposit_cents": deposit_cents,
        "installment_cents": installment,
        "amount_paid_cents": 0,
        "balance_due_cents": plan_total,
        "status": "DEPOSIT_DUE",
    }
    db.stamp_create(obj)
    db.payment_plans[obj["id"]] = obj
    return success(common.serialize(obj), status=201)


@bp.route("/payment-plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_plans():
    limit, offset = common.paginate(request.args)
    rows = list(db.payment_plans.values())
    gown_order_id = request.args.get("gown_order_id")
    if gown_order_id is not None:
        rows = [p for p in rows if p["gown_order_id"] == gown_order_id]
    for p in rows:
        services.refresh_plan_ledger(p)
    window, meta = common.page_slice(rows, limit, offset)
    return success([common.serialize(o) for o in window], pagination=meta)


@bp.route("/payment-plans/<pid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_plan(pid):
    obj = services.get_plan(pid)
    return success(_plan_view(obj))


@bp.route("/payment-plans/<pid>/payments", methods=["POST"])
@require_roles("FinanceClerk", "ShopManager")
def post_payment(pid):
    plan = services.get_plan(pid)
    body = common.get_body()
    # Request-shape (priority 4): both fields present & well-typed.
    amount_cents = common.as_int(body, "amount_cents", minimum=1)
    expected_plan_version = common.as_int(body, "expected_plan_version")

    # OCC guard (§2.6): expected_plan_version must equal current plan.version.
    if expected_plan_version != plan["version"]:
        errors.raise_error(errors.ERR_STALE_PLAN_VERSION, "Stale plan version")

    # Current ledger before this payment.
    amount_paid, _ = services.compute_plan_ledger(plan)
    new_paid = amount_paid + amount_cents

    # Overpayment guard (priority 11): cannot push paid strictly above total.
    if new_paid > plan["plan_total_cents"]:
        errors.raise_error(errors.ERR_OVERPAYMENT, "Overpayment")

    # kind: DEPOSIT while the deposit is still being covered, INSTALLMENT after.
    kind = "DEPOSIT" if amount_paid < plan["deposit_cents"] else "INSTALLMENT"

    payment = {
        "id": db.new_id(),
        "payment_plan_id": pid,
        "amount_cents": amount_cents,
        "kind": kind,
        "settlement_status": "SETTLED",
    }
    # Payment is common_fields:false — only id + created_at, no version/updated_at.
    db.stamp_create(payment, with_version=False)
    db.payments[payment["id"]] = payment

    # Recompute ledger, advance plan + linked order status, bump plan version.
    services.refresh_plan_ledger(plan)
    _advance_payment_status(plan)
    db.touch(plan)

    return success(common.serialize(payment), status=201)


def _advance_payment_status(plan):
    """Drive plan.status and order.payment_status on the two coordinated axes."""
    amount_paid = plan["amount_paid_cents"]
    plan_total = plan["plan_total_cents"]
    order = db.gown_orders.get(plan["gown_order_id"])

    if amount_paid == plan_total:
        # PAID_IN_FULL on both axes.
        if plan["status"] in ("DEPOSIT_DUE", "ACTIVE"):
            plan["status"] = "PAID_IN_FULL"
        if order is not None and order["payment_status"] in ("UNPAID", "DEPOSIT_PAID"):
            order["payment_status"] = "PAID_IN_FULL"
            db.touch(order)
    elif amount_paid >= plan["deposit_cents"]:
        # Deposit covered but not fully paid -> ACTIVE / DEPOSIT_PAID.
        if plan["status"] == "DEPOSIT_DUE":
            plan["status"] = "ACTIVE"
        if order is not None and order["payment_status"] == "UNPAID":
            order["payment_status"] = "DEPOSIT_PAID"
            db.touch(order)


@bp.route("/payment-plans/<pid>/payments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_payments(pid):
    services.get_plan(pid)  # existence
    limit, offset = common.paginate(request.args)
    rows = [p for p in db.payments.values() if p["payment_plan_id"] == pid]
    window, meta = common.page_slice(rows, limit, offset)
    return success([common.serialize(o) for o in window], pagination=meta)


@bp.route("/payment-plans/<pid>/refund", methods=["POST"])
@require_roles("FinanceClerk", "ShopManager")
def refund_plan(pid):
    plan = services.get_plan(pid)
    body = common.get_body()
    expected_plan_version = common.as_int(body, "expected_plan_version")

    # OCC guard (§2.6).
    if expected_plan_version != plan["version"]:
        errors.raise_error(errors.ERR_STALE_PLAN_VERSION, "Stale plan version")

    # Cross-entity precondition (priority 6): order must be CANCELLED.
    order = db.gown_orders.get(plan["gown_order_id"])
    if order is None or order["fulfillment_status"] != "CANCELLED":
        errors.raise_error(errors.ERR_REFUND_NOT_ALLOWED, "Refund not allowed")

    amount_paid, _ = services.compute_plan_ledger(plan)

    # Post a single REFUND payment of the current amount_paid_cents.
    refund_payment = {
        "id": db.new_id(),
        "payment_plan_id": pid,
        "amount_cents": amount_paid,
        "kind": "REFUND",
        "settlement_status": "SETTLED",
    }
    db.stamp_create(refund_payment, with_version=False)
    db.payments[refund_payment["id"]] = refund_payment

    # Flip every prior SETTLED (DEPOSIT/INSTALLMENT) payment to REVERSED.
    for p in db.payments.values():
        if p["payment_plan_id"] != pid:
            continue
        if p["id"] == refund_payment["id"]:
            continue
        if p["settlement_status"] == "SETTLED":
            p["settlement_status"] = "REVERSED"

    # Ledger returns to 0 (paid DEPOSIT/INSTALLMENT now REVERSED; REFUND subtracts 0).
    services.refresh_plan_ledger(plan)
    plan["status"] = "CANCELLED"
    if order is not None and order["payment_status"] in ("DEPOSIT_PAID", "PAID_IN_FULL"):
        order["payment_status"] = "REFUNDED"
        db.touch(order)
    db.touch(plan)

    return success(common.serialize(refund_payment), status=201)
