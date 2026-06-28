"""Calculation rules (PRD §3.2, §3.6, §3.7; SCAFFOLD §1.3).

All monetary amounts are integer cents. Fractional cents are rounded round-half-up.
"""
from decimal import Decimal, ROUND_HALF_UP


def _round_half_up(value):
    """Round a Decimal to the nearest whole integer using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------------
# placement_band (PRD §3.2)
# ----------------------------------------------------------------------------
def placement_band(raw_score):
    if raw_score >= 90:
        return "C2"
    if raw_score >= 75:
        return "C1"
    if raw_score >= 60:
        return "B2"
    if raw_score >= 45:
        return "B1"
    if raw_score >= 25:
        return "A2"
    return "A1"


# ----------------------------------------------------------------------------
# addon_fee (PRD §3.6)
# ----------------------------------------------------------------------------
ADDON_RATES = {
    "CONVERSATION_CLUB": 1500,
    "PRIVATE_TUTORING": 6000,
    "IMMERSION_ABROAD": 40000,
}
IMMERSION_SURCHARGE_PCT = Decimal("0.15")
IMMERSION_FREE_WEEKS = 2


def addon_fee(add_on_type, units):
    rate = ADDON_RATES[add_on_type]
    base = rate * units
    if add_on_type == "IMMERSION_ABROAD":
        if units > IMMERSION_FREE_WEEKS:
            surcharge = _round_half_up(
                Decimal(rate) * Decimal(units - IMMERSION_FREE_WEEKS) * IMMERSION_SURCHARGE_PCT
            )
        else:
            surcharge = 0
        return base + surcharge
    return base


# ----------------------------------------------------------------------------
# tuition_invoice (PRD §3.6)
# ----------------------------------------------------------------------------
DISCOUNT_PCT = {
    "BRONZE": Decimal("0.00"),
    "SILVER": Decimal("0.10"),
    "GOLD": Decimal("0.20"),
}


def tuition_invoice(base_tuition_cents, active_addon_fees, discount_tier):
    """Pinned evaluation order (PRD §3.6).

    Step 1: add_on_total = sum of already-rounded ACTIVE add-on fee_cents.
    Step 2: gross = base_tuition_cents + add_on_total.
    Step 3: discount_pct from sponsoring contract's tier (0 for self-pay).
    Step 4: discount_cents = round_half_up(base_tuition_cents * discount_pct)  [base only].
    Step 5: tuition_invoice_cents = gross - discount_cents.
    """
    add_on_total = sum(active_addon_fees)
    gross = base_tuition_cents + add_on_total
    pct = DISCOUNT_PCT.get(discount_tier, Decimal("0.00")) if discount_tier else Decimal("0.00")
    discount_cents = _round_half_up(Decimal(base_tuition_cents) * pct)
    return gross - discount_cents


# ----------------------------------------------------------------------------
# withdrawal_refund (PRD §3.7) — chronological tiered schedule (authoritative)
# ----------------------------------------------------------------------------
def weeks_elapsed(current_dt, term_start_dt):
    """floor((current - term_start) / 7 days), whole weeks since term start."""
    delta_seconds = (current_dt - term_start_dt).total_seconds()
    if delta_seconds < 0:
        # Withdrawal before the term starts -> 0 whole weeks elapsed.
        return 0
    return int(delta_seconds // (7 * 24 * 3600))


def refund_fraction(weeks):
    if weeks == 0:
        return Decimal("1.00")
    if weeks == 1:
        return Decimal("0.75")
    if weeks in (2, 3):
        return Decimal("0.50")
    if weeks in (4, 5):
        return Decimal("0.25")
    return Decimal("0.00")


def withdrawal_refund(tuition_invoice_cents, current_dt, term_start_dt):
    weeks = weeks_elapsed(current_dt, term_start_dt)
    frac = refund_fraction(weeks)
    return _round_half_up(Decimal(tuition_invoice_cents) * frac)


# ----------------------------------------------------------------------------
# completion_score (PRD §3.7) — round-then-combine, pinned at three steps
# ----------------------------------------------------------------------------
def completion_score(latest_report, attendance_rate):
    skill_sum = (
        latest_report["speaking"]
        + latest_report["listening"]
        + latest_report["reading"]
        + latest_report["writing"]
    )
    skill_avg = _round_half_up(Decimal(skill_sum) / Decimal(4))
    attendance_pts = _round_half_up(Decimal(str(attendance_rate)) * Decimal(100))
    combined = Decimal("0.7") * Decimal(skill_avg) + Decimal("0.3") * Decimal(attendance_pts)
    return _round_half_up(combined)


# ----------------------------------------------------------------------------
# certification_rollup (PRD §3.7)
# ----------------------------------------------------------------------------
REQUIRED_COMPLETIONS = 2
CERT_PASS_SCORE = 70

# Completion-gate attendance floor (PRD §3.7).
MIN_PASS_ATTENDANCE = 0.70


def certification_rollup(completion_scores):
    """Returns (certification_status, final_progress_score).

    completion_scores: list of completion_score values for COMPLETED enrollments.
    """
    if not completion_scores:
        return ("NONE", None)
    mean = Decimal(sum(completion_scores)) / Decimal(len(completion_scores))
    final = _round_half_up(mean)
    count = len(completion_scores)
    if count >= REQUIRED_COMPLETIONS and final >= CERT_PASS_SCORE:
        return ("CERTIFIED", final)
    return ("PROVISIONAL", final)
