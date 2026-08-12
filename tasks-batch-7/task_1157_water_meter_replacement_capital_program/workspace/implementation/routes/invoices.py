"""Contractor invoice endpoints (PRD 3.9): draft, settlement at submit,
approval against budget availability, dispute."""
import db
from db import base_resource, touch
from errors import raise_err
from middleware import (
    ALL_ROLES,
    check_contractor_ownership,
    require_roles,
)
from response import ok_object
from services.core import (
    BONUS_ELIGIBLE_BP,
    get_or_404,
    list_page,
    money_int,
    program_derived,
    ser_invoice,
)
from decimal import Decimal
from flask import Blueprint, g, request
from validate import body, req_dt, req_str

bp = Blueprint("invoices", __name__)

BONUS_PCT = Decimal("0.02")
PENALTY_PER_FAIL_PCT = Decimal("0.01")
PENALTY_CAP_PCT = Decimal("0.10")
RETAINAGE_PCT_STANDARD = Decimal("0.05")
RETAINAGE_PCT_SUSPENDED = Decimal("0.10")


@bp.post("/api/invoices")
@require_roles("FieldContractor")
def create_invoice():
    b = body()
    # Ownership (stage 3): a contractor creates invoices with its own id.
    contractor_id = b.get("contractor_id")
    if isinstance(contractor_id, str) and contractor_id != g.user_id:
        check_contractor_ownership(contractor_id)
    contractor_id = req_str(b, "contractor_id")
    check_contractor_ownership(contractor_id)
    contractor = get_or_404(db.contractors, contractor_id, "Contractor")
    period_start = req_dt(b, "period_start")
    period_end = req_dt(b, "period_end")
    inv = base_resource()
    inv.update({
        "contractor_id": contractor["id"],
        "program_id": contractor["program_id"],
        "period_start": period_start,
        "period_end": period_end,
        "units_completed": None,
        "gross_amount_cents": None,
        "bonus_cents": None,
        "penalty_cents": None,
        "retainage_cents": None,
        "net_amount_cents": None,
        "dispute_reason": None,
        "status": "DRAFT",
    })
    db.invoices[inv["id"]] = inv
    return ok_object(ser_invoice(inv), 201)


@bp.get("/api/invoices")
@require_roles(*ALL_ROLES)
def list_invoices():
    filters = {}
    for k in ("contractor_id", "program_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    return list_page(db.invoices.values(), filters, ser_invoice)


@bp.get("/api/invoices/<invoiceId>")
@require_roles(*ALL_ROLES)
def get_invoice(invoiceId):
    return ok_object(ser_invoice(get_or_404(db.invoices, invoiceId, "ContractorInvoice")))


@bp.post("/api/invoices/<invoiceId>/submit")
@require_roles("FieldContractor")
def submit_invoice(invoiceId):
    inv = get_or_404(db.invoices, invoiceId, "ContractorInvoice")
    check_contractor_ownership(inv["contractor_id"])
    if inv["status"] not in ("DRAFT", "DISPUTED"):
        raise_err("ERR_INVALID_STATE", "Invoice is not DRAFT or DISPUTED")
    contractor = get_or_404(db.contractors, inv["contractor_id"], "Contractor")
    # invoice_settlement (scaffold 1.3): half-open [period_start, period_end).
    units = sum(
        1
        for wo in db.work_orders.values()
        if wo["contractor_id"] == contractor["id"]
        and wo["lifecycle_status"] == "CLOSED"
        and wo["closed_at"] is not None
        and inv["period_start"] <= wo["closed_at"] < inv["period_end"]
    )
    if units < 1:
        raise_err("ERR_INVOICE_PERIOD_EMPTY",
                  "No completed units in the invoice period")
    gross = units * contractor["unit_price_cents"]
    bonus = (
        money_int(Decimal(gross) * BONUS_PCT)
        if contractor["quality_score_bp"] >= BONUS_ELIGIBLE_BP
        else 0
    )
    fails_in_period = sum(
        1
        for a in db.quality_audits.values()
        if a["contractor_id"] == contractor["id"]
        and a["result_status"] == "FAIL"
        and a["recorded_at"] is not None
        and inv["period_start"] <= a["recorded_at"] < inv["period_end"]
    )
    penalty = min(
        fails_in_period * money_int(Decimal(gross) * PENALTY_PER_FAIL_PCT),
        money_int(Decimal(gross) * PENALTY_CAP_PCT),
    )
    retainage_pct = (
        RETAINAGE_PCT_SUSPENDED
        if contractor["status"] == "SUSPENDED"
        else RETAINAGE_PCT_STANDARD
    )
    retainage = money_int(Decimal(gross) * retainage_pct)
    # Components rounded to whole cents first, then summed (pinned order).
    inv["units_completed"] = units
    inv["gross_amount_cents"] = gross
    inv["bonus_cents"] = bonus
    inv["penalty_cents"] = penalty
    inv["retainage_cents"] = retainage
    inv["net_amount_cents"] = gross + bonus - penalty - retainage
    inv["status"] = "SUBMITTED"
    touch(inv)
    return ok_object(ser_invoice(inv))


@bp.post("/api/invoices/<invoiceId>/approve")
@require_roles("ProgramManager")
def approve_invoice(invoiceId):
    inv = get_or_404(db.invoices, invoiceId, "ContractorInvoice")
    if inv["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Invoice is not SUBMITTED")
    program = get_or_404(db.programs, inv["program_id"], "Program")
    _, _, available, _, _ = program_derived(program)
    # Affordability gate: net <= budget_available_cents, equality allowed.
    if inv["net_amount_cents"] > available:
        raise_err("ERR_BUDGET_AVAILABLE_EXCEEDED",
                  "net_amount_cents exceeds program budget_available_cents")
    inv["status"] = "APPROVED"
    touch(inv)
    return ok_object(ser_invoice(inv))


@bp.post("/api/invoices/<invoiceId>/dispute")
@require_roles("ProgramManager")
def dispute_invoice(invoiceId):
    inv = get_or_404(db.invoices, invoiceId, "ContractorInvoice")
    b = body()
    reason = req_str(b, "reason")
    if inv["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Invoice is not SUBMITTED")
    inv["status"] = "DISPUTED"
    inv["dispute_reason"] = reason
    touch(inv)
    return ok_object(ser_invoice(inv))
