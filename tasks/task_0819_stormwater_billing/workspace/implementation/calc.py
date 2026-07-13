"""Monetary/ERU calculations and derived-field reconciliation."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store


# ---------------------------------------------------------------------------
# Rounding (round half up, away from zero)
# ---------------------------------------------------------------------------
def _D(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def rhu_cents(value):
    return int(_D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_eru(value):
    return float(_D(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# ERU assessment (exemption applied to AREA first, then divide, then round)
# ---------------------------------------------------------------------------
def compute_billable_eru(impervious_area_sqft, exempt_pct):
    area_after = _D(impervious_area_sqft) * (Decimal("1") - _D(exempt_pct))
    eru_raw = area_after / _D(store.ERU_BASE_SQFT)
    return rhu_eru(eru_raw)


# ---------------------------------------------------------------------------
# Tiered stormwater fee (base fee, before fixed charge and credit)
# ---------------------------------------------------------------------------
def base_fee_marginal(eru):
    e = _D(eru)
    t1 = min(e, Decimal("1.0"))
    t2 = max(Decimal("0"), min(e, Decimal("5.0")) - Decimal("1.0"))
    t3 = max(Decimal("0"), e - Decimal("5.0"))
    total = t1 * store.RATE_T1 + t2 * store.RATE_T2 + t3 * store.RATE_T3
    return rhu_cents(total)


def base_fee_flat(eru):
    e = _D(eru)
    if e <= Decimal("1.0"):
        rate = store.RATE_T1
    elif e <= Decimal("5.0"):
        rate = store.RATE_T2
    else:
        rate = store.RATE_T3
    return rhu_cents(e * rate)


def base_fee_for_variant(eru, variant):
    if variant == "FLAT":
        return base_fee_flat(eru)
    return base_fee_marginal(eru)


def credit_amount_cents(base_fee_cents, credit_pct):
    if not credit_pct:
        return 0
    return rhu_cents(_D(base_fee_cents) * _D(credit_pct))


# ---------------------------------------------------------------------------
# BMP credit percentage from a score
# ---------------------------------------------------------------------------
def credit_pct_from_score(score):
    return min(store.MAX_CREDIT_PCT, (score / 100.0) * store.CREDIT_SCALE)


# ---------------------------------------------------------------------------
# Fund allocation split (round capital, operating = applied - capital)
# ---------------------------------------------------------------------------
def fund_split(applied_amount_cents):
    capital = rhu_cents(_D(applied_amount_cents) * _D(store.CAPITAL_TARGET_PCT))
    operating = applied_amount_cents - capital
    return capital, operating


# ---------------------------------------------------------------------------
# Delinquency penalty
# ---------------------------------------------------------------------------
def penalty_cents(assessed_fee_cents, amount_paid_cents):
    unpaid = assessed_fee_cents - amount_paid_cents
    if unpaid <= 0:
        return 0
    return rhu_cents(_D(unpaid) * _D(store.DELINQUENCY_PENALTY_PCT))


# ---------------------------------------------------------------------------
# Parcel active-credit percentage
# ---------------------------------------------------------------------------
def parcel_credit_pct(parcel_id):
    total = 0.0
    for c in store.bmp_credits.values():
        if c["parcel_id"] == parcel_id and c["status"] == "ACTIVE":
            total += c["credit_pct"]
    return total


# ---------------------------------------------------------------------------
# Derived-field reconciliation
# ---------------------------------------------------------------------------
def recompute_parcel(parcel):
    """Re-derive active measurement pointer, area, exemption, ERU, and fee.
    Does NOT bump version — callers bump per the transition that triggered it."""
    pid = parcel["id"]

    active = None
    for m in store.measurements.values():
        if m["parcel_id"] == pid and m["status"] == "ACTIVE":
            active = m
            break
    if active is not None:
        parcel["active_measurement_id"] = active["id"]
        parcel["impervious_area_sqft"] = active["measured_sqft"]
        parcel["status"] = "ACTIVE"
    else:
        parcel["active_measurement_id"] = None
        parcel["impervious_area_sqft"] = 0

    exempt = 0.0
    for e in store.exemptions.values():
        if e["parcel_id"] == pid and e["status"] == "GRANTED":
            exempt = e["granted_pct"]
            break
    parcel["exempt_pct"] = exempt

    parcel["billable_eru"] = compute_billable_eru(
        parcel["impervious_area_sqft"], parcel["exempt_pct"]
    )

    # Live MARGINAL-variant fee for the parcel's current state: the tiered
    # creditable fee net of any active credit. A parcel with no measurement
    # (ERU 0) therefore has a fee of 0 -- "no fee until measured" (PRD 3.1).
    # The per-bill fixed administrative charge is NOT part of this parcel-level
    # figure; it is added only when a bill is issued.
    credit_pct = parcel_credit_pct(pid)
    eru = parcel["billable_eru"]
    base = base_fee_marginal(eru)
    credit_amt = credit_amount_cents(base, credit_pct)
    parcel["current_fee_cents"] = base - credit_amt


def account_outstanding(account_id):
    total = 0
    for b in store.bills.values():
        if b["account_id"] == account_id and b["status"] != "VOID":
            total += b["net_fee_cents"] - b["amount_paid_cents"]
    return total


def account_delinquency(account_id):
    """Derived from the logical clock and this account's unpaid, non-VOID bills."""
    clock = store.get_clock()
    grace = timedelta(days=store.GRACE_DAYS)
    delinquent = False
    past_due = False
    for b in store.bills.values():
        if b["account_id"] != account_id or b["status"] == "VOID":
            continue
        if b["net_fee_cents"] - b["amount_paid_cents"] <= 0:
            continue
        try:
            due = store.parse_dt(b["due_date"])
        except ValueError:
            continue
        if clock >= due + grace:
            delinquent = True
        elif clock > due:
            past_due = True
    if delinquent:
        return "DELINQUENT"
    if past_due:
        return "PAST_DUE"
    return "CURRENT"


def recompute_account(account, touch_delinquency=True):
    account["outstanding_balance_cents"] = account_outstanding(account["id"])
    if touch_delinquency:
        account["delinquency_status"] = account_delinquency(account["id"])
