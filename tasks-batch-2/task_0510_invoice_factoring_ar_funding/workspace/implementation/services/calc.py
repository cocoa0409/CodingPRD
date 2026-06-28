"""Calculation rules (§1.3 / PRD §2.7-§2.10, §3.6-§3.7).

All money is integer cents; rounding is round-half-up per the precision notes.
Fee rates and multipliers preserve their input precision (used via Decimal).
"""

import math
from decimal import Decimal

import db
from common import round_half_up

DAY_SECONDS = 86400

# Invoice statuses that contribute to denormalized balances.
EXPOSURE_STATUSES = {"FUNDED", "OUTSTANDING", "SHORT_PAID"}


def _elapsed_days(start_dt, end_dt):
    """floor((end - start) / DAY_SECONDS), never less than zero."""
    delta = (end_dt - start_dt).total_seconds()
    days = math.floor(delta / DAY_SECONDS)
    return max(0, days)


# --- advance_split ---------------------------------------------------------
def advance_split(face_amount_cents, advance_rate_pct):
    """Returns (advance_amount_cents, reserve_held_cents)."""
    advance = round_half_up(Decimal(str(face_amount_cents)) * Decimal(str(advance_rate_pct)))
    reserve = face_amount_cents - advance
    return advance, reserve


# --- factoring_fee ---------------------------------------------------------
def provisional_fee(invoice):
    """Flat per-diem accrual to the current logical clock; floored at 0 days."""
    funded_at = invoice.get("funded_at")
    if not funded_at:
        return 0
    funded_dt = db.parse_iso(funded_at)
    days = _elapsed_days(funded_dt, db.clock_now())
    face = Decimal(str(invoice["face_amount_cents"]))
    rate = Decimal(str(invoice["fee_rate_per_day"]))
    return round_half_up(face * rate * Decimal(days))


def final_fee(invoice, program, cutoff_dt):
    """Tiered escalating per-diem, round-per-tier-then-sum (pinned order)."""
    funded_at = invoice.get("funded_at")
    if not funded_at:
        return 0
    funded_dt = db.parse_iso(funded_at)
    days = _elapsed_days(funded_dt, cutoff_dt)
    d1 = min(days, 30)
    d2 = min(max(days - 30, 0), 30)
    d3 = max(days - 60, 0)
    face = Decimal(str(invoice["face_amount_cents"]))
    rate = Decimal(str(invoice["fee_rate_per_day"]))
    t2 = Decimal(str(program["tier2_multiplier"]))
    t3 = Decimal(str(program["tier3_multiplier"]))
    f1 = round_half_up(face * rate * Decimal(d1))
    f2 = round_half_up(face * rate * t2 * Decimal(d2))
    f3 = round_half_up(face * rate * t3 * Decimal(d3))
    return f1 + f2 + f3


# --- aging_bucket ----------------------------------------------------------
def aging_bucket(invoice):
    due = invoice.get("due_date")
    if not due:
        return "CURRENT"
    due_dt = db.parse_iso(due)
    delta = (db.clock_now() - due_dt).total_seconds()
    dpd = math.floor(delta / DAY_SECONDS)
    if dpd <= 0:
        return "CURRENT"
    if dpd <= 30:
        return "DPD_1_30"
    if dpd <= 60:
        return "DPD_31_60"
    if dpd <= 90:
        return "DPD_61_90"
    return "DPD_90_PLUS"


# --- settlement_rebate (waterfall) -----------------------------------------
def settlement_waterfall(collected, advance_amount, fee_amount):
    """Returns dict with principal_applied, fee_applied, rebate, fee_shortfall."""
    remaining = collected
    principal_applied = min(remaining, advance_amount)
    remaining -= principal_applied
    fee_applied = min(remaining, fee_amount)
    remaining -= fee_applied
    rebate = max(0, remaining)
    fee_shortfall = fee_amount - fee_applied
    return {
        "principal_applied_cents": principal_applied,
        "fee_applied_cents": fee_applied,
        "rebate_cents": rebate,
        "fee_shortfall_cents": fee_shortfall,
    }


# --- collected-total over POSTED postings ----------------------------------
def amount_collected(invoice_id):
    total = 0
    for p in db.collection_postings.values():
        if p["invoice_id"] == invoice_id and p["status"] == "POSTED":
            total += p["amount_cents"]
    return total


def dilution_cents(invoice_id):
    total = 0
    for a in db.adjustments.values():
        if a["invoice_id"] == invoice_id and a["type"] in ("DILUTION", "CREDIT_MEMO"):
            total += a["amount_cents"]
    return total


def concentration_breached(debtor_face_before, candidate_face, portfolio_before,
                           limit):
    """Exact-integer concentration test.

    The candidate is included in the portfolio denominator (per PRD §2.10). The
    debtor exposure numerator is the debtor's prospective face. Rejection uses
    strict '>' (boundary '==' allowed) via cross-multiplication on integers so
    no float division is performed.

    Returns True when funding must be rejected with ERR_CONCENTRATION_EXCEEDED.
    """
    from fractions import Fraction
    debtor_exposure_after = debtor_face_before + candidate_face
    portfolio_after = portfolio_before + candidate_face
    # A debtor that constitutes the entire client portfolio (single-debtor
    # funding) is never rejected on its own first exposure: the concentration
    # ceiling only constrains a debtor's share relative to OTHER debtors.
    if debtor_face_before == portfolio_before:
        return False
    lim = Fraction(str(limit))
    return debtor_exposure_after * lim.denominator > lim.numerator * portfolio_after


def latest_posted_received_at(invoice_id):
    """Latest POSTED CollectionPosting.received_at as a datetime, or None."""
    best = None
    for p in db.collection_postings.values():
        if p["invoice_id"] == invoice_id and p["status"] == "POSTED":
            dt = db.parse_iso(p["received_at"])
            if best is None or dt > best:
                best = dt
    return best
