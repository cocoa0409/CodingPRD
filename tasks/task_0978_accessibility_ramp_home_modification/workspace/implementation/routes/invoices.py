"""Invoice and invoice line item endpoints."""
from decimal import Decimal
from flask import Blueprint, request

from core import (
    db, ApiError, body, ok_object, paginate, new_record, touch, serialize,
    require_roles, get_case_or_404, get_child_or_404, require_case_active,
    check_expected_case_version, req_str, req_enum, req_dt, req_int, req_num,
    opt_num, opt_str, opt_dt, now, now_iso, iso,
)
from domain import (
    mutate_case, compute_invoice_totals, invoice_line_amounts,
    make_invoice_number,
)

bp = Blueprint("invoices", __name__)

INVOICE_TYPES = ("INSTALLATION", "RENTAL_MONTHLY", "RENTAL_FINAL",
                 "SERVICE_CALL", "WARRANTY_WORK")


def _get_invoice(case_id, invoice_id):
    case = get_case_or_404(case_id)
    inv = get_child_or_404("invoices", invoice_id, "case_id", case_id,
                           "ERR_INVOICE_NOT_FOUND", "Invoice")
    return case, inv


def _check_invoice_funding_cap(case, invoice):
    """Third-party invoices must not exceed the case's funded total."""
    if invoice.get("funding_source_id") and \
            invoice["total_cents"] > case["total_funded_cents"]:
        raise ApiError("ERR_INVOICE_EXCEEDS_FUNDING", 422,
                       "Invoice total exceeds available funding for "
                       "third-party billing")


