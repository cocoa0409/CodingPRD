"""Business services: allocation waterfall, state cascades, payoff, remittance."""
from datetime import timedelta
from decimal import Decimal

import store as S
from store import (
    parse_iso, now_dt, fmt_iso, fmt_date, day_floor, round_half_up_cents, touch,
    CHARGE_PRIORITY, PAYOFF_GOOD_THROUGH_DAYS, INTEREST_DAY_COUNT,
)


# --------------------------------------------------------------------------
# payment allocation waterfall
# --------------------------------------------------------------------------
def run_allocation(payment):
    account_id = payment["account_id"]
    candidates = [a for a in S.account_assessments(account_id)
                  if a["status"] in ("OPEN", "PARTIAL")]
    candidates.sort(key=lambda a: (
        CHARGE_PRIORITY[a["charge_type"]],
        parse_iso(a["due_date"]),
        a["_cdt"],
        a["_cseq"],
    ))
    remaining = payment["amount_cents"]
    allocations = []
    for a in candidates:
        if remaining <= 0:
            break
        applied = min(remaining, a["balance_cents"])
        if applied <= 0:
            continue
        allocations.append({"assessment_id": a["id"], "applied_cents": applied})
        a["balance_cents"] -= applied
        a["status"] = "PAID" if a["balance_cents"] == 0 else "PARTIAL"
        touch(a)
        remaining -= applied
    payment["allocations"] = allocations
    payment["unapplied_cents"] = remaining


def unapply_allocations(payment):
    """Restore assessment balances when a payment is reversed."""
    for alloc in payment["allocations"]:
        a = S.assessments.get(alloc["assessment_id"])
        if a is None:
            continue
        a["balance_cents"] += alloc["applied_cents"]
        if a["balance_cents"] >= a["amount_cents"]:
            a["balance_cents"] = a["amount_cents"]
            a["status"] = "OPEN"
        else:
            a["status"] = "PARTIAL"
        touch(a)


# --------------------------------------------------------------------------
# account status helpers
# --------------------------------------------------------------------------
def set_account_status(account, new_status):
    if account["status"] != new_status:
        account["status"] = new_status
    touch(account)


def on_balance_maybe_current(account, payment):
    """After allocation: if balance == 0, DELINQUENT/LIEN -> CURRENT."""
    if S.account_total_balance(account["id"]) != 0:
        return
    st = account["status"]
    if st == "DELINQUENT":
        set_account_status(account, "CURRENT")
        payment["_caused_current"] = True
    elif st == "LIEN":
        # release the RECORDED lien(s) on the account
        for l in S.account_liens(account["id"]):
            if l["status"] == "RECORDED":
                l["status"] = "RELEASED"
                touch(l)
        set_account_status(account, "CURRENT")
        payment["_caused_current"] = True


# --------------------------------------------------------------------------
# charge-off waiver
# --------------------------------------------------------------------------
def waive_open_assessments(account):
    for a in S.account_assessments(account["id"]):
        if a["status"] in ("OPEN", "PARTIAL"):
            a["balance_cents"] = 0
            a["status"] = "WAIVED"
            touch(a)


# --------------------------------------------------------------------------
# bankruptcy cascades
# --------------------------------------------------------------------------
def bankruptcy_filed_cascade(account):
    for l in S.account_liens(account["id"]):
        if l["status"] in ("RECORDED", "FORECLOSING"):
            l["status"] = "STAYED"
            touch(l)
    for r in S.account_referrals(account["id"]):
        if r["status"] in ("REFERRED", "FILED"):
            r["status"] = "STAYED"
            touch(r)
    for p in S.account_plans(account["id"]):
        if p["status"] == "ACTIVE":
            p["status"] = "SUSPENDED"
            touch(p)
    set_account_status(account, "BANKRUPTCY")


def bankruptcy_dismiss_cascade(account):
    for l in S.account_liens(account["id"]):
        if l["status"] == "STAYED":
            l["status"] = "RECORDED"
            touch(l)
    for r in S.account_referrals(account["id"]):
        if r["status"] == "STAYED":
            r["status"] = "REFERRED"
            touch(r)
    for p in S.account_plans(account["id"]):
        if p["status"] == "SUSPENDED":
            p["status"] = "ACTIVE"
            touch(p)
    set_account_status(account, "DELINQUENT")


