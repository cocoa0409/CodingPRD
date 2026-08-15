"""Routes: invoices and expense lines (allowable reimbursement lifecycle)."""

from flask import Blueprint, request

from auth import get_auth, require_role, ANY_ROLE
from db import store, new_entity, bump, bump_if_changed, public, iso3
from errors import raise_err
from response import ok, ok_list
from services import (
    compute_allowable, compute_prompt_pay_discount, ytd_add, ytd_subtract,
    evaluate_review_flag_on_approve, reevaluate_review_flag,
)
from util import (
    get_body, req_str, opt_str, req_amount, req_quantity, req_enum, get_or_404,
    parse_pagination, paginate, sort_created, ITEM_CODES,
)

bp = Blueprint("invoice", __name__)

PROVISIONAL_SET = {"SUBMITTED", "APPROVED", "PARTIALLY_APPROVED", "PAID"}
FINAL_SET = {"APPROVED", "PARTIALLY_APPROVED", "PAID"}


def _invoice_servicer_id(invoice):
    prop = store.properties.get(invoice["property_id"])
    return prop["servicer_id"] if prop else None


def _require_owning_servicer(invoice, user_id):
    if _invoice_servicer_id(invoice) != user_id:
        raise_err("ERR_FORBIDDEN_FOR_ROLE", "Servicer may act only on its own properties' invoices")


# ---- ExpenseLine --------------------------------------------------------------

