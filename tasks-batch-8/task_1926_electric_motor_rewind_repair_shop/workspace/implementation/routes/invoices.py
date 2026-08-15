"""Invoice routes: list, get, void, payments (waterfall)."""
from flask import Blueprint, request
from middleware import require_role
from errors import err_invalid_state, err_invoice_has_payments, err_invalid_input
from db import store, new_id
from response import success_object, success_list
from serializers import invoice_view
from services.lazy import bump, refresh_invoice, recompute_standing
from routes.common import (
    get_json_body, parse_int_field, get_shop_or_404, get_work_order_or_404,
    get_invoice_or_404, get_customer_or_404, get_pagination, paginate,
)

bp = Blueprint("invoices", __name__)


def _refresh_customer_invoices(customer_id):
    for inv in store.invoices.values():
        if inv["customer_id"] == customer_id:
            refresh_invoice(inv)


def _list_invoices(work_order_id=None, shop_id=None, customer_id=None, status=None):
    items = list(store.invoices.values())
    if work_order_id is not None:
        items = [i for i in items if i["work_order_id"] == work_order_id]
    if shop_id is not None:
        items = [
            i for i in items
            if store.work_orders.get(i["work_order_id"], {}).get("shop_id") == shop_id
        ]
    if customer_id is not None:
        items = [i for i in items if i["customer_id"] == customer_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    # apply lazy overdue
    for i in items:
        refresh_invoice(i)
    items.sort(key=lambda i: i["created_at"])
    return items


@bp.route("/shops/<shopId>/work-orders/<woId>/invoices", methods=["GET"])
def list_invoices_for_wo(shopId, woId):
    require_role("ShopAdmin", "Estimator", "ServiceManager", "Customer")
    get_shop_or_404(shopId)
    get_work_order_or_404(woId, shopId)
    limit, offset = get_pagination()
    items = _list_invoices(work_order_id=woId)
    page, total = paginate(items, limit, offset)
    return success_list([invoice_view(i) for i in page], limit, offset, total)


@bp.route("/shops/<shopId>/invoices/<invoiceId>", methods=["GET"])
def get_invoice(shopId, invoiceId):
    require_role("ShopAdmin", "Estimator", "ServiceManager", "Customer")
    get_shop_or_404(shopId)
    inv = get_invoice_or_404(invoiceId, shopId)
    refresh_invoice(inv)
    return success_object(invoice_view(inv))


@bp.route("/shops/invoices-flat", methods=["GET"])
def list_invoices_flat():
    require_role("ShopAdmin", "Estimator", "ServiceManager")
    limit, offset = get_pagination()
    work_order_id = request.args.get("work_order_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = _list_invoices(work_order_id=work_order_id, customer_id=customer_id, status=status)
    page, total = paginate(items, limit, offset)
    return success_list([invoice_view(i) for i in page], limit, offset, total)


@bp.route("/shops/invoices-flat/<invoiceId>", methods=["GET"])
def get_invoice_flat(invoiceId):
    require_role("ShopAdmin", "Estimator", "ServiceManager", "Customer")
    inv = get_invoice_or_404(invoiceId)
    refresh_invoice(inv)
    return success_object(invoice_view(inv))


@bp.route("/shops/<shopId>/invoices/<invoiceId>/void", methods=["POST"])
def void_invoice(shopId, invoiceId):
    require_role("ServiceManager")
    get_shop_or_404(shopId)
    inv = get_invoice_or_404(invoiceId, shopId)
    if inv["status"] != "OPEN":
        raise err_invalid_state("Invoice must be OPEN to void")
    if inv["amount_paid_cents"] != 0:
        raise err_invoice_has_payments()
    inv["status"] = "VOID"
    bump(inv)
    recompute_standing(inv["customer_id"])
    return success_object(invoice_view(inv))


@bp.route("/shops/<shopId>/customers/<customerId>/payments", methods=["POST"])
def record_payment(shopId, customerId):
    require_role("ServiceManager")
    get_shop_or_404(shopId)
    customer = get_customer_or_404(customerId, shopId)
    body = get_json_body()
    payment_cents = parse_int_field(body, "payment_cents", required=True, min_value=0)

    # lazy overdue on all customer's invoices first
    _refresh_customer_invoices(customerId)

    # waterfall: OPEN + OVERDUE, oldest issued_at first, created_at tiebreak
    eligible = [
        i for i in store.invoices.values()
        if i["customer_id"] == customerId and i["status"] in ("OPEN", "OVERDUE")
    ]
    eligible.sort(key=lambda i: (i["issued_at"], i["created_at"]))

    remaining = payment_cents
    applied = []
    for inv in eligible:
        if remaining <= 0:
            break
        take = min(remaining, inv["balance_due_cents"])
        if take <= 0:
            continue
        inv["amount_paid_cents"] += take
        inv["balance_due_cents"] -= take
        remaining -= take
        if inv["balance_due_cents"] == 0:
            inv["status"] = "PAID"
        bump(inv)
        applied.append({"invoice_id": inv["id"], "applied_cents": take})

    credit_added = 0
    if remaining > 0:
        customer["account_credit_cents"] += remaining
        credit_added = remaining
        bump(customer)

    recompute_standing(customerId)

    return success_object({
        "applied": applied,
        "credit_added_cents": credit_added,
    }, status=201)
