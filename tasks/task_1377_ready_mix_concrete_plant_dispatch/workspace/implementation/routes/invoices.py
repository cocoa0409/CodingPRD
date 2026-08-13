"""Invoice routes: get, list, issue, dispute, adjust, pay."""

from flask import Blueprint

import clock
import errors
import middleware as mw
import response
from db import stores
from routes.catalog import get_or_404, request_args
from services import calc

bp = Blueprint("invoices", __name__)

PM = ["PlantManager"]
CUSTOMER = ["Customer"]

TERMINAL_STATES = ("PAID", "VOID")


@bp.get("/v1/invoices/<rid>")
def get_invoice(rid):
    user_id, role = mw.require_auth(mw.ALL_ROLES)
    rec = get_or_404("invoices", rid)
    if role == "Customer" and rec["customer_id"] != user_id:
        raise errors.err_ownership()
    return response.success_object(rec)


@bp.get("/v1/invoices")
def list_invoices():
    mw.require_auth(mw.ALL_ROLES)
    limit, offset = mw.parse_pagination()
    items = list(stores["invoices"].values())
    args = request_args()
    for field in ("order_id", "customer_id", "status"):
        v = mw.optional_string(args, field)
        if v is not None:
            items = [i for i in items if i.get(field) == v]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array(page, limit, offset, total)


def _sync_order_billing(invoice, to_status):
    order = stores["orders"].get(invoice["order_id"])
    if order is not None:
        order["billing_status"] = to_status
        mw.touch(order)
    return order


def _touch_customer(customer):
    if customer is not None and calc.recompute_credit_exposure(customer):
        mw.touch(customer)


@bp.post("/v1/invoices/<rid>/issue")
def issue_invoice(rid):
    mw.require_auth(PM)
    rec = get_or_404("invoices", rid)
    if rec["status"] in TERMINAL_STATES:
        raise errors.err_already_terminal()
    if rec["status"] != "DRAFT":
        raise errors.err_invalid_state()
    rec["status"] = "ISSUED"
    rec["issued_at"] = clock.iso(clock.now())
    mw.touch(rec)
    _sync_order_billing(rec, "INVOICED")
    return response.success_object(rec)


@bp.post("/v1/invoices/<rid>/dispute")
def dispute_invoice(rid):
    user_id, _ = mw.require_auth(CUSTOMER)
    rec = get_or_404("invoices", rid)
    if rec["customer_id"] != user_id:
        raise errors.err_ownership()
    if rec["status"] in TERMINAL_STATES:
        raise errors.err_already_terminal()
    if rec["status"] != "ISSUED":
        raise errors.err_invalid_state()
    rec["status"] = "DISPUTED"
    mw.touch(rec)
    _sync_order_billing(rec, "DISPUTED")
    return response.success_object(rec)


@bp.post("/v1/invoices/<rid>/adjust")
def adjust_invoice(rid):
    mw.require_auth(PM)
    rec = get_or_404("invoices", rid)
    body = mw.get_json_body()
    adjustment_lines = mw.require_field(body, "adjustment_lines")
    if not isinstance(adjustment_lines, list):
        raise errors.err_validation("adjustment_lines must be an array")
    if len(adjustment_lines) == 0:
        raise errors.err_validation("adjustment_lines must be non-empty")
    for line in adjustment_lines:
        if not isinstance(line, dict) or not mw.is_int(line.get("amount_cents")):
            raise errors.err_validation(
                "adjustment lines must carry an integer amount_cents")
    if rec["status"] in TERMINAL_STATES:
        raise errors.err_already_terminal()
    if rec["status"] != "DISPUTED":
        raise errors.err_invalid_state()
    for line in adjustment_lines:
        rec["line_items"].append(dict(line))
    rec["total_cents"] = sum(li["amount_cents"] for li in rec["line_items"])
    rec["status"] = "ISSUED"
    mw.touch(rec)
    _sync_order_billing(rec, "INVOICED")
    _touch_customer(stores["customers"].get(rec["customer_id"]))
    return response.success_object(rec)


@bp.post("/v1/invoices/<rid>/pay")
def pay_invoice(rid):
    user_id, _ = mw.require_auth(CUSTOMER)
    rec = get_or_404("invoices", rid)
    if rec["customer_id"] != user_id:
        raise errors.err_ownership()
    body = mw.get_json_body()
    amount_cents = mw.require_int(body, "amount_cents")
    if rec["status"] in TERMINAL_STATES:
        raise errors.err_already_terminal()
    if rec["status"] != "ISSUED":
        raise errors.err_invalid_state()
    if amount_cents != rec["total_cents"]:
        raise errors.err_payment_mismatch()
    rec["status"] = "PAID"
    mw.touch(rec)
    _sync_order_billing(rec, "PAID")
    _touch_customer(stores["customers"].get(rec["customer_id"]))
    return response.success_object(rec)
