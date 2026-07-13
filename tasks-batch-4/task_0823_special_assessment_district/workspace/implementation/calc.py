"""Pure calculation routines: apportionment, amortization, payoff, delinquency."""
from fractions import Fraction

from util import rhu, ffloor, to_fraction, add_years, days_30_360

GRACE_DAYS = 30
DELINQUENCY_PENALTY_PCT = Fraction(1, 10)          # 0.10
DELINQUENCY_MONTHLY_INTEREST_PCT = Fraction(15, 1000)  # 0.015
QUOTE_VALIDITY_DAYS = 30
DAY_COUNT_BASIS = 360
FORECLOSURE_DELINQUENT_THRESHOLD = 3


def weight_of(parcel, method):
    if method == "BENEFIT_UNITS":
        return parcel.get("benefit_units") or 0
    if method == "LAND_AREA":
        return parcel.get("land_area_sqft") or 0
    if method == "FRONT_FOOTAGE":
        return parcel.get("front_footage_ft") or 0
    return 0


def waterfall(total_cents, entries):
    """Floor-then-distribute allocation.

    `entries` is a list of dicts each with keys: id, weight, seq.
    Returns {id: cents}. Shares sum exactly to total_cents (when denom > 0).
    """
    result = {e["id"]: 0 for e in entries}
    denom = sum(to_fraction(e["weight"]) for e in entries)
    if denom == 0 or total_cents == 0:
        return result
    floors = {}
    for e in entries:
        raw = to_fraction(total_cents) * to_fraction(e["weight"]) / denom
        floors[e["id"]] = ffloor(raw)
    remainder = total_cents - sum(floors.values())
    # order by weight DESC, then created seq ASC (stable)
    order = sorted(entries, key=lambda e: e["seq"])
    order = sorted(order, key=lambda e: to_fraction(e["weight"]), reverse=True)
    for e in order[:remainder]:
        floors[e["id"]] += 1
    return floors


def amortize(p0, coupon_rate_bps, term_years, admin_fee_bps, issuance_date):
    """Level debt-service amortization. Returns list of per-year dicts."""
    r = Fraction(coupon_rate_bps, 10000)
    n = term_years
    admin_r = Fraction(admin_fee_bps, 10000)
    if r == 0:
        # No interest: level principal distributed, final year absorbs drift.
        level_ds = rhu(Fraction(p0, n)) if n else 0
    else:
        factor = (1 + r) ** (-n)  # (1+r)^(-n) exact Fraction
        level_ds = rhu(to_fraction(p0) * r / (1 - factor))
    schedule = []
    outstanding = p0
    for k in range(1, n + 1):
        interest_k = rhu(to_fraction(outstanding) * r)
        admin_k = rhu(to_fraction(outstanding) * admin_r)
        if k < n:
            principal_k = level_ds - interest_k
        else:
            principal_k = outstanding
        amount_due_k = principal_k + interest_k + admin_k
        schedule.append({
            "installment_year": k,
            "due_date": add_years(issuance_date, k),
            "principal_cents": principal_k,
            "interest_cents": interest_k,
            "admin_fee_cents": admin_k,
            "amount_due_cents": amount_due_k,
        })
        outstanding -= principal_k
    return schedule


def payoff_figures(rem, bond, total_apportioned_principal_cents, quote_mode, quote_date):
    r = Fraction(bond["coupon_rate_bps"], 10000)
    premium = rhu(to_fraction(rem) * to_fraction(bond["prepayment_premium_pct"]))
    if total_apportioned_principal_cents and total_apportioned_principal_cents != 0:
        reserve_credit = rhu(
            to_fraction(rem) / to_fraction(total_apportioned_principal_cents)
            * to_fraction(bond["reserve_fund_cents"])
        )
    else:
        reserve_credit = 0
    if quote_mode == "IMMEDIATE":
        days = days_30_360(bond["issuance_date"], quote_date)
        accrued = rhu(to_fraction(rem) * r * Fraction(days) / DAY_COUNT_BASIS)
    else:  # NEXT_CALL_DATE
        accrued = rhu(to_fraction(rem) * r)
    total = rem + accrued + premium - reserve_credit
    return {
        "remaining_principal_cents": rem,
        "accrued_interest_cents": accrued,
        "prepayment_premium_cents": premium,
        "reserve_credit_cents": reserve_credit,
        "total_payoff_cents": total,
    }


def delinquency_charges(base, due_date, clock):
    penalty = rhu(to_fraction(base) * DELINQUENCY_PENALTY_PCT)
    months_late = days_30_360(due_date, clock) // 30
    if months_late < 0:
        months_late = 0
    redemption = rhu(to_fraction(base) * DELINQUENCY_MONTHLY_INTEREST_PCT * months_late)
    return penalty, redemption
