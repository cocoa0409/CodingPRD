"""Calculation rules (scaffold §1.3).

All algorithms read inputs from already-validated upstream data — no I/O.
Precision-sensitive math uses Decimal with ROUND_HALF_UP per scaffold.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from typing import Dict, Any, Optional, List


# Constants pinned by scaffold §1.3
BASE_FEE_CENTS = {
    "I-130": 56000,
    "I-485": 142000,
    "I-765": 41000,
    "I-131": 63000,
}
BIOMETRICS_SURCHARGE_CENTS = 8500
CHILD_DISCOUNT_PCT = Decimal("0.25")
BIOMETRICS_REQUIRED = {"I-485", "I-765", "I-131"}

DEADLINE_DAYS = 87
MAX_RFE_ROUNDS = 2

STATUS_WEIGHTS = {
    "FILED": 1,
    "BIOMETRICS_SCHEDULED": 2,
    "BIOMETRICS_COMPLETED": 3,
    "UNDER_REVIEW": 4,
    "RFE_PENDING": 2,
    "INTERVIEW_SCHEDULED": 5,
    "INTERVIEW_COMPLETED": 5,
}
MULTIPLIER_CAP = Decimal("1.0")
MULTIPLIER_DAYS_PER_UNIT = 365

TERMINAL_CASE_STATES = {"APPROVED", "DENIED", "ABANDONED"}


def round_half_up_cents(value: Decimal) -> int:
    """Round a Decimal value to whole cents using ROUND_HALF_UP, return int."""
    quantized = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(quantized)


def compute_filing_fee_cents(case_type: str, is_under_14: bool) -> int:
    """Scaffold §1.3.filing_fee.

    Step 1: base = BASE_FEE_CENTS[case_type]
    Step 2: surcharge = BIOMETRICS_SURCHARGE_CENTS iff case_type in {I-485,I-765,I-131}
    Step 3: if I-485 and is_under_14: apply 25% discount, round_half_up ONCE
            (after multiplication, not per-component)
    """
    base = BASE_FEE_CENTS[case_type]
    surcharge = BIOMETRICS_SURCHARGE_CENTS if case_type in BIOMETRICS_REQUIRED else 0
    pre_discount = base + surcharge
    if case_type == "I-485" and is_under_14:
        # Apply discount to the SUBTOTAL first, then round-half-up to whole cents.
        discounted = Decimal(pre_discount) * (Decimal("1") - CHILD_DISCOUNT_PCT)
        return round_half_up_cents(discounted)
    return pre_discount


def compute_rfe_deadline(issued_at_iso: str) -> str:
    """Scaffold §1.3.rfe_deadline.

    Add 87 calendar days to the calendar-date portion of issued_at,
    return ISO YYYY-MM-DD.
    """
    issued_date = date.fromisoformat(issued_at_iso[:10])
    deadline = issued_date + timedelta(days=DEADLINE_DAYS)
    return deadline.isoformat()


def compute_is_under_14(date_of_birth_iso: str, reference_date_iso: str) -> bool:
    """True iff age in completed years at reference_date is strictly less than 14."""
    dob = date.fromisoformat(date_of_birth_iso[:10])
    ref = date.fromisoformat(reference_date_iso[:10])
    # Age in completed years.
    years = ref.year - dob.year - (1 if (ref.month, ref.day) < (dob.month, dob.day) else 0)
    return years < 14


def evaluate_visa_availability(
    priority_date_iso: str,
    preference_category: str,
    country: str,
    chart_type: str,
    evaluation_month: str,
    visa_bulletin_store: Dict[str, Dict[str, Any]],
) -> str:
    """Scaffold §1.3.visa_availability.

    Step 1: evaluation_month is the YYYY-MM caller computed from clock.
    Step 2: find entry matching (category, country, chart_type, month).
    Step 3: empty-set fallback — most-recent-prior month by lexicographic max.
    Step 4: comparison — 'CURRENT' literal => CURRENT; else strict priority_date < cutoff_date.

    Returns 'CURRENT' or 'RETROGRESSED'.
    """
    # Filter to entries matching category/country/chart_type
    matching = [
        e for e in visa_bulletin_store.values()
        if e.get("preference_category") == preference_category
        and e.get("country") == country
        and e.get("chart_type") == chart_type
    ]

    # Try the exact month first.
    exact = [e for e in matching if e.get("bulletin_month") == evaluation_month]
    if exact:
        entry = exact[0]
    else:
        # Fall back to most-recent prior month (lex max where month < evaluation_month).
        prior = [e for e in matching if e.get("bulletin_month", "") < evaluation_month]
        if not prior:
            return "RETROGRESSED"
        prior.sort(key=lambda e: e.get("bulletin_month", ""), reverse=True)
        entry = prior[0]

    cutoff = entry.get("cutoff_date")
    if cutoff == "CURRENT":
        return "CURRENT"
    # Strict less-than: priority_date < cutoff_date => CURRENT; equality => RETROGRESSED.
    if priority_date_iso[:10] < cutoff[:10]:
        return "CURRENT"
    return "RETROGRESSED"


def compute_officer_workload(
    officer_id: str,
    cases_store: Dict[str, Dict[str, Any]],
    current_utc_iso: str,
) -> Dict[str, Any]:
    """Scaffold §1.3.officer_workload_score.

    Two variants from the same pool:
      VARIANT A (workload_score): sum(weight * multiplier), rounded ONCE to 2dp half-up.
      VARIANT B (case_count): len(pool).
    """
    current_date = date.fromisoformat(current_utc_iso[:10])
    pool = [
        c for c in cases_store.values()
        if c.get("assigned_officer_id") == officer_id
        and c.get("status") not in TERMINAL_CASE_STATES
    ]

    total = Decimal("0")
    for c in pool:
        status = c.get("status")
        weight = STATUS_WEIGHTS.get(status, 0)
        file_date_iso = c.get("file_date")
        if not file_date_iso:
            age_days = 0
        else:
            file_d = date.fromisoformat(file_date_iso[:10])
            age_days = max(0, (current_date - file_d).days)
        age_factor = Decimal(age_days) / Decimal(MULTIPLIER_DAYS_PER_UNIT)
        capped = min(age_factor, MULTIPLIER_CAP)
        multiplier = Decimal("1") + capped
        total += Decimal(weight) * multiplier

    # Apply rounding ONCE to the final sum.
    workload_score = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Convert to float for JSON (preserves the two-decimal precision; test rigs
    # generally accept either string or numeric).
    return {
        "officer_id": officer_id,
        "workload_score": float(workload_score),
        "case_count": len(pool),
    }
