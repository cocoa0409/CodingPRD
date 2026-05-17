"""Calculation helpers — sliding-fee, patient-responsibility, crisis composite, etc.

All monetary precision uses Decimal with ROUND_HALF_UP per SCAFFOLD §1.3.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

# ---------------- Sliding-fee tier (Patient) ---------------------------------

FPL_BASE_CENTS = {
    1: 1_497_000,
    2: 2_044_000,
    3: 2_591_000,
    4: 3_138_000,
}
FPL_INCREMENT_CENTS_PER_PERSON_OVER_4 = 547_000


def fpl_base_cents(household_size: int) -> int:
    """Federal-poverty-level base in cents for a given household size."""
    if household_size <= 4:
        return FPL_BASE_CENTS[household_size]
    return FPL_BASE_CENTS[4] + (household_size - 4) * FPL_INCREMENT_CENTS_PER_PERSON_OVER_4


def sliding_fee_tier_pct(household_income_cents: int, household_size: int) -> int:
    """Compute the sliding-fee tier percent (20|40|60|80|100) per SCAFFOLD §1.3 sliding_fee_tier.

    Brackets are left-open / right-closed except the first, which is closed-closed at the lower end.
    """
    base = fpl_base_cents(household_size)
    if household_income_cents <= 0:
        ratio = 0.0
    else:
        ratio = household_income_cents / base
    if ratio <= 1.00:
        return 20
    if ratio <= 1.50:
        return 40
    if ratio <= 2.00:
        return 60
    if ratio <= 2.50:
        return 80
    return 100


# ---------------- Sliding-fee charge (BillingClaim, SELF_PAY) ---------------

def round_half_up_to_cent(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def sliding_fee_charge_cents(rack_cents: int, tier_pct: int) -> int:
    """charged = rack * tier_pct / 100, rounded half-up to nearest cent."""
    val = Decimal(rack_cents) * Decimal(tier_pct) / Decimal(100)
    return round_half_up_to_cent(val)


# ---------------- Patient responsibility (INSURANCE_IN_NETWORK) -------------

def patient_responsibility_in_network(
    *,
    allowed_cents: int,
    contract_mode: str,
    copay_cents: int,
    deductible_remaining_cents: int,
) -> tuple[int, int, int]:
    """Return (charged, patient_responsibility, insurer_paid) for an IN_NETWORK claim."""
    charged = allowed_cents
    if contract_mode == "DEDUCTIBLE_FIRST":
        if deductible_remaining_cents > 0:
            patient = min(allowed_cents, deductible_remaining_cents)
            insurer = allowed_cents - patient
        else:
            patient = min(copay_cents, allowed_cents)
            insurer = allowed_cents - patient
    elif contract_mode == "COPAY_ONLY":
        patient = min(copay_cents, allowed_cents)
        insurer = allowed_cents - patient
    else:
        # defensive; create-time validation should have rejected
        raise ValueError(f"unknown contract_mode {contract_mode!r}")
    return charged, patient, insurer


# ---------------- Supervised-hour ledger arithmetic --------------------------

INDIVIDUAL_HOURS = Decimal("1.00")
INTAKE_HOURS = Decimal("1.50")
REQUIRED_HOURS_FOR_LICENSURE = Decimal("3000.00")


def round_half_up_2dp(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def supervision_credit_for_type(session_type: str) -> Decimal:
    return INTAKE_HOURS if session_type == "INTAKE" else INDIVIDUAL_HOURS


def compute_new_accrued(accrued: float | Decimal, delta: Decimal) -> Decimal:
    """Adds delta to accrued, rounded half-up to 2dp."""
    if isinstance(accrued, float):
        accrued_dec = Decimal(str(accrued))
    elif isinstance(accrued, int):
        accrued_dec = Decimal(accrued)
    elif isinstance(accrued, Decimal):
        accrued_dec = accrued
    else:
        accrued_dec = Decimal(str(accrued))
    return round_half_up_2dp(accrued_dec + delta)


def licensure_exam_eligible(accrued: Decimal | float, credential_status: str) -> bool:
    if isinstance(accrued, float):
        accrued_dec = Decimal(str(accrued))
    elif isinstance(accrued, int):
        accrued_dec = Decimal(accrued)
    elif isinstance(accrued, Decimal):
        accrued_dec = accrued
    else:
        accrued_dec = Decimal(str(accrued))
    return accrued_dec >= REQUIRED_HOURS_FOR_LICENSURE and credential_status in {"PROVISIONAL", "ACTIVE"}


# ---------------- Crisis composite score & bucket ---------------------------

CRISIS_WEIGHTS = {
    "si_score": Decimal("4.005"),
    "pa_score": Decimal("3.005"),
    "su_score": Decimal("2.005"),
    "so_score": Decimal("1.005"),
    "am_score": Decimal("2.505"),
}


def crisis_composite_score(
    si: int, pa: int, su: int, so: int, am: int
) -> Decimal:
    """Pinned order: round each factor*weight to 2 dp half-up, THEN sum, THEN round to 2 dp half-up."""
    pairs = [
        (si, CRISIS_WEIGHTS["si_score"]),
        (pa, CRISIS_WEIGHTS["pa_score"]),
        (su, CRISIS_WEIGHTS["su_score"]),
        (so, CRISIS_WEIGHTS["so_score"]),
        (am, CRISIS_WEIGHTS["am_score"]),
    ]
    per_factor = [round_half_up_2dp(Decimal(v) * w) for v, w in pairs]
    total = sum(per_factor, Decimal("0"))
    return round_half_up_2dp(total)


def crisis_risk_bucket(composite: Decimal) -> str:
    if composite >= Decimal("23.55"):
        return "HIGH"
    if composite >= Decimal("15.00"):
        return "MODERATE"
    return "LOW"


# ---------------- PSYPACT states ---------------------------------------------

PSYPACT_STATES = {
    "AL", "AR", "AZ", "CO", "CT", "DC", "DE", "FL", "GA", "IL",
    "KS", "KY", "ME", "MD", "MN", "NE", "NV", "NH", "NJ", "NC",
    "OH", "OK", "PA", "TN", "TX", "UT", "VA", "WA", "WV", "WI", "WY",
}


def is_psypact_state(code: str) -> bool:
    return code in PSYPACT_STATES


def decimal_to_2dp_float(x: Decimal) -> float:
    """Return a Python float representation rounded to 2dp (for JSON serialization)."""
    return float(round_half_up_2dp(x))


def to_decimal(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(str(x))