@bp.route("/cases/<caseId>/invoices", methods=["POST"])
def create_invoice(caseId):
    require_roles("BillingCoordinator")
    case = get_case_or_404(caseId)
    require_case_active(case)
    b = body()
    invoice_type = req_enum(b, "invoice_type", INVOICE_TYPES)
    due_date = req_dt(b, "due_date")
    funding_source_id = opt_str(b, "funding_source_id")
    quote_id = opt_str(b, "quote_id")
    rental_ramp_id = opt_str(b, "rental_ramp_id")
    check_expected_case_version(case, b)

    if funding_source_id is not None:
        src = db["funding_sources"].get(funding_source_id)
        if src is None or src["case_id"] != caseId:
            raise ApiError("ERR_FUNDING_SOURCE_NOT_FOUND", 404,
                           "Funding source with given ID does not exist")
    if quote_id is not None:
        q = db["quotes"].get(quote_id)
        if q is None or q["case_id"] != caseId:
            raise ApiError("ERR_QUOTE_NOT_FOUND", 404,
                           "Quote with given ID does not exist")
    if rental_ramp_id is not None:
        r = db["rental_ramps"].get(rental_ramp_id)
        if r is None or r["case_id"] != caseId:
            raise ApiError("ERR_RAMP_NOT_FOUND", 404,
                           "Rental ramp with given ID does not exist")

    rec = new_record()
    rec.update({
        "case_id": caseId,
        "invoice_number": make_invoice_number(),
        "invoice_type": invoice_type,
        "status": "DRAFT",
        "issue_date": None,
        "due_date": iso(due_date),
        "paid_date": None,
        "subtotal_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "balance_cents": 0,
        "funding_source_id": funding_source_id,
        "quote_id": quote_id,
        "rental_ramp_id": rental_ramp_id,
        "_due_date_dt": due_date,
    })
    compute_invoice_totals(rec)
    _check_invoice_funding_cap(case, rec)
    db["invoices"][rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/cases/<caseId>/invoices", methods=["GET"])
def list_invoices(caseId):
    require_roles()
    get_case_or_404(caseId)
    status = request.args.get("status")
    records = [i for i in db["invoices"].values() if i["case_id"] == caseId]
    if status is not None:
        records = [i for i in records if i["status"] == status]
    return paginate(records)


@bp.route("/cases/<caseId>/invoices/<invoiceId>", methods=["GET"])
def get_invoice(caseId, invoiceId):
    require_roles()
    _case, inv = _get_invoice(caseId, invoiceId)
    return ok_object(serialize(inv))


@bp.route("/cases/<caseId>/invoices/<invoiceId>/line-items", methods=["POST"])
def add_invoice_line(caseId, invoiceId):
    require_roles("BillingCoordinator")
    case, inv = _get_invoice(caseId, invoiceId)
    require_case_active(case)
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Invoice must be DRAFT to add line items")
    b = body()
    description = req_str(b, "description")
    quantity = req_num(b, "quantity")
    unit_price = req_int(b, "unit_price_cents")
    tax_rate = opt_num(b, "tax_rate_pct", Decimal("0.0"))
    period_start = opt_dt(b, "period_start")
    period_end = opt_dt(b, "period_end")

    ext, tax, line_total = invoice_line_amounts(quantity, unit_price, tax_rate)
    rec = new_record()
    rec.update({
        "invoice_id": invoiceId,
        "description": description,
        "quantity": float(quantity),
        "unit_price_cents": unit_price,
        "extended_price_cents": ext,
        "tax_cents": tax,
        "line_total_cents": line_total,
        "period_start": iso(period_start),
        "period_end": iso(period_end),
    })
    db["invoice_line_items"][rec["id"]] = rec
    compute_invoice_totals(inv)
    _check_invoice_funding_cap(case, inv)
    touch(inv)
    return ok_object(serialize(rec), 201)


@bp.route("/cases/<caseId>/invoices/<invoiceId>/send", methods=["POST"])
def send_invoice(caseId, invoiceId):
    require_roles("BillingCoordinator")
    case, inv = _get_invoice(caseId, invoiceId)
    require_case_active(case)
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Invoice must be DRAFT to send")
    b = body()
    check_expected_case_version(case, b)
    lines = [li for li in db["invoice_line_items"].values()
             if li["invoice_id"] == invoiceId]
    if not lines:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Invoice must have at least one line item to send")
    compute_invoice_totals(inv)
    _check_invoice_funding_cap(case, inv)

    inv["status"] = "SENT"
    inv["issue_date"] = now_iso()
    touch(inv)
    mutate_case(case)
    return ok_object(serialize(inv))


@bp.route("/cases/<caseId>/invoices/<invoiceId>/record-payment", methods=["POST"])
def record_payment(caseId, invoiceId):
    require_roles("BillingCoordinator")
    case, inv = _get_invoice(caseId, invoiceId)
    require_case_active(case)
    if inv["status"] not in ("SENT", "PARTIALLY_PAID"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Invoice must be SENT or PARTIALLY_PAID to record payment")
    b = body()
    amount = req_int(b, "amount_cents")
    if amount <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Payment amount must be positive")
    balance = inv["total_cents"] - inv["amount_paid_cents"]
    if amount > balance:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", 422,
                       "Payment amount exceeds invoice balance")

    inv["amount_paid_cents"] += amount
    inv["balance_cents"] = inv["total_cents"] - inv["amount_paid_cents"]
    if amount == balance:
        inv["status"] = "PAID"
        inv["paid_date"] = now_iso()
        inv["amount_paid_cents"] = inv["total_cents"]
        inv["balance_cents"] = 0
    else:
        inv["status"] = "PARTIALLY_PAID"
    touch(inv)
    mutate_case(case)
    return ok_object(serialize(inv))


@bp.route("/cases/<caseId>/invoices/<invoiceId>/void", methods=["POST"])
def void_invoice(caseId, invoiceId):
    require_roles("BillingCoordinator")
    case, inv = _get_invoice(caseId, invoiceId)
    require_case_active(case)
    if inv["status"] not in ("DRAFT", "SENT", "PARTIALLY_PAID", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Invoice cannot be voided from its current state")
    if inv["amount_paid_cents"] != 0:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Invoice with payments cannot be voided")
    inv["status"] = "VOID"
    inv["balance_cents"] = 0
    touch(inv)
    mutate_case(case)
    return ok_object(serialize(inv))


@bp.route("/cases/<caseId>/invoices/<invoiceId>/dispute", methods=["POST"])
def dispute_invoice(caseId, invoiceId):
    require_roles("Client")
    case, inv = _get_invoice(caseId, invoiceId)
    require_case_active(case)
    if inv["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Invoice must be SENT to dispute")
    inv["status"] = "DISPUTED"
    touch(inv)
    mutate_case(case)
    return ok_object(serialize(inv))
