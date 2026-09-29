"""Rebate accrual and clawback (PRD 3.9)."""
from decimal import Decimal

import clock
import db
from services import tier as tier_svc
from services.money import round_half_up

REBATE_PERIOD_DAYS = 90


def rebate_rate(account):
    return tier_svc.tier_by_code(account.get("tier_code"))["rebate_rate_pct"]


def _accruals_of(account_id):
    return db.where("rebate_accruals", pro_account_id=account_id)


def recompute_payable(accrual):
    accrual["payable_cents"] = max(0, accrual["accrued_cents"] - accrual["clawed_back_cents"])
    return accrual


def recompute_account_total(account):
    total = 0
    for accrual in _accruals_of(account["id"]):
        if accrual["payout_status"] in ("ACCRUING", "PAYABLE"):
            total += accrual["payable_cents"]
    account["rebate_accrued_cents"] = total
    db.touch(account)
    return account


def open_accrual(account):
    period_start = clock.today()
    period_end = clock.add_days(period_start, REBATE_PERIOD_DAYS)
    return db.new_record("rebate_accruals", {
        "pro_account_id": account["id"],
        "period_start": clock.fmt_date(period_start),
        "period_end": clock.fmt_date(period_end),
        "accrued_cents": 0,
        "clawed_back_cents": 0,
        "payable_cents": 0,
        "payout_status": "ACCRUING",
        "closed_at": None,
        "payout_reference": None,
        "paid_amount_cents": 0,
    })


def book_accrual(account, order):
    """Invoice leg: the delta lands on the account's ACCRUING accrual, creating one if needed."""
    target = None
    for accrual in _accruals_of(account["id"]):
        if accrual["payout_status"] == "ACCRUING":
            target = accrual
            break
    if target is None:
        target = open_accrual(account)
    delta = round_half_up(Decimal(order["subtotal_cents"] or 0) * rebate_rate(account))
    target["accrued_cents"] += delta
    recompute_payable(target)
    db.touch(target)
    recompute_account_total(account)
    return target


def book_clawback(account, request):
    """Return-credit leg: the newest ACCRUING or PAYABLE accrual absorbs the clawback."""
    target = None
    for accrual in _accruals_of(account["id"]):
        if accrual["payout_status"] in ("ACCRUING", "PAYABLE"):
            target = accrual  # keep walking: creation order ascending, so the last wins
    if target is None:
        recompute_account_total(account)
        return None
    delta = round_half_up(Decimal(request["gross_refund_cents"] or 0) * rebate_rate(account))
    target["clawed_back_cents"] += delta
    recompute_payable(target)
    db.touch(target)
    recompute_account_total(account)
    return target
