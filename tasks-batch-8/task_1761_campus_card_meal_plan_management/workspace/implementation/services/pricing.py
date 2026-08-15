"""Calculation rules (PRD 3.4, 3.7; scaffold calculations table).
All money is integer cents; every component is rounded half-up exactly once."""

from decimal import Decimal, ROUND_HALF_UP

from db import store
from services.core import clock, clock_date, dt_of

MIN_REFUND_CENTS = 1000
PROVISIONAL_DAILY_CAP_CENTS = 2500
FRAUD_SUSPENSION_THRESHOLD = 3
DISPUTE_WINDOW_DAYS = 30

TIER_FEES = {1: 2500, 2: 3500}
TIER_FEE_3_PLUS = 5000
STOLEN_SURCHARGE_MULTIPLIER = 2
DAMAGED_SURRENDER_DISCOUNT = 1500


def rhu(numerator, denominator):
    """round_half_up(numerator / denominator) to whole cents."""
    q = (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def term_total_days(term):
    return (dt_of(term, "end_date").date() - dt_of(term, "start_date").date()).days + 1


def activation_pricing(plan, term):
    """enrollment_activation_pricing: charge first, then grant; each rounded
    once, independently. Returns (charge_cents, grant_cents)."""
    if term["proration_mode"] == "WEEKLY":
        t = term["total_weeks"]
        remaining = t - term["current_week_index"] + 1
        charge = rhu(plan["price_cents"] * remaining, t)
        grant = rhu(plan["dining_dollar_allocation_cents"] * remaining, t)
    else:
        total_days = term_total_days(term)
        consumed = max(0, (clock_date() - dt_of(term, "start_date").date()).days)
        remaining = total_days - consumed
        charge = rhu(plan["price_cents"] * remaining, total_days)
        grant = rhu(plan["dining_dollar_allocation_cents"] * remaining, total_days)
    return charge, grant


def cancellation_credit(enrollment, plan, term):
    """enrollment_cancellation_credit: credit = charge - earned, floored at 0."""
    if term["proration_mode"] == "WEEKLY":
        consumed = max(0, term["current_week_index"] - (enrollment.get("enrolled_week_index") or 0))
        earned = rhu(plan["price_cents"] * consumed, term["total_weeks"])
    else:
        total_days = term_total_days(term)
        act = dt_of(enrollment, "activated_at")
        consumed = (clock_date() - act.date()).days if act else 0
        earned = rhu(plan["price_cents"] * min(consumed, total_days), total_days)
    return max(0, (enrollment.get("charge_cents") or 0) - earned)


def plan_change_proration(old_enrollment, old_plan, new_plan, term, effective_week_index):
    """plan_change_proration: pinned five-step evaluation order.
    Returns (charge_delta, funding_delta, new_due, credit_from_old)."""
    w = effective_week_index
    t = term["total_weeks"]
    p_old = old_plan["price_cents"]
    p_new = new_plan["price_cents"]
    a_new = new_plan["dining_dollar_allocation_cents"]
    c_old = old_enrollment["charge_cents"] or 0
    if term["proration_mode"] == "WEEKLY":
        old_earned = rhu(p_old * (w - 1), t)                      # (1)
        credit_from_old = max(0, c_old - old_earned)              # (2)
        new_due = rhu(p_new * (t - w + 1), t)                     # (3)
        charge_delta = new_due - credit_from_old                  # (4)
        funding_delta = rhu(a_new * (t - w + 1), t)               # (5)
    else:
        total_days = term_total_days(term)
        days_consumed = (clock_date() - dt_of(term, "start_date").date()).days
        old_earned = rhu(p_old * days_consumed, total_days)
        credit_from_old = max(0, c_old - old_earned)
        new_due = rhu(p_new * (total_days - days_consumed), total_days)
        charge_delta = new_due - credit_from_old
        funding_delta = rhu(a_new * (total_days - days_consumed), total_days)
    return charge_delta, funding_delta, new_due, credit_from_old


def replacement_fee(holder, old_card, reason, police_report_number, surrendered):
    """replacement_fee_schedule: tiered pricing, rules applied in order."""
    ordinal = 1 + sum(
        1 for c in store.cards.values()
        if c["holder_id"] == holder["id"] and c["id"] != old_card["id"]
        and c["lifecycle_status"] == "REPLACED"
    )
    tier = TIER_FEES.get(ordinal, TIER_FEE_3_PLUS)
    police = bool(old_card.get("stolen_police_report_number")) or bool(police_report_number)
    if holder["holder_type"] in ("FACULTY", "STAFF") and ordinal == 1:
        return 0                                        # (1) free first replacement
    if reason == "STOLEN" and police:
        return 0                                        # (2)
    if reason == "STOLEN" and not police:
        return tier * STOLEN_SURCHARGE_MULTIPLIER       # (3)
    if reason == "DAMAGED" and surrendered:
        return max(0, tier - DAMAGED_SURRENDER_DISCOUNT)  # (4)
    return tier                                         # (5)


def settlement_commission(merchant, swept_amounts):
    """merchant_settlement_sweep commission variants; rounding order is
    variant-defining."""
    gross = sum(swept_amounts)
    bps = merchant["commission_bps"]
    if merchant["commission_mode"] == "PER_TRANSACTION":
        commission = sum(rhu(a * bps, 10000) for a in swept_amounts)
    else:  # AGGREGATE
        commission = rhu(gross * bps, 10000)
    return gross, commission, gross - commission


def unresolved_provisional_for_account(account):
    """Sum of provisional_credit_cents over the holder's disputes in
    OPENED | PROVISIONAL_CREDIT_GRANTED whose transaction debited this account."""
    total = 0
    for d in store.disputes.values():
        if d["status"] in ("OPENED", "PROVISIONAL_CREDIT_GRANTED"):
            tx = store.transactions.get(d["transaction_id"])
            if tx is not None and tx.get("account_id") == account["id"]:
                total += d["provisional_credit_cents"]
    return total


def refund_amount(account):
    """term_end_refund_amount. Returns (variant, amount_cents)."""
    unresolved = unresolved_provisional_for_account(account)
    if unresolved == 0:
        return "FULL_BALANCE", account["balance_cents"]
    return "AUTO_EXCLUDING_PROVISIONAL", max(0, account["balance_cents"] - unresolved)


def provisional_day_total(card_id):
    """Sum of amount_cents over the card's PURCHASE ledger entries (both account
    types) whose created_at falls on the same UTC date as the clock."""
    today = clock_date()
    total = 0
    tx_ids = {t["id"] for t in store.transactions.values() if t["card_id"] == card_id}
    for e in store.ledger_entries.values():
        if (e["entry_type"] == "PURCHASE"
                and e.get("reference_transaction_id") in tx_ids):
            if dt_of(e, "created_at").date() == today:
                total += e["amount_cents"]
    return total
