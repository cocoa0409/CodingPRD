"""Monetary and rate calculations.

All cent amounts are integers; rounding is round-half-up (PRD §2.7). The CIRR
placement rate is the only non-cent quantity: a fraction rounded to 4 decimals,
also round-half-up. Rounding order within each multi-step calc is pinned per the
calculation narratives in PRD §3.
"""
from decimal import Decimal, ROUND_HALF_UP

# refund constants (SCAFFOLD calc refund_amount)
WITHDRAWAL_RETENTION = Decimal("0.10")
TUITION_PRORATION_WEIGHT = Decimal("0.50")
ADMIN_FEE_PCT = Decimal("0.05")

CIRR_WINDOW_DAYS = 180


def round_half_up_cents(value):
    """Round a Decimal/number to the nearest whole cent, half-up. Returns int."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4(value):
    """Round to 4 decimal places, half-up. Returns float."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    q = d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


# --- monthly_payment_amount (PRD §3.8) -----------------------------------------

def monthly_obligation(contract, gross_income_cents):
    """Obligation for one income period. Evaluation order is pinned.

    1. DEFERRED contract -> 0
    2. gross_income <= income_threshold (inclusive floor) -> 0
    3. payments_made_count >= term_months -> 0
    4. raw = round_half_up(gross_income * income_share_pct); clamp to remaining_cap
    """
    if contract["status"] == "DEFERRED":
        return 0
    if gross_income_cents <= contract["income_threshold_cents"]:
        return 0
    if contract["_payments_made_count"] >= contract["term_months"]:
        return 0
    raw = round_half_up_cents(Decimal(gross_income_cents) * Decimal(str(contract["income_share_pct"])))
    remaining = contract["_remaining_cap_cents"]
    return min(raw, remaining)


# --- isa_payoff_projection (PRD §3.11) -----------------------------------------

def projected_payoff(contract, latest_income_report):
    """Forward-looking projection assuming latest income repeats every month."""
    amount_paid = contract["_amount_paid_cents"]
    if latest_income_report is None or contract["status"] in ("COMPLETED", "SETTLED_TERM", "VOIDED"):
        return amount_paid
    share = round_half_up_cents(
        Decimal(latest_income_report["gross_income_cents"]) * Decimal(str(contract["income_share_pct"]))
    )
    per_month = max(0, min(share, contract["cap_cents"]))
    months_left = contract["term_months"] - contract["_payments_made_count"]
    if months_left < 0:
        months_left = 0
    return min(contract["cap_cents"], amount_paid + per_month * months_left)


# --- refund_amount (PRD §3.6) --------------------------------------------------

def refund_amounts(reason, deposit_amount_cents, tuition_sticker_cents, progress_pct):
    """Per-line round, then sum, then deduct rounded admin fee. Order pinned."""
    if reason == "COOLING_OFF":
        deposit_line = deposit_amount_cents
    else:
        deposit_line = round_half_up_cents(
            Decimal(deposit_amount_cents) * (Decimal("1") - WITHDRAWAL_RETENTION)
        )

    if reason == "COOLING_OFF":
        tuition_line = 0
    else:
        unconsumed = Decimal("1") - (Decimal(str(progress_pct)) / Decimal("100"))
        tuition_line = round_half_up_cents(
            Decimal(tuition_sticker_cents) * unconsumed * TUITION_PRORATION_WEIGHT
        )

    gross = deposit_line + tuition_line
    admin_fee = round_half_up_cents(Decimal(gross) * ADMIN_FEE_PCT)
    net = gross - admin_fee
    return gross, net


# --- cirr_eligibility (PRD §3.12) ----------------------------------------------

COUNTABLE_CATEGORIES = {"EMPLOYED_IN_FIELD", "EMPLOYED_OUT_OF_FIELD", "SELF_EMPLOYED"}


def cirr_eligible(category, placement_days):
    countable = category in COUNTABLE_CATEGORIES
    within_window = placement_days is not None and placement_days <= CIRR_WINDOW_DAYS
    return countable and within_window


# --- cirr_placement_rate (PRD §3.12) -------------------------------------------

def placement_rate(placed_count, denom):
    if denom == 0:
        return 0.0
    return round_half_up_4(Decimal(placed_count) / Decimal(denom))
