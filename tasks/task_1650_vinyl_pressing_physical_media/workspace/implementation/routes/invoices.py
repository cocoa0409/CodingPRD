"""Invoice endpoints: issue, list, get, payments, credit memos."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVOICE_NOT_FOUND,
    ERR_ORDER_INVALID_STATE, ERR_INVOICE_INVALID_STATE,
    ERR_PAYMENT_EXCEEDS_BALANCE,
)
from middleware import get_auth, require_role, get_pagination, apply_pagination
from response import success_object, success_list
from services import pricing
from .press_orders import get_order_or_404

bp = Blueprint("invoices", __name__)


def get_invoice_or_404(invoice_id):
    inv = db.invoices.get(invoice_id)
    if not inv:
        raise ApiError(ERR_INVOICE_NOT_FOUND, "Invoice id does not exist", 404)
    return inv


@bp.route("/press-orders/<oid>/invoices", methods=["POST"])
def issue_invoice(oid):
    _, role = get_auth()
    require_role(role, ["BillingClerk"])
    order = get_order_or_404(oid)

    # state precondition: order must be COMPLETED
    if order["production_status"] != "COMPLETED":
        raise ApiError(ERR_INVOICE_INVALID_STATE, "Order must be COMPLETED to invoice", 409)
    # exactly one STANDARD invoice per order
    for inv in db.invoices.values():
        if inv["press_order_id"] == order["id"] and inv["kind"] == "STANDARD":
            raise ApiError(ERR_ORDER_INVALID_STATE, "A STANDARD invoice already exists for this order", 409)

    release = db.releases[order["release_id"]]
    customer = db.customers[release["customer_id"]]
    lines, gross, discount, net = pricing.compute_final_invoice(order, release, customer)

    now = db.timestamp_now()
    invoice = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "press_order_id": order["id"],
        "customer_id": customer["id"],
        "parent_invoice_id": None,
        "kind": "STANDARD",
        "gross_cents": gross,
        "discount_cents": discount,
        "net_cents": net,
        "paid_cents": 0,
        "credited_cents": 0,
        "lines": lines,
        "status": "ISSUED",
    }
    db.invoices[invoice["id"]] = invoice

    # billing dimension UNBILLED -> INVOICED
    order["billing_status"] = "INVOICED"
    order["version"] += 1
    order["updated_at"] = now

    # rebate_tier_evaluation step 3: AFTER issuance, accrue net into trailing
    customer["trailing_billed_cents"] += net
    customer["updated_at"] = now

    return success_object(serializers.invoice(invoice), 201)


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    get_auth()
    limit, offset = get_pagination()
    press_order_id = request.args.get("press_order_id")
    customer_id = request.args.get("customer_id")
    parent_invoice_id = request.args.get("parent_invoice_id")
    status = request.args.get("status")
    items = list(db.invoices.values())
    if press_order_id is not None:
        items = [i for i in items if i["press_order_id"] == press_order_id]
    if customer_id is not None:
        items = [i for i in items if i["customer_id"] == customer_id]
    if parent_invoice_id is not None:
        items = [i for i in items if i.get("parent_invoice_id") == parent_invoice_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.invoice(i) for i in page], limit, offset, total)


@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    get_auth()
    return success_object(serializers.invoice(get_invoice_or_404(iid)))


def _mirror_billing(order, status):
    if status == "PARTIALLY_PAID":
        order["billing_status"] = "PARTIALLY_PAID"
    elif status == "PAID":
        order["billing_status"] = "PAID"
    elif status == "CREDITED":
        order["billing_status"] = "CREDIT_CLOSED"
    order["version"] += 1
    order["updated_at"] = db.timestamp_now()


@bp.route("/invoices/<iid>/payments", methods=["POST"])
def record_payment(iid):
    _, role = get_auth()
    require_role(role, ["BillingClerk"])
    invoice = get_invoice_or_404(iid)
    body = request.get_json(silent=True) or {}

    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "amount_cents must be a positive integer", 400)

    if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise ApiError(ERR_INVOICE_INVALID_STATE, "Invoice is not payable", 409)

    remaining = invoice["net_cents"] - invoice["paid_cents"] - invoice["credited_cents"]
    if amount > remaining:
        raise ApiError(ERR_PAYMENT_EXCEEDS_BALANCE, "Payment exceeds the remaining balance", 400)

    invoice["paid_cents"] += amount
    if invoice["paid_cents"] + invoice["credited_cents"] >= invoice["net_cents"]:
        invoice["status"] = "PAID"
    else:
        invoice["status"] = "PARTIALLY_PAID"
    invoice["version"] += 1
    invoice["updated_at"] = db.timestamp_now()

    order = db.press_orders.get(invoice["press_order_id"])
    if order is not None:
        _mirror_billing(order, invoice["status"])

    return success_object(serializers.invoice(invoice))


@bp.route("/invoices/<iid>/credit-memos", methods=["POST"])
def create_credit_memo(iid):
    _, role = get_auth()
    require_role(role, ["BillingClerk"])
    invoice = get_invoice_or_404(iid)
    body = request.get_json(silent=True) or {}

    amount = body.get("amount_cents")
    reason = body.get("reason")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "amount_cents must be a positive integer", 400)
    if not isinstance(reason, str) or not reason:
        raise ApiError(ERR_INVALID_REQUEST, "reason is required", 400)

    if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise ApiError(ERR_INVOICE_INVALID_STATE, "Invoice is not creditable", 409)

    remaining = invoice["net_cents"] - invoice["paid_cents"] - invoice["credited_cents"]
    if amount > remaining:
        raise ApiError(ERR_PAYMENT_EXCEEDS_BALANCE, "Credit memo exceeds the remaining balance", 400)

    now = db.timestamp_now()
    memo = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "press_order_id": invoice["press_order_id"],
        "customer_id": invoice["customer_id"],
        "parent_invoice_id": invoice["id"],
        "kind": "CREDIT_MEMO",
        "gross_cents": amount,
        "discount_cents": 0,
        "net_cents": amount,
        "paid_cents": 0,
        "credited_cents": 0,
        "lines": [{
            "label": "credit_memo",
            "gross_cents": amount,
            "discount_cents": 0,
            "net_cents": amount,
        }],
        "status": "PAID",  # memo rows are self-settled; keep them out of outstanding
    }
    db.invoices[memo["id"]] = memo

    invoice["credited_cents"] += amount
    if invoice["credited_cents"] + invoice["paid_cents"] >= invoice["net_cents"]:
        invoice["status"] = "CREDITED"
    invoice["version"] += 1
    invoice["updated_at"] = now

    order = db.press_orders.get(invoice["press_order_id"])
    if order is not None and invoice["status"] == "CREDITED":
        _mirror_billing(order, "CREDITED")

    return success_object(serializers.invoice(memo), 201)
