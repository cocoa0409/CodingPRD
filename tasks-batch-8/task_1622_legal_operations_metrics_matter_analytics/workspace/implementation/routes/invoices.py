from flask import Blueprint, request

from db import store, new_entity, new_ledger_entry, touch
from errors import (
    ApiError, ERR_BUDGET_OVERRUN_EXCEEDED, ERR_DUPLICATE, ERR_ENTITY_INACTIVE,
    ERR_INVALID_AMOUNT, ERR_INVALID_STATE, ERR_PERIOD_CLOSED, ERR_SOD_VIOLATION,
)
from middleware import require_roles
from response import object_response
from serializers import invoice_view
from services.aggregates import (
    matching_budgets, recompute_budget, recompute_matter, recompute_period,
)
from validation import Payload, require_exists, list_page

bp = Blueprint("invoices", __name__, url_prefix="/legal-ops/invoices")

ALL = ("LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive")
SOD_THRESHOLD_CENTS = 100000  # >= $1000 triggers segregation of duties
OVERRUN_ALLOWANCE_NUM = 11    # fixed overrun allowance: 10% -> consumed <= allocated * 11/10
OVERRUN_ALLOWANCE_DEN = 10


@bp.post("")
@require_roles("LegalOpsAnalyst")
def create_invoice(user_id, role):
    p = Payload()
    matter_id = p.req_str("matter_id")
    firm_id = p.req_str("firm_id")
    fp_id = p.req_str("fiscal_period_id")
    invoice_number = p.req_str("invoice_number")
    amount = p.req_int("amount_cents")
    fp = firm = None
    if matter_id is not None:
        require_exists(store.matters, matter_id, "matter")
    if firm_id is not None:
        firm = require_exists(store.firms, firm_id, "firm")
    if fp_id is not None:
        fp = require_exists(store.fiscal_periods, fp_id, "fiscal period")
    # Order per PRD 3.5: calendar gate -> firm activity -> uniqueness -> amount.
    if fp is not None and fp["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_PERIOD_CLOSED, 409, "Fiscal period is not OPEN or REOPENED")
    if firm is not None and firm["status"] != "ACTIVE":
        raise ApiError(ERR_ENTITY_INACTIVE, 422, "Firm is not ACTIVE")
    if firm_id is not None and invoice_number is not None:
        for inv in store.invoices.values():
            if inv["firm_id"] == firm_id and inv["invoice_number"] == invoice_number:
                raise ApiError(ERR_DUPLICATE, 409, "Invoice number already exists for this firm")
    if amount is not None and amount <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "amount_cents must be > 0")
    p.finish()
    inv = new_entity({
        "matter_id": matter_id,
        "firm_id": firm_id,
        "fiscal_period_id": fp_id,
        "invoice_number": invoice_number,
        "amount_cents": amount,
        "payment_status": "SUBMITTED",
        "accrual_match_status": "UNMATCHED",
        "matched_accrual_id": None,
        "_creator_id": user_id,
    })
    store.invoices[inv["id"]] = inv
    return object_response(invoice_view(inv), 201)


@bp.get("")
@require_roles(*ALL)
def list_invoices(user_id, role):
    items = list(store.invoices.values())
    for param in ("matter_id", "firm_id", "fiscal_period_id", "payment_status",
                  "accrual_match_status", "matched_accrual_id"):
        v = request.args.get(param)
        if v is not None:
            items = [i for i in items if i[param] == v]
    return list_page(items, invoice_view)


@bp.get("/<iid>")
@require_roles(*ALL)
def get_invoice(user_id, role, iid):
    return object_response(invoice_view(require_exists(store.invoices, iid, "invoice")))


