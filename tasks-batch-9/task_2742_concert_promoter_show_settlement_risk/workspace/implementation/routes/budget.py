"""Budget lines, the variance ladder and the vendor-invoice control (PRD 3.6)."""

from flask import Blueprint

import common
import recompute
import serializers as ser
import store
import validation as v
from envelope import created, list_response, object_response
from errors import ApiError
from store import db, new_entity

bp = Blueprint("budget", __name__)

CATEGORIES = ("PRODUCTION", "MARKETING", "STAFFING", "HOSPITALITY")
OPEN_SHOW_STATUSES = ("CONFIRMED", "ON_SALE", "PERFORMED")
UNRESOLVED_INVOICE_STATUSES = ("SUBMITTED", "VERIFIED", "DISPUTED")


# ---------------------------------------------------------------------------
# budget lines
# ---------------------------------------------------------------------------

@bp.post("/budget-lines")
def create_budget_line():
    common.auth("TourAccountant")
    body = v.get_body()
    show_id = v.req_str(body, "show_id")
    category = v.req_enum(body, "category", CATEGORIES)
    description = v.req_str(body, "description", max_len=200)
    budgeted = v.req_cents(body, "budgeted_cents", minimum=1)
    deductible = v.opt_bool(body, "is_artist_deductible", default=False)

    show = common.get_show(show_id)

    line = new_entity(
        show_id=show_id,
        category=category,
        description=description,
        budgeted_cents=budgeted,
        is_artist_deductible=deductible,
        actual_cents=0,
        variance_cents=0,
        variance_pct=0,
        variance_status="WITHIN_TOLERANCE",
        required_approver_role="NONE",
        approved_cap_cents=None,
        variance_decided_by_user_id=None,
        variance_justification=None,
        settlement_expense_cents=0,
        status="ACTIVE",
    )
    db.budget_lines[line["id"]] = line
    recompute.cascade(show, bump_show=True, bump_market=True)
    return created(ser.budget_line_json(line))


@bp.get("/budget-lines/<budget_line_id>")
def read_budget_line(budget_line_id):
    common.auth(*common.ALL_ROLES)
    line = common.get_line(budget_line_id)
    return object_response(ser.budget_line_json(line))


@bp.get("/budget-lines")
def list_budget_lines():
    common.auth(*common.ALL_ROLES)
    show_id = common.filter_fk("show_id", common.get_show)
    category = common.filter_arg("category")
    variance_status = common.filter_arg("variance_status")
    status = common.filter_arg("status")
    rows = []
    for line in db.budget_lines.values():
        if show_id is not None and line["show_id"] != show_id:
            continue
        if category is not None and line["category"] != category:
            continue
        if variance_status is not None and line["variance_status"] != variance_status:
            continue
        if status is not None and line["status"] != status:
            continue
        rows.append(line)
    page, limit, offset, total = common.listing(rows, ser.budget_line_json)
    return list_response(page, limit, offset, total)


