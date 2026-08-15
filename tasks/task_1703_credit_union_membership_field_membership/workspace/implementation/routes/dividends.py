"""Dividend declaration, accrual, void, and payment endpoints."""
from flask import Blueprint, request

import db
from auth import require_roles, STAFF_ROLES
from errors import ApiError
from response import ok_object, paginate, now_iso
from serializers import serialize_declaration, serialize_payment
from services import calc, sweep
from services.sweep import new_id, bump
from validators import get_body, req_int, req_enum, req_date

bp = Blueprint("dividends", __name__)


def _get_declaration_or_404(did):
    d = db.declarations.get(did)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", f"dividend declaration {did} not found")
    return d


@bp.post("/credit-union/dividend-declarations")
def create_declaration():
    uid, _ = require_roles({"BoardDirector"})
    body = get_body()
    # Tier 4: syntactic
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    rate_bps = req_int(body, "rate_bps")
    method = req_enum(body, "method", {"AVERAGE_DAILY_BALANCE", "MINIMUM_DAILY_BALANCE"})
    payable_date = req_date(body, "payable_date")
    # Tier 10: rate band
    if rate_bps < 10 or rate_bps > 1500:
        raise ApiError("ERR_DIVIDEND_RATE_OUT_OF_BAND",
                       "rate_bps must be within the authorized band [10, 1500]")
    # Tier 11: period overlap (closed intervals; only DECLARED/PAID block)
    for d in db.declarations.values():
        if d["status"] in ("DECLARED", "PAID"):
            if period_start <= d["period_end"] and d["period_start"] <= period_end:
                raise ApiError("ERR_DIVIDEND_PERIOD_OVERLAP",
                               "period overlaps an existing DECLARED or PAID declaration")
    # Tier 11: payable_date strictly after period_end
    if payable_date <= period_end:
        raise ApiError("ERR_DATE_ORDER_INVALID",
                       "payable_date must be strictly later than period_end")
    declaration = {
        "id": new_id(),
        "period_start": period_start,
        "period_end": period_end,
        "rate_bps": rate_bps,
        "method": method,
        "payable_date": payable_date,
        "status": "DECLARED",
        "declared_pool_cents": 0,
        "paid_total_cents": None,
        "declared_by_user_id": uid,
        "paid_by_user_id": None,
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.declarations[declaration["id"]] = declaration
    # Provisional accrual: OPEN accounts opened on/before period_end,
    # processed in (opened_date ASC, created_at ASC) order.
    eligible = [a for a in db.accounts.values()
                if a["status"] == "OPEN" and a["opened_date"] <= period_end]
    eligible.sort(key=lambda a: (a["opened_date"], a["created_at"], a["_seq"]))
    pool = 0
    for acc in eligible:
        member = db.members.get(acc["member_id"])
        member_tier = member["tier"] if member is not None else "STANDARD"
        result = calc.compute_dividend(acc, member_tier, declaration)
        if result is None:
            continue
        amount, bonus = result
        payment = {
            "id": new_id(),
            "declaration_id": declaration["id"],
            "share_account_id": acc["id"],
            "accrued_amount_cents": amount,
            "credited_amount_cents": None,
            "accrual_delta_cents": None,
            "tier_bonus_bps_applied": bonus,
            "status": "ACCRUED",
            "version": 1,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "_seq": db.next_seq(),
        }
        db.payments[payment["id"]] = payment
        pool += amount
    declaration["declared_pool_cents"] = pool
    return ok_object(serialize_declaration(declaration), 201)


@bp.get("/credit-union/dividend-declarations/<did>")
def get_declaration(did):
    require_roles(STAFF_ROLES)
    return ok_object(serialize_declaration(_get_declaration_or_404(did)), 200)


@bp.post("/credit-union/dividend-declarations/<did>/void")
def void_declaration(did):
    require_roles({"BoardDirector"})
    declaration = _get_declaration_or_404(did)
    if declaration["status"] != "DECLARED":
        raise ApiError("ERR_DECLARATION_INVALID_STATE",
                       "dividend declaration is not DECLARED")
    for p in db.payments.values():
        if p["declaration_id"] == did and p["status"] == "ACCRUED":
            p["status"] = "VOIDED"
            bump(p)
    declaration["status"] = "VOIDED"
    bump(declaration)
    return ok_object(serialize_declaration(declaration), 200)


@bp.post("/credit-union/dividend-declarations/<did>/pay")
def pay_declaration(did):
    uid, _ = require_roles({"OperationsOfficer"})
    declaration = _get_declaration_or_404(did)
    if declaration["status"] != "DECLARED":
        raise ApiError("ERR_DECLARATION_INVALID_STATE",
                       "dividend declaration is not DECLARED")
    if db.clock.current_date_str() < declaration["payable_date"]:
        raise ApiError("ERR_DIVIDEND_NOT_YET_PAYABLE",
                       "current date is before the payable_date")
    rows = [p for p in db.payments.values()
            if p["declaration_id"] == did and p["status"] == "ACCRUED"]
    rows.sort(key=lambda p: (p["created_at"], p["_seq"]))
    paid_total = 0
    for row in rows:
        account = db.accounts.get(row["share_account_id"])
        if account is None or account["status"] != "OPEN":
            row["status"] = "VOIDED"
            bump(row)
            continue
        member = db.members.get(account["member_id"])
        member_tier = member["tier"] if member is not None else "STANDARD"
        result = calc.compute_dividend(account, member_tier, declaration)
        if result is None:
            row["status"] = "VOIDED"
            bump(row)
            continue
        amount, bonus = result
        row["credited_amount_cents"] = amount
        row["accrual_delta_cents"] = amount - row["accrued_amount_cents"]
        row["tier_bonus_bps_applied"] = bonus
        row["status"] = "CREDITED"
        bump(row)
        sweep.write_system_tx(account, "DIVIDEND_CREDIT", amount,
                              declaration["payable_date"])
        bump(account)
        paid_total += amount
    declaration["paid_total_cents"] = paid_total
    declaration["paid_by_user_id"] = uid
    declaration["status"] = "PAID"
    bump(declaration)
    return ok_object(serialize_declaration(declaration), 200)


@bp.get("/credit-union/dividend-declarations/<did>/payments")
def list_declaration_payments(did):
    require_roles(STAFF_ROLES)
    _get_declaration_or_404(did)
    items = [p for p in db.payments.values() if p["declaration_id"] == did]
    status_f = request.args.get("status")
    if status_f is not None:
        items = [p for p in items if p["status"] == status_f]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return paginate([serialize_payment(p) for p in items])