@bp.post("/<iid>/approve")
@require_roles("LegalOpsAnalyst")
def approve(user_id, role, iid):
    inv = require_exists(store.invoices, iid, "invoice")
    if inv["payment_status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Invoice is not SUBMITTED")
    # Segregation of duties (priority 5) fires before the calendar gate (priority 8).
    if inv["amount_cents"] >= SOD_THRESHOLD_CENTS and user_id == inv["_creator_id"]:
        raise ApiError(ERR_SOD_VIOLATION, 403, "Approver cannot be the invoice creator for amounts >= 100000 cents")
    period = store.fiscal_periods.get(inv["fiscal_period_id"])
    if period is not None and period["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_PERIOD_CLOSED, 409, "Fiscal period is not OPEN or REOPENED")
    # Accrual match: OUTSTANDING accrual at the same (matter, period, firm) grain;
    # earliest created_at wins.
    candidates = [
        a for a in store.accruals.values()
        if a["matter_id"] == inv["matter_id"]
        and a["fiscal_period_id"] == inv["fiscal_period_id"]
        and a["firm_id"] == inv["firm_id"]
        and a["status"] == "OUTSTANDING"
    ]
    candidates.sort(key=lambda a: (a["created_at"], a["_seq"]))
    if candidates:
        accrual = candidates[0]
        inv["matched_accrual_id"] = accrual["id"]
        if accrual["amount_cents"] == inv["amount_cents"]:
            inv["accrual_match_status"] = "FULLY_MATCHED"
        elif accrual["amount_cents"] > inv["amount_cents"]:
            inv["accrual_match_status"] = "PARTIALLY_MATCHED"
        else:
            inv["accrual_match_status"] = "OVER_BILLED"
    inv["payment_status"] = "APPROVED"
    touch(inv)
    return object_response(invoice_view(inv))


@bp.post("/<iid>/pay")
@require_roles("LegalOpsManager")
def pay(user_id, role, iid):
    inv = require_exists(store.invoices, iid, "invoice")
    if inv["payment_status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Invoice is not APPROVED")
    period = store.fiscal_periods.get(inv["fiscal_period_id"])
    if period is not None and period["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_PERIOD_CLOSED, 409, "Fiscal period is not OPEN or REOPENED")
    matter = store.matters.get(inv["matter_id"])
    # Hard fiscal cap before anything posts: no matching budget may be pushed past
    # allocated * 1.10 (exact integer comparison, strictly-greater rejects).
    budgets = []
    if matter is not None:
        budgets = matching_budgets(
            inv["fiscal_period_id"], matter["practice_area_id"], matter["matter_type_id"]
        )
        for b in budgets:
            if (b["consumed_cents"] + inv["amount_cents"]) * OVERRUN_ALLOWANCE_DEN \
                    > b["allocated_cents"] * OVERRUN_ALLOWANCE_NUM:
                raise ApiError(
                    ERR_BUDGET_OVERRUN_EXCEEDED, 422,
                    "Payment would push budget consumption past allocated * 1.10",
                )
    # Post the spend line: posting_date = posting period's start_date.
    line = new_ledger_entry({
        "matter_id": inv["matter_id"],
        "fiscal_period_id": inv["fiscal_period_id"],
        "firm_id": inv["firm_id"],
        "invoice_id": inv["id"],
        "posting_date": period["start_date"] if period is not None else None,
        "amount_cents": inv["amount_cents"],
        "source_status": "POSTED",
        "reversal_of_id": None,
    })
    store.spend_lines[line["id"]] = line
    # Matched accrual transitions OUTSTANDING -> MATCHED.
    if inv["matched_accrual_id"] is not None:
        accrual = store.accruals.get(inv["matched_accrual_id"])
        if accrual is not None and accrual["status"] == "OUTSTANDING":
            accrual["status"] = "MATCHED"
            touch(accrual)
    # Cascade: matter, period, budgets recompute (each bumps its own version).
    if matter is not None:
        recompute_matter(matter)
    if period is not None:
        recompute_period(period)
    for b in budgets:
        recompute_budget(b)
    inv["payment_status"] = "PAID"
    touch(inv)
    return object_response(invoice_view(inv))


@bp.post("/<iid>/reject")
@require_roles("LegalOpsAnalyst")
def reject(user_id, role, iid):
    inv = require_exists(store.invoices, iid, "invoice")
    if inv["payment_status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Invoice is not SUBMITTED")
    inv["payment_status"] = "REJECTED"
    touch(inv)
    return object_response(invoice_view(inv))
