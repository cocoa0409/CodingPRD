"""Calculation rules (SCAFFOLD §1.3 / PRD §3.2, §3.8, §3.9).

All monetary amounts are integer cents. Where a fraction of an amount is taken
(coinsurance) we use Decimal with ROUND_HALF_UP. Unit*rate products are exact.
"""
import math
from decimal import Decimal, ROUND_HALF_UP


# ---- diagnostic_severity (PRD §3.2) ----
# assessment_score in [0,180]; tiered, inclusive lower-bound (>=) thresholds.
SEVERE_FLOOR = 120
MODERATE_FLOOR = 60
SEVERE_WEEKLY_UNITS = 160
MODERATE_WEEKLY_UNITS = 100
MILD_WEEKLY_UNITS = 40


def diagnostic_severity(assessment_score):
    """Return (severity_level, recommended_weekly_units)."""
    if assessment_score >= SEVERE_FLOOR:
        return "SEVERE", SEVERE_WEEKLY_UNITS
    if assessment_score >= MODERATE_FLOOR:
        return "MODERATE", MODERATE_WEEKLY_UNITS
    return "MILD", MILD_WEEKLY_UNITS


# ---- supervision_ratio (PRD §3.8) ----
def required_supervision_units(delivered_direct_units, supervision_ratio_pct):
    """ceil(delivered_direct_units * supervision_ratio_pct)."""
    # Compute the product exactly with Decimal, then ceil to a whole unit.
    product = Decimal(str(delivered_direct_units)) * Decimal(str(supervision_ratio_pct))
    return int(math.ceil(product))


def supervision_status(delivered_direct_units, delivered_supervision_units,
                       supervision_ratio_pct):
    """COMPLIANT iff delivered_supervision_units >= required (inclusive >=)."""
    required = required_supervision_units(delivered_direct_units, supervision_ratio_pct)
    if delivered_supervision_units >= required:
        return "COMPLIANT"
    return "DEFICIENT"


# ---- claim_billed (PRD §3.9) ----
SERVICE_LINE_RATE_CENTS = {
    "DIRECT_THERAPY": 3200,
    "SUPERVISION": 4800,
    "PARENT_TRAINING": 2400,
}


def provisional_billed_cents(service_line, scheduled_units):
    """Provisional: bill the scheduled (reserved) units. Exact integer cents."""
    return scheduled_units * SERVICE_LINE_RATE_CENTS[service_line]


def final_billed_cents(service_line, delivered_units):
    """Final (at SUBMITTED): bill the actually delivered units."""
    return delivered_units * SERVICE_LINE_RATE_CENTS[service_line]


# ---- claim_remittance (PRD §2.8 / §3.9) ----
def remittance(delivered_units, allowed_rate_cents, coinsurance_pct):
    """Return (allowed_cents, patient_responsibility_cents, payer_paid_cents).

    allowed_cents = delivered_units * allowed_rate_cents (exact).
    patient_responsibility_cents = round_half_up(allowed_cents * coinsurance_pct).
    payer_paid_cents = allowed_cents - patient_responsibility_cents (the
    remainder, so the two always sum back to allowed_cents).
    """
    allowed_cents = delivered_units * allowed_rate_cents
    patient = Decimal(str(allowed_cents)) * Decimal(str(coinsurance_pct))
    patient_cents = int(patient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    payer_paid_cents = allowed_cents - patient_cents
    return allowed_cents, patient_cents, payer_paid_cents