@bp.post("/budget-lines/<budget_line_id>/variance-decision")
def variance_decision(budget_line_id):
    user_id, role = common.auth("TourAccountant", "RiskOfficer")
    body = v.get_body()
    decision = v.req_enum(body, "decision", ("APPROVE", "REJECT"))
    cap_supplied = v.present(body, "approved_cap_cents")
    approved_cap = v.opt_cents(body, "approved_cap_cents", minimum=0, default=None)
    justification = v.req_str(body, "variance_justification", max_len=500)

    line = common.get_line(budget_line_id)
    common.state_guard(line["variance_status"], ("PENDING_APPROVAL",), ())
    show = common.get_show(line["show_id"])
    common.require(show["show_status"] in OPEN_SHOW_STATUSES,
                   "the show's books are not open")

    if role == "TourAccountant" and line["required_approver_role"] == "RISK_OFFICER":
        raise ApiError("ERR_VARIANCE_APPROVAL_AUTHORITY",
                       "this variance must be decided by a RiskOfficer")

    if decision == "APPROVE":
        if not cap_supplied or approved_cap is None:
            raise ApiError("ERR_VARIANCE_CAP_INVALID",
                           "approved_cap_cents is required on APPROVE")
        if approved_cap < line["budgeted_cents"]:
            raise ApiError("ERR_VARIANCE_CAP_INVALID",
                           "approved_cap_cents must be at least budgeted_cents")
    else:
        if cap_supplied:
            raise ApiError("ERR_VARIANCE_CAP_INVALID",
                           "approved_cap_cents must be absent on REJECT")

    line["variance_justification"] = justification
    line["variance_decided_by_user_id"] = user_id
    if decision == "APPROVE":
        line["variance_status"] = "APPROVED"
        line["approved_cap_cents"] = approved_cap
        line["settlement_expense_cents"] = min(line["actual_cents"], approved_cap)
    else:
        line["variance_status"] = "REJECTED"
        line["approved_cap_cents"] = None
        line["settlement_expense_cents"] = line["budgeted_cents"]
        line["_actual_at_rejection"] = line["actual_cents"]
    store.touch(line)
    recompute.cascade(show, bump_show=True, bump_market=True)
    return object_response(ser.budget_line_json(line))


# ---------------------------------------------------------------------------
# vendor invoices
# ---------------------------------------------------------------------------

@bp.post("/vendor-invoices")
def create_invoice():
    user_id, role = common.auth("TourAccountant", "VenueOperator")
    body = v.get_body()
    show_id = v.req_str(body, "show_id")
    line_id = v.req_str(body, "budget_line_id")
    vendor_name = v.req_str(body, "vendor_name", max_len=120)
    amount = v.req_cents(body, "amount_cents", minimum=1)
    # PRD 2.9 scopes the ISO-instant well-formedness rule to `_at` fields; an
    # `invoice_date` is a required string and carries no declared instant shape.
    invoice_date = v.req_str(body, "invoice_date")
    documentation_ref = v.req_str(body, "documentation_ref", max_len=64)

    show = common.get_show(show_id)
    line = common.get_line(line_id)
    common.require_show_owner(show, user_id, role)
    if line["show_id"] != show_id:
        raise ApiError("ERR_BUDGET_LINE_SHOW_MISMATCH",
                       "the budget line belongs to another show")

    invoice = new_entity(
        show_id=show_id,
        budget_line_id=line_id,
        vendor_name=vendor_name,
        amount_cents=amount,
        invoice_date=invoice_date,
        documentation_ref=documentation_ref,
        status="SUBMITTED",
        verified_by_user_id=None,
        approved_by_user_id=None,
        dispute_reason=None,
        resubmit_count=0,
    )
    db.vendor_invoices[invoice["id"]] = invoice
    return created(ser.vendor_invoice_json(invoice))


@bp.get("/vendor-invoices/<vendor_invoice_id>")
def read_invoice(vendor_invoice_id):
    common.auth("TalentBuyer", "TourAccountant", "RiskOfficer", "VenueOperator")
    invoice = common.get_invoice(vendor_invoice_id)
    return object_response(ser.vendor_invoice_json(invoice))


@bp.get("/vendor-invoices")
def list_invoices():
    common.auth("TalentBuyer", "TourAccountant", "RiskOfficer", "VenueOperator")
    show_id = common.filter_fk("show_id", common.get_show)
    line_id = common.filter_fk("budget_line_id", common.get_line)
    status = common.filter_arg("status")
    rows = []
    for invoice in db.vendor_invoices.values():
        if show_id is not None and invoice["show_id"] != show_id:
            continue
        if line_id is not None and invoice["budget_line_id"] != line_id:
            continue
        if status is not None and invoice["status"] != status:
            continue
        rows.append(invoice)
    page, limit, offset, total = common.listing(rows, ser.vendor_invoice_json)
    return list_response(page, limit, offset, total)