@bp.post("/preservation/invoices/<invoiceId>/lines")
def add_expense_line(invoiceId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    inv = get_or_404(store.invoices, invoiceId, "Invoice")
    b = get_body()
    item_code = req_enum(b, "item_code", ITEM_CODES)
    quantity = req_quantity(b, "quantity")
    unit_price_cents = req_amount(b, "unit_price_cents")
    description = opt_str(b, "description")

    if inv["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Expense lines may be added only to a DRAFT invoice")

    line = new_entity({
        "invoice_id": inv["id"],
        "item_code": item_code,
        "description": description,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "claimed_cents": quantity * unit_price_cents,
        "allowed_cents": None,
        "line_discount_cents": 0,
        "denial_reason": None,
    })
    store.expense_lines[line["id"]] = line
    total = sum(
        l["claimed_cents"] for l in store.expense_lines.values() if l["invoice_id"] == inv["id"]
    )
    bump_if_changed(inv, {"claimed_total_cents": total})
    return ok(public(line), status=201)


@bp.get("/preservation/invoices/<invoiceId>/lines")
def list_invoice_lines(invoiceId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    inv = get_or_404(store.invoices, invoiceId, "Invoice")
    limit, offset = parse_pagination()
    items = sort_created([l for l in store.expense_lines.values() if l["invoice_id"] == inv["id"]])
    page, total = paginate(items, public, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/preservation/expense-lines")
def list_expense_lines():
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(store.expense_lines.values())
    for field in ("invoice_id", "item_code"):
        f = request.args.get(field)
        if f is not None:
            items = [l for l in items if l.get(field) == f]
    items = sort_created(items)
    page, total = paginate(items, public, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/preservation/expense-lines/<expenseLineId>")
def get_expense_line(expenseLineId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    line = get_or_404(store.expense_lines, expenseLineId, "ExpenseLine")
    return ok(public(line))


# ---- Invoice ------------------------------------------------------------------

@bp.get("/preservation/invoices/<invoiceId>")
def get_invoice(invoiceId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    inv = get_or_404(store.invoices, invoiceId, "Invoice")
    return ok(public(inv))


@bp.get("/preservation/invoices")
def list_invoices():
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(store.invoices.values())
    for field in ("property_id", "work_order_id", "status"):
        f = request.args.get(field)
        if f is not None:
            items = [i for i in items if i.get(field) == f]
    items = sort_created(items)
    page, total = paginate(items, public, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.post("/preservation/invoices/<invoiceId>/submit")
def submit_invoice(invoiceId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    inv = get_or_404(store.invoices, invoiceId, "Invoice")
    get_body()
    if inv["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Invoice is not DRAFT")
    prop = store.properties.get(inv["property_id"])
    if prop is not None and prop["financial_review_required"]:
        raise_err("ERR_FINANCIAL_REVIEW_REQUIRED", "Property is under financial review")
    has_lines = any(l["invoice_id"] == inv["id"] for l in store.expense_lines.values())
    if not has_lines:
        raise_err("ERR_INVOICE_NO_LINES", "Invoice has no expense lines")

    inv["submitted_at"] = iso3(store.clock)
    total = compute_allowable(inv, PROVISIONAL_SET)
    inv["provisional_allowed_cents"] = total
    inv["status"] = "SUBMITTED"
    bump(inv)
    return ok(public(inv))


@bp.post("/preservation/invoices/<invoiceId>/approve")
def approve_invoice(invoiceId):
    user_id, role = get_auth()
    require_role(role, ["Servicer"])
    inv = get_or_404(store.invoices, invoiceId, "Invoice")
    get_body()
    _require_owning_servicer(inv, user_id)
    if inv["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Invoice is not SUBMITTED")

    total = compute_allowable(inv, FINAL_SET)
    inv["approved_amount_cents"] = total
    discount = compute_prompt_pay_discount(inv)
    inv["prompt_pay_discount_cents"] = discount
    inv["payable_amount_cents"] = total - discount
    inv["approved_at"] = iso3(store.clock)
    inv["status"] = "APPROVED" if total == inv["claimed_total_cents"] else "PARTIALLY_APPROVED"
    bump(inv)

    prop = store.properties.get(inv["property_id"])
    if prop is not None:
        ytd_add(prop, total)
        evaluate_review_flag_on_approve(prop)
    return ok(public(inv))


@bp.post("/preservation/invoices/<invoiceId>/deny")
def deny_invoice(invoiceId):
    user_id, role = get_auth()
    require_role(role, ["Servicer"])
    inv = get_or_404(store.invoices, invoiceId, "Invoice")
    b = get_body()
    _require_owning_servicer(inv, user_id)
    req_str(b, "reason")
    if inv["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Invoice is not SUBMITTED")
    inv["status"] = "DENIED"
    bump(inv)
    return ok(public(inv))


@bp.post("/preservation/invoices/<invoiceId>/appeal")
def appeal_invoice(invoiceId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    inv = get_or_404(store.invoices, invoiceId, "Invoice")
    get_body()
    if inv["status"] not in ("DENIED", "PARTIALLY_APPROVED"):
        raise_err("ERR_INVALID_STATE", "Invoice is not DENIED or PARTIALLY_APPROVED")
    if inv["appeal_round"] >= 1:
        raise_err("ERR_APPEAL_EXHAUSTED", "Invoice has already used its appeal")
    inv["appeal_round"] = 1
    if inv["status"] == "PARTIALLY_APPROVED":
        prop = store.properties.get(inv["property_id"])
        if prop is not None:
            ytd_subtract(prop, inv["approved_amount_cents"] or 0)
    inv["status"] = "SUBMITTED"
    bump(inv)
    return ok(public(inv))


@bp.post("/preservation/invoices/<invoiceId>/mark-paid")
def mark_paid_invoice(invoiceId):
    user_id, role = get_auth()
    require_role(role, ["Servicer"])
    inv = get_or_404(store.invoices, invoiceId, "Invoice")
    get_body()
    _require_owning_servicer(inv, user_id)
    if inv["status"] not in ("APPROVED", "PARTIALLY_APPROVED"):
        raise_err("ERR_INVALID_STATE", "Invoice is not APPROVED or PARTIALLY_APPROVED")
    inv["status"] = "PAID"
    bump(inv)
    return ok(public(inv))


@bp.post("/preservation/invoices/<invoiceId>/void")
def void_invoice(invoiceId):
    user_id, role = get_auth()
    require_role(role, ["Servicer"])
    inv = get_or_404(store.invoices, invoiceId, "Invoice")
    b = get_body()
    _require_owning_servicer(inv, user_id)
    opt_str(b, "reason")
    if inv["status"] not in ("APPROVED", "PARTIALLY_APPROVED"):
        raise_err("ERR_INVALID_STATE", "Invoice is not APPROVED or PARTIALLY_APPROVED")
    inv["status"] = "VOIDED"
    bump(inv)
    prop = store.properties.get(inv["property_id"])
    if prop is not None:
        ytd_subtract(prop, inv["approved_amount_cents"] or 0)
        reevaluate_review_flag(prop)
    return ok(public(inv))
