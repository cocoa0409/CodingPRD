"""Calculation rules (SCAFFOLD.yaml Table 3 / PRD §3.9-§3.13).

All monetary amounts are integer cents. The only fractional intermediate is the
volume discount, rounded half-up exactly once.
"""

from decimal import Decimal, ROUND_HALF_UP


# --- OSHA recordability (§3.10) ---------------------------------------------

def osha_recordability(treatment_level, days_away, days_restricted):
    """Return (is_osha_recordable, osha_column). First match wins, fixed order."""
    days_away = days_away or 0
    days_restricted = days_restricted or 0

    if treatment_level == "FATALITY":
        return True, "DEATH"
    if days_away >= 1:
        return True, "DAYS_AWAY"
    if days_restricted >= 1 or treatment_level == "RESTRICTED_DUTY":
        return True, "RESTRICTED_TRANSFER"
    if treatment_level == "MEDICAL_TREATMENT":
        return True, "OTHER_RECORDABLE"
    if treatment_level == "LOST_TIME" and days_away == 0:
        return True, "OTHER_RECORDABLE"
    # remaining: FIRST_AID
    return False, "NOT_RECORDABLE"


# --- Surveillance outcome (§3.12) -------------------------------------------

STS_THRESHOLD_DB = 10
HALF_MASK_MIN_FF = 100
FULL_FACEPIECE_MIN_FF = 500


def surveillance_outcome(exam_kind, baseline_db, current_db, fit_factor, respirator_class):
    if exam_kind == "AUDIOMETRIC":
        shift = current_db - baseline_db
        if shift >= STS_THRESHOLD_DB:
            return "STS"
        return "PASS"
    # RESPIRATOR_FIT
    required = HALF_MASK_MIN_FF if respirator_class == "HALF_MASK" else FULL_FACEPIECE_MIN_FF
    if fit_factor >= required:
        return "PASS"
    return "FAIL"


# --- Invoice volume discount / total (§3.13) --------------------------------

TIER1_MIN = 5
TIER1_RATE = Decimal("0.05")
TIER2_MIN = 10
TIER2_RATE = Decimal("0.10")


def invoice_discount_rate(line_count):
    if line_count >= TIER2_MIN:
        return TIER2_RATE
    if line_count >= TIER1_MIN:
        return TIER1_RATE
    return Decimal("0.00")


def invoice_totals(subtotal_cents, line_count):
    """Return (discount_cents, total_cents). Round the discount once, half-up."""
    rate = invoice_discount_rate(line_count)
    if rate == 0:
        discount_cents = 0
    else:
        raw = Decimal(subtotal_cents) * rate
        discount_cents = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    total_cents = subtotal_cents - discount_cents
    if total_cents < 0:
        total_cents = 0
    return discount_cents, total_cents
