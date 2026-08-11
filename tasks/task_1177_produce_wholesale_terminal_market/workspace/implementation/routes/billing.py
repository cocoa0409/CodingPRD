"""Invoice and Payment routes — invoice_settlement calculation, early-pay
discount with inclusive boundary, PAID at zero balance, overpayment gate."""

from datetime import datetime, timedelta

from flask import Blueprint

from db import store
from errors import (
    raise_error,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_INVOICE_EXISTS,
    ERR_OVERPAYMENT,
)
from middleware import require_roles, check_customer_ownership, ALL_ROLES
from response import success_object, success_list
from services.domain import (
    get_json_body,
    require_fields,
    req_positive_int,
    is_str,
    lookup,
    stamp_new,
    touch,
    paginate,
    sorted_by_created,
    early_pay_discount_cents,
    recompute_customer_credit_exposure,
    clock_now,
    add_days_str,
    PALLET_DEPOSIT_CENTS,
    DISCOUNT_DAYS,
    DATE_FMT,
)

bp = Blueprint("billing", __name__)


@bp.post("/market/invoices")
def create_invoice():
    require_roles(["BillingClerk"])
    body = get_json_body()
    require_fields(body, ["sales_order_id"])
    sales_order_id = body.get("sales_order_id")
    if not is_str(sales_order_id):
        raise_error(ERR_VALIDATION, "sales_order_id must be a string")
    order = lookup(store.sales_orders, sales_order_id, "SalesOrder")
    # Priority 5: specialized ERR_INVOICE_EXISTS when already INVOICED.
    if order["status"] == "INVOICED" or any(
        i["sales_order_id"] == sales_order_id for i in store.invoices.values()
    ):
        raise_error(
            ERR_INVOICE_EXISTS, "An invoice already exists for this order"
        )
    if order["status"] != "DELIVERED":
        raise_error(
            ERR_INVALID_STATE,
            f"Order must be DELIVERED to invoice; current status {order['status']}",
        )
    customer = lookup(store.customers, order["customer_id"], "Customer")

    clock = clock_now()
    invoice_date = clock.strftime(DATE_FMT)
    # Terms snapshotted at issuance.
    due_date = add_days_str(clock.date(), customer["terms_days"])
    discount_eligible_until = add_days_str(clock.date(), DISCOUNT_DAYS)
    deposit_cents = order["pallet_count"] * PALLET_DEPOSIT_CENTS
    total_cents = order["subtotal_cents"] + deposit_cents

    invoice = stamp_new(
        {
            "sales_order_id": sales_order_id,
            "customer_id": order["customer_id"],
            "invoice_date": invoice_date,
            "due_date": due_date,
            "discount_eligible_until": discount_eligible_until,
            "subtotal_cents": order["subtotal_cents"],
            "deposit_cents": deposit_cents,
            "total_cents": total_cents,
            "discount_taken_cents": 0,
            "paid_cents": 0,
            "balance_cents": total_cents,
            "status": "OPEN",
        }
    )
    store.invoices[invoice["id"]] = invoice
    order["status"] = "INVOICED"
    touch(order)
    recompute_customer_credit_exposure(customer["id"])
    return success_object(invoice, 201)


@bp.get("/market/invoices/<invoice_id>")
def get_invoice(invoice_id):
    user_id, role = require_roles(ALL_ROLES)
    invoice = lookup(store.invoices, invoice_id, "Invoice")
    check_customer_ownership(user_id, role, invoice["customer_id"])
    return success_object(invoice, 200)


@bp.get("/market/sales-orders/<order_id>/invoices")
def list_order_invoices(order_id):
    user_id, role = require_roles(ALL_ROLES)
    order = lookup(store.sales_orders, order_id, "SalesOrder")
    check_customer_ownership(user_id, role, order["customer_id"])
    items = [i for i in store.invoices.values() if i["sales_order_id"] == order_id]
    items = sorted_by_created(items)
    page, pagination = paginate(items)
    return success_list(page, pagination, 200)


@bp.post("/market/payments")
def create_payment():
    require_roles(["BillingClerk"])
    body = get_json_body()
    require_fields(body, ["invoice_id", "amount_cents"])
    invoice_id = body.get("invoice_id")
    if not is_str(invoice_id):
        raise_error(ERR_VALIDATION, "invoice_id must be a string")
    amount_cents = req_positive_int(body, "amount_cents")

    invoice = lookup(store.invoices, invoice_id, "Invoice")
    if invoice["status"] not in {"OPEN", "PAST_DUE", "TRUST_CLAIMED"}:
        raise_error(
            ERR_INVALID_STATE,
            f"Invoice must be OPEN, PAST_DUE or TRUST_CLAIMED to pay; current status {invoice['status']}",
        )

    # Early-pay discount: first payment with paid date <= discount_eligible_until
    # (inclusive boundary), only when no discount yet taken.
    clock = clock_now()
    paid_date = clock.strftime(DATE_FMT)
    would_discount = 0
    if (
        invoice["discount_taken_cents"] == 0
        and paid_date <= invoice["discount_eligible_until"]
    ):
        would_discount = early_pay_discount_cents(invoice["total_cents"])

    # Money gate last: overpayment vs balance after any earned discount.
    balance_after_discount = (
        invoice["total_cents"] - would_discount - invoice["paid_cents"]
    )
    if amount_cents > balance_after_discount:
        raise_error(
            ERR_OVERPAYMENT,
            f"Payment {amount_cents} exceeds balance after discount {balance_after_discount}",
        )

    payment = stamp_new(
        {
            "invoice_id": invoice_id,
            "amount_cents": amount_cents,
            "paid_at": _fmt(clock),
        },
        common=False,
    )
    store.payments[payment["id"]] = payment

    if would_discount:
        invoice["discount_taken_cents"] = would_discount
    invoice["paid_cents"] += amount_cents
    invoice["balance_cents"] = (
        invoice["total_cents"]
        - invoice["discount_taken_cents"]
        - invoice["paid_cents"]
    )
    if invoice["balance_cents"] == 0:
        invoice["status"] = "PAID"
    touch(invoice)
    recompute_customer_credit_exposure(invoice["customer_id"])
    return success_object(payment, 201)


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.get("/market/invoices/<invoice_id>/payments")
def list_invoice_payments(invoice_id):
    user_id, role = require_roles(ALL_ROLES)
    invoice = lookup(store.invoices, invoice_id, "Invoice")
    check_customer_ownership(user_id, role, invoice["customer_id"])
    items = [p for p in store.payments.values() if p["invoice_id"] == invoice_id]
    items = sorted_by_created(items)
    page, pagination = paginate(items)
    return success_list(page, pagination, 200)