def bankruptcy_discharge_cascade(account):
    waive_open_assessments(account)
    for l in S.account_liens(account["id"]):
        if l["status"] in ("STAYED", "RECORDED"):
            l["status"] = "RELEASED"
            touch(l)
    set_account_status(account, "CHARGED_OFF")


# --------------------------------------------------------------------------
# payoff quote
# --------------------------------------------------------------------------
def compute_payoff(account, association, variant):
    now = now_dt()
    if variant == "BINDING":
        T = now + timedelta(days=PAYOFF_GOOD_THROUGH_DAYS)
        good_through = T
    else:
        T = now
        good_through = now
    rate = Decimal(str(association["interest_rate_annual_pct"]))
    accrued = 0
    for a in S.account_assessments(account["id"]):
        if a["status"] not in ("OPEN", "PARTIAL"):
            continue
        if a["charge_type"] not in ("REGULAR", "SPECIAL"):
            continue
        days = max(0, day_floor(T, parse_iso(a["due_date"])))
        raw = (Decimal(a["balance_cents"]) * (rate / Decimal(100))
               * (Decimal(days) / Decimal(INTEREST_DAY_COUNT)))
        interest_a = round_half_up_cents(raw)
        interest_a = min(interest_a, a["balance_cents"])
        accrued += interest_a
    total_balance = S.account_total_balance(account["id"])
    return {
        "account_id": account["id"],
        "variant": variant,
        "quote_date": fmt_date(now),
        "good_through_date": fmt_date(good_through),
        "total_balance_cents": total_balance,
        "accrued_interest_cents": accrued,
        "payoff_amount_cents": total_balance + accrued,
    }


# --------------------------------------------------------------------------
# remittance amounts (dual variant)
# --------------------------------------------------------------------------
def compute_remittance_amounts(association, period_start, period_end, basis):
    ps = parse_iso(period_start)
    pe = parse_iso(period_end)
    acct_ids = {a["id"] for a in S.association_accounts(association["id"])}
    pool = []
    for p in S.payments.values():
        if p["account_id"] not in acct_ids:
            continue
        rd = parse_iso(p["received_date"])
        if ps <= rd <= pe:
            pool.append(p)
    if basis == "NET":
        included = [p for p in pool if p["status"] == "POSTED"]
    else:  # CASH: every payment ever posted in window (all were posted)
        included = pool
    gross = sum(p["amount_cents"] for p in included)
    fee_pct = Decimal(str(association["management_fee_pct"]))
    fee = 0
    for p in included:
        fee += round_half_up_cents(Decimal(p["amount_cents"]) * (fee_pct / Decimal(100)))
    return gross, fee, gross - fee


# --------------------------------------------------------------------------
# association-wide aging report
# --------------------------------------------------------------------------
def association_aging_report(association):
    accts = S.association_accounts(association["id"])
    agg = {
        "bucket_current": 0,
        "bucket_1_30": 0,
        "bucket_31_60": 0,
        "bucket_61_90": 0,
        "bucket_91_plus": 0,
    }
    for acc in accts:
        b = S.account_aging(acc["id"])
        for k in agg:
            agg[k] += b[k]
    total = sum(agg.values())
    return {
        "association_id": association["id"],
        "total_delinquent_cents": total,
        "bucket_current_cents": agg["bucket_current"],
        "bucket_1_30_cents": agg["bucket_1_30"],
        "bucket_31_60_cents": agg["bucket_31_60"],
        "bucket_61_90_cents": agg["bucket_61_90"],
        "bucket_91_plus_cents": agg["bucket_91_plus"],
        "account_count": len(accts),
    }


# --------------------------------------------------------------------------
# final due date helper
# --------------------------------------------------------------------------
def compute_final_due_date(first_due_date, num_installments):
    first = parse_iso(first_due_date)
    return fmt_date(first + timedelta(days=30 * (num_installments - 1)))
