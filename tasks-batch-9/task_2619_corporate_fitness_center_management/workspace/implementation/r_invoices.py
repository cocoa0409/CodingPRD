"""MonthlyInvoice endpoints (PRD 3.9)."""
from flask import Blueprint

import calc
from core import (ApiError, ROLE_CLIENT_SPONSOR, ROLE_OPERATOR_ADMIN, body, created,
                 find, get_or_404, new_record, now, ok, opt_str, req_int, req_month, req_str,
                 require, scope_contract, upd, view, where)
from guards import CONTRACT_TERMINAL, INVOICE_TERMINAL, terminal

bp = Blueprint("invoices", __name__)

LIVE_BILLED_STATUSES = ("ISSUED", "DISPUTED", "PAID")
MONEY_FIELDS = ("labor_subtotal_cents", "program_direct_cost_cents", "admin_markup_cents",
                "volume_credit_cents", "downtime_credit_cents", "coverage_penalty_cents",
                "gross_amount_cents", "net_amount_cents", "nte_capped")


def _period_conflict(contract_id, period_month, exclude_id=None):
    for invoice in where("invoice", contract_id=contract_id):
        if invoice["id"] == exclude_id:
            continue
        if invoice["period_month"] != period_month:
            continue
        if invoice["status"] in LIVE_BILLED_STATUSES:
            return True
    return False


@bp.post("/monthly-invoices")
def draft_invoice():
    require(ROLE_OPERATOR_ADMIN)
    data = body()
    contract_id = req_str(data, "contract_id")
    period_month = req_month(data, "period_month")
    expected_contract_version = req_int(data, "expected_contract_version", minimum=1)
    contract = get_or_404("contract", contract_id)
    if expected_contract_version != contract["version"]:
        raise ApiError("ERR_STALE_CONTRACT_VERSION", 412)
    terminal(contract["status"] in CONTRACT_TERMINAL)
    if _period_conflict(contract_id, period_month):
        raise ApiError("ERR_INVOICE_PERIOD_CONFLICT", 409)
    snapshot = contract["fee_structure"]
    amounts = calc.compute_invoice_amounts(contract, period_month, snapshot)
    fields = {
        "contract_id": contract_id,
        "period_month": period_month,
        "fee_structure_snapshot": snapshot,
    }
    for key in MONEY_FIELDS:
        fields[key] = amounts[key]
    fields.update({
        "status": "DRAFT",
        "dispute_reason": None,
        "rebill_count": 0,
        "issued_at": None,
        "disputed_at": None,
        "paid_at": None,
    })
    invoice = new_record("invoice", fields)
    for prior in where("invoice", contract_id=contract_id):
        if prior["id"] != invoice["id"] and prior["period_month"] == period_month and \
                prior["status"] == "DRAFT":
            upd(prior, status="SUPERSEDED")
    upd(contract, version=contract["version"] + 1)
    return created(view(invoice))


@bp.post("/monthly-invoices/<iid>/issue")
def issue_invoice(iid):
    require(ROLE_OPERATOR_ADMIN)
    invoice = get_or_404("invoice", iid)
    body()
    terminal(invoice["status"] in INVOICE_TERMINAL)
    if invoice["status"] != "DRAFT":
        raise ApiError("ERR_INVOICE_NOT_DRAFT", 409)
    contract = find("contract", invoice["contract_id"])
    if contract is None or contract["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409)
    if _period_conflict(invoice["contract_id"], invoice["period_month"],
                        exclude_id=invoice["id"]):
        raise ApiError("ERR_INVOICE_PERIOD_CONFLICT", 409)
    if invoice["fee_structure_snapshot"] == "COST_PLUS":
        headroom = (contract.get("not_to_exceed_cents") or 0) - (
            contract.get("ytd_billed_cents") or 0)
        if headroom <= 0:
            raise ApiError("ERR_NTE_EXHAUSTED", 422)
    upd(invoice, status="ISSUED", issued_at=now())
    upd(contract, ytd_billed_cents=(contract.get("ytd_billed_cents") or 0)
        + invoice["net_amount_cents"])
    return ok(view(invoice))


@bp.post("/monthly-invoices/<iid>/dispute")
def dispute_invoice(iid):
    require(ROLE_CLIENT_SPONSOR)
    invoice = get_or_404("invoice", iid)
    scope_contract(invoice["contract_id"])
    data = body()
    dispute_reason = req_str(data, "dispute_reason", 1, 1000)
    terminal(invoice["status"] in INVOICE_TERMINAL)
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_NOT_ISSUED", 409)
    upd(invoice, status="DISPUTED", disputed_at=now(), dispute_reason=dispute_reason)
    contract = find("contract", invoice["contract_id"])
    if contract is not None:
        upd(contract, ytd_billed_cents=(contract.get("ytd_billed_cents") or 0)
            - invoice["net_amount_cents"])
    return ok(view(invoice))


@bp.post("/monthly-invoices/<iid>/rebill")
def rebill_invoice(iid):
    require(ROLE_OPERATOR_ADMIN)
    invoice = get_or_404("invoice", iid)
    body()
    terminal(invoice["status"] in INVOICE_TERMINAL)
    if invoice["status"] != "DISPUTED":
        raise ApiError("ERR_INVOICE_NOT_DISPUTED", 409)
    contract = find("contract", invoice["contract_id"])
    fields = {"status": "DRAFT", "issued_at": None,
              "rebill_count": (invoice.get("rebill_count") or 0) + 1}
    if contract is not None:
        amounts = calc.compute_invoice_amounts(contract, invoice["period_month"],
                                               invoice["fee_structure_snapshot"])
        for key in MONEY_FIELDS:
            fields[key] = amounts[key]
    upd(invoice, **fields)
    return ok(view(invoice))


@bp.post("/monthly-invoices/<iid>/pay")
def pay_invoice(iid):
    require(ROLE_CLIENT_SPONSOR)
    invoice = get_or_404("invoice", iid)
    scope_contract(invoice["contract_id"])
    data = body()
    opt_str(data, "payment_reference", 1, 120)
    terminal(invoice["status"] in INVOICE_TERMINAL)
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_NOT_ISSUED", 409)
    upd(invoice, status="PAID", paid_at=now())
    return ok(view(invoice))
