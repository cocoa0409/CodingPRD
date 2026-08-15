"""Commission budgets (PRD §3.2)."""
from flask import Blueprint, request

import audit
import db
import services as svc
from errors import raise_err
from middleware import ALL_ROLES, body, paged, pagination, require_roles
from response import ok_list, ok_object
from util import parse_date, public

bp = Blueprint("budgets", __name__)


@bp.post("/trading/accounts/<accountId>/commission-budgets")
@require_roles("DeskAdmin")
def create_budget(accountId):
    b = body()
    ps_raw = b.get("period_start")
    pe_raw = b.get("period_end")
    ps = parse_date(ps_raw)
    pe = parse_date(pe_raw)
    if ps is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'period_start' must be an ISO date")
    if pe is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'period_end' must be an ISO date")
    if pe <= ps:
        raise_err("ERR_INVALID_REQUEST", "period_end must be strictly after period_start")
    amount = b.get("budget_amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise_err("ERR_INVALID_REQUEST", "Field 'budget_amount_cents' must be a positive integer")
    svc.fetch("accounts", accountId, "ERR_ACCOUNT_NOT_FOUND")
    for existing in db.store["budgets"].values():
        if existing["account_id"] != accountId:
            continue
        if existing["status"] not in ("OPEN", "EXHAUSTED"):
            continue
        # half-open [start, end) intersection; adjacency (end == start) allowed
        if ps < existing["_period_end"] and existing["_period_start"] < pe:
            raise_err("ERR_BUDGET_PERIOD_OVERLAP",
                      "Budget period overlaps an existing budget of this account")
    rec = svc.new_record()
    rec.update({"account_id": accountId, "period_start": ps_raw, "period_end": pe_raw,
                "budget_amount_cents": amount, "accrued_commission_cents": 0,
                "status": "OPEN", "_period_start": ps, "_period_end": pe})
    db.store["budgets"][rec["id"]] = rec
    audit.record_request("CommissionBudget", rec["id"], "BUDGET_CREATED",
                         f"account_id: {accountId}; period: [{ps_raw}, {pe_raw}); "
                         f"budget_amount_cents: {amount}")
    return ok_object(public(rec), 201)


@bp.get("/trading/commission-budgets/<budgetId>")
@require_roles(*ALL_ROLES)
def get_budget(budgetId):
    return ok_object(public(svc.fetch("budgets", budgetId, "ERR_BUDGET_NOT_FOUND")))


@bp.get("/trading/commission-budgets")
@require_roles(*ALL_ROLES)
def list_budgets():
    limit, offset = pagination()
    items = sorted(db.store["budgets"].values(), key=lambda r: r["_seq"])
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [b for b in items if b["account_id"] == account_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, total = paged(items, limit, offset)
    return ok_list([public(b) for b in page], total, limit, offset)