@bp.post("/vendor-invoices/<vendor_invoice_id>/verify")
def verify_invoice(vendor_invoice_id):
    user_id, _role = common.auth("TourAccountant")
    v.get_body()
    invoice = common.get_invoice(vendor_invoice_id)
    common.state_guard(invoice["status"], ("SUBMITTED",), common.TERMINAL_INVOICE)
    show = common.get_show(invoice["show_id"])
    line = common.get_line(invoice["budget_line_id"])
    common.require(show["show_status"] in OPEN_SHOW_STATUSES,
                   "the show's books are not open")
    common.require(line["status"] == "ACTIVE", "the budget line is not ACTIVE")

    invoice["status"] = "VERIFIED"
    invoice["verified_by_user_id"] = user_id
    store.touch(invoice)
    return object_response(ser.vendor_invoice_json(invoice))


@bp.post("/vendor-invoices/<vendor_invoice_id>/approve")
def approve_invoice(vendor_invoice_id):
    user_id, _role = common.auth("TourAccountant", "RiskOfficer")
    v.get_body()
    invoice = common.get_invoice(vendor_invoice_id)
    common.state_guard(invoice["status"], ("VERIFIED",), common.TERMINAL_INVOICE)
    show = common.get_show(invoice["show_id"])
    line = common.get_line(invoice["budget_line_id"])
    common.require(show["show_status"] in OPEN_SHOW_STATUSES,
                   "the show's books are not open")
    common.require(line["status"] == "ACTIVE", "the budget line is not ACTIVE")
    common.require_different_actor(
        user_id, invoice["verified_by_user_id"],
        "the approver must differ from the verifier")

    invoice["status"] = "APPROVED"
    invoice["approved_by_user_id"] = user_id
    store.touch(invoice)

    recompute.refresh_line_variance(line)
    store.touch(line)
    recompute.cascade(show, bump_show=True, bump_market=True)
    return object_response(ser.vendor_invoice_json(invoice))


@bp.post("/vendor-invoices/<vendor_invoice_id>/dispute")
def dispute_invoice(vendor_invoice_id):
    user_id, role = common.auth("TourAccountant", "VenueOperator")
    body = v.get_body()
    reason = v.req_str(body, "dispute_reason", max_len=500)
    invoice = common.get_invoice(vendor_invoice_id)
    show = common.get_show(invoice["show_id"])
    common.require_show_owner(show, user_id, role)
    common.state_guard(invoice["status"], ("SUBMITTED", "VERIFIED"),
                       common.TERMINAL_INVOICE)

    invoice["status"] = "DISPUTED"
    invoice["dispute_reason"] = reason
    invoice["verified_by_user_id"] = None
    store.touch(invoice)
    return object_response(ser.vendor_invoice_json(invoice))


@bp.post("/vendor-invoices/<vendor_invoice_id>/dispute-resolution")
def resolve_dispute(vendor_invoice_id):
    common.auth("TourAccountant")
    body = v.get_body()
    outcome = v.req_enum(body, "outcome", ("RESUBMIT", "REJECT"))
    if outcome == "RESUBMIT":
        amount = v.req_cents(body, "amount_cents", minimum=1)
        documentation_ref = v.req_str(body, "documentation_ref", max_len=64)
    else:
        amount = None
        documentation_ref = None
        v.req_str(body, "reason", max_len=500)

    invoice = common.get_invoice(vendor_invoice_id)
    common.state_guard(invoice["status"], ("DISPUTED",), common.TERMINAL_INVOICE)

    if outcome == "RESUBMIT":
        invoice["status"] = "SUBMITTED"
        invoice["amount_cents"] = amount
        invoice["documentation_ref"] = documentation_ref
        invoice["resubmit_count"] += 1
        invoice["dispute_reason"] = None
        invoice["verified_by_user_id"] = None
        store.touch(invoice)
        return object_response(ser.vendor_invoice_json(invoice))

    invoice["status"] = "REJECTED"
    store.touch(invoice)
    line = common.get_line(invoice["budget_line_id"])
    show = common.get_show(invoice["show_id"])
    recompute.refresh_line_variance(line)
    store.touch(line)
    recompute.cascade(show, bump_show=True, bump_market=False)
    return object_response(ser.vendor_invoice_json(invoice))
