"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted so
the implementation cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.6: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 format with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_offset(*, days: int = 0, hours: int = 0, minutes: int = 0,
               seconds: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
    ))


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp produced by iso_utc."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# ISO date helpers — for fields PRD declares as date-only or as a UTC
# wall-clock instant.
# ---------------------------------------------------------------------------
def iso_date(d: date) -> str:
    return d.isoformat()


def first_of_month(d: date) -> date:
    return date(d.year, d.month, 1)


def last_of_month(d: date) -> date:
    last_day = monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last_day)


def add_months(d: date, months: int) -> date:
    """Calendar month arithmetic preserving day-of-month where possible
    (clamping to last day of target month).
    """
    total = d.month - 1 + months
    new_year = d.year + total // 12
    new_month = total % 12 + 1
    last = monthrange(new_year, new_month)[1]
    return date(new_year, new_month, min(d.day, last))


def date_offset(*, days: int = 0, base: Optional[date] = None) -> date:
    base = base or datetime.now(tz=timezone.utc).date()
    return base + timedelta(days=days)


def iso_instant_utc(year: int, month: int, day: int, hour: int = 0,
                    minute: int = 0, second: int = 0) -> str:
    """Build an ISO 8601 UTC instant with .000Z millis."""
    return iso_utc(datetime(year, month, day, hour, minute, second,
                            tzinfo=timezone.utc))


def iso_day_end_utc(d: date) -> str:
    """Last second of `d` in UTC (23:59:59.000Z). PRD §3.1: iep_end_date
    is the last second of the month."""
    return iso_instant_utc(d.year, d.month, d.day, 23, 59, 59)


def iso_day_start_utc(d: date) -> str:
    """First instant of `d` in UTC (00:00:00.000Z)."""
    return iso_instant_utc(d.year, d.month, d.day, 0, 0, 0)


# ---------------------------------------------------------------------------
# Random-id helpers — PRD requires globally-unique medicare_id, plan_code.
# ---------------------------------------------------------------------------
_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


def random_medicare_id() -> str:
    """PRD §3.1: 'an externally issued Medicare Beneficiary Identifier,
    exactly eleven uppercase-alphanumeric characters, and must be unique
    across all beneficiaries'.
    """
    return random_suffix(11)


def random_plan_code(prefix: str = "PLN") -> str:
    """PRD §3.3: plan_code 1..40 chars, unique."""
    return f"{prefix}-{random_suffix(10)}"


def random_ndc() -> str:
    """National Drug Code. PRD §3.8: 'ndc_code (the National Drug Code)'.
    Free-form string suffices for testing.
    """
    return f"NDC-{random_suffix(9)}"


# ---------------------------------------------------------------------------
# Beneficiary — PRD §3.1
# ---------------------------------------------------------------------------
def create_beneficiary_payload(
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    medicare_id: Optional[str] = None,
    has_esrd: Optional[bool] = None,
    has_disability: Optional[bool] = None,
    ssdi_start_date: Optional[str] = None,
    state_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /beneficiaries — PlanAdmin only.

    PRD §3.1: required input fields are full_name, date_of_birth,
    medicare_id, state_code, and the eligibility-pathway flags has_esrd,
    has_disability, and (when disability applies) ssdi_start_date.
    has_esrd and has_disability default to false per Scaffold §1.1.

    medicare_id: PRD §3.1: 'exactly eleven uppercase-alphanumeric
    characters, and must be unique across all beneficiaries'.
    state_code: PRD §3.1: 'two-letter USPS abbreviation'.
    """
    payload: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"Beneficiary {random_suffix(4)}"
        ),
        "date_of_birth": date_of_birth or "1960-04-15",
        "medicare_id": medicare_id or random_medicare_id(),
        "state_code": state_code or TEST_DEFAULTS["STATE_CODE"],
    }
    if has_esrd is not None:
        payload["has_esrd"] = has_esrd
    if has_disability is not None:
        payload["has_disability"] = has_disability
    if ssdi_start_date is not None:
        payload["ssdi_start_date"] = ssdi_start_date
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Plan — PRD §3.3
# ---------------------------------------------------------------------------
def create_plan_payload(
    *,
    plan_code: Optional[str] = None,
    plan_type: str = "PART_C",
    plan_year: int = 2026,
    state_code: Optional[str] = None,
    monthly_premium_cents: int = 10_000,
    annual_deductible_cents: Optional[int] = None,
    initial_coverage_limit_cents: Optional[int] = None,
    catastrophic_threshold_cents: Optional[int] = None,
    star_rating: float = 4.0,
    is_active: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /plans — PlanAdmin.

    PRD §3.3: required input fields are plan_code (1..40 chars, unique),
    plan_type, plan_year (2020..2030), monthly_premium_cents,
    star_rating (half-star step 1.0..5.0). For Part D plans, the admin
    must also supply annual_deductible_cents, initial_coverage_limit_cents,
    and catastrophic_threshold_cents. Medigap plans carry state_code.
    is_active defaults to true.
    """
    payload: Dict[str, Any] = {
        "plan_code": plan_code or random_plan_code(),
        "plan_type": plan_type,
        "plan_year": plan_year,
        "monthly_premium_cents": monthly_premium_cents,
        "star_rating": star_rating,
    }
    if state_code is not None:
        payload["state_code"] = state_code
    if annual_deductible_cents is not None:
        payload["annual_deductible_cents"] = annual_deductible_cents
    if initial_coverage_limit_cents is not None:
        payload["initial_coverage_limit_cents"] = initial_coverage_limit_cents
    if catastrophic_threshold_cents is not None:
        payload["catastrophic_threshold_cents"] = (
            catastrophic_threshold_cents
        )
    if is_active is not None:
        payload["is_active"] = is_active
    payload.update(overrides)
    return payload


def create_part_d_plan_payload(
    *,
    plan_code: Optional[str] = None,
    plan_year: int = 2026,
    monthly_premium_cents: int = 4_000,
    annual_deductible_cents: int = 40_000,
    initial_coverage_limit_cents: int = 400_000,
    catastrophic_threshold_cents: int = 150_000,
    star_rating: float = 4.0,
    **overrides: Any,
) -> Dict[str, Any]:
    """Convenience: PART_D plan payload pre-loaded with the donut-hole
    thresholds PRD §3.8 names (D, I, C)."""
    return create_plan_payload(
        plan_code=plan_code, plan_type="PART_D", plan_year=plan_year,
        monthly_premium_cents=monthly_premium_cents,
        annual_deductible_cents=annual_deductible_cents,
        initial_coverage_limit_cents=initial_coverage_limit_cents,
        catastrophic_threshold_cents=catastrophic_threshold_cents,
        star_rating=star_rating, **overrides,
    )


def create_medigap_plan_payload(
    *,
    plan_code: Optional[str] = None,
    plan_year: int = 2026,
    state_code: str = "CA",
    monthly_premium_cents: int = 20_000,
    star_rating: float = 4.0,
    **overrides: Any,
) -> Dict[str, Any]:
    """Convenience: MEDIGAP plan payload. PRD §3.3: 'Medigap plans
    additionally carry a state_code'."""
    return create_plan_payload(
        plan_code=plan_code, plan_type="MEDIGAP", plan_year=plan_year,
        state_code=state_code,
        monthly_premium_cents=monthly_premium_cents,
        star_rating=star_rating, **overrides,
    )


def create_star_rating_payload(
    *,
    measurement_year: int = 2026,
    clinical_quality_score: float = 80.0,
    member_experience_score: float = 80.0,
    customer_service_score: float = 80.0,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /plans/{id}/star-ratings — PlanAdmin.

    PRD §3.3: required input fields are measurement_year (2020..2030)
    and three raw 0-to-100 sub-scores clinical_quality_score,
    member_experience_score, customer_service_score.
    """
    payload: Dict[str, Any] = {
        "measurement_year": measurement_year,
        "clinical_quality_score": clinical_quality_score,
        "member_experience_score": member_experience_score,
        "customer_service_score": customer_service_score,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# EnrollmentPeriod — PRD §3.2
# ---------------------------------------------------------------------------
def create_enrollment_period_payload(
    *,
    period_type: str = "AEP",
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /beneficiaries/{beneficiary_id}/enrollment-periods —
    PlanAdmin only.

    PRD §3.2: required input fields are period_type (one of AEP, GEP,
    SEP_MOVE, SEP_LOSS_OF_COVERAGE, MEDIGAP_GI), window_start, and
    window_end. window_end is inclusive — PRD §3.1 establishes the
    23:59:59 UTC inclusive convention for window_end.
    """
    payload: Dict[str, Any] = {"period_type": period_type}
    if window_start is not None:
        payload["window_start"] = window_start
    if window_end is not None:
        payload["window_end"] = window_end
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Enrollment — PRD §3.4
# ---------------------------------------------------------------------------
def create_enrollment_payload(
    *,
    beneficiary_id: str,
    plan_id: str,
    enrollment_period_id: str,
    effective_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /enrollments — BenefitsCounselor only.

    PRD §3.4: required input fields are beneficiary_id, plan_id,
    enrollment_period_id, and the proposed effective_date.
    """
    payload: Dict[str, Any] = {
        "beneficiary_id": beneficiary_id,
        "plan_id": plan_id,
        "enrollment_period_id": enrollment_period_id,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def terminate_enrollment_payload(
    *,
    termination_date: str,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /enrollments/{id}/terminate — BenefitsCounselor.

    PRD §3.9: required input is termination_date 'on or after
    effective_date and on or before the last day of the plan's
    plan_year'.
    """
    payload: Dict[str, Any] = {"termination_date": termination_date}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def transfer_enrollment_payload(
    *,
    new_plan_id: str,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /enrollments/{id}/transfer — BenefitsCounselor.

    PRD §3.9: 'a counselor supplies new_plan_id'.
    """
    payload: Dict[str, Any] = {"new_plan_id": new_plan_id}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def version_body(version: Optional[int]) -> Dict[str, Any]:
    """Build an action payload carrying an optional version field per
    PRD §2.7 OCC contract."""
    return {} if version is None else {"version": version}


# ---------------------------------------------------------------------------
# MedigapPolicy — PRD §3.7
# ---------------------------------------------------------------------------
def create_medigap_policy_payload(
    *,
    beneficiary_id: str,
    plan_id: str,
    underwriting_uplift_decimal: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /medigap-policies — BenefitsCounselor.

    PRD §3.7: required input fields are beneficiary_id and plan_id (of a
    MEDIGAP plan). underwriting_uplift_decimal is OPTIONAL and 'defaults
    to zero and is ignored on the guaranteed-issue branch'.
    """
    payload: Dict[str, Any] = {
        "beneficiary_id": beneficiary_id,
        "plan_id": plan_id,
    }
    if underwriting_uplift_decimal is not None:
        payload["underwriting_uplift_decimal"] = underwriting_uplift_decimal
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DrugClaim — PRD §3.8
# ---------------------------------------------------------------------------
def create_drug_claim_payload(
    *,
    beneficiary_id: str,
    enrollment_id: str,
    ndc_code: Optional[str] = None,
    tier: str = "TIER_3",
    fill_date: Optional[str] = None,
    gross_cost_cents: int = 5_000,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /drug-claims — BenefitsCounselor.

    PRD §3.8: required input fields are beneficiary_id, enrollment_id,
    ndc_code, tier (TIER_1..TIER_5), fill_date (date-only UTC), and
    gross_cost_cents (>= 1).
    """
    payload: Dict[str, Any] = {
        "beneficiary_id": beneficiary_id,
        "enrollment_id": enrollment_id,
        "ndc_code": ndc_code or random_ndc(),
        "tier": tier,
        "fill_date": fill_date or "2026-05-10",
        "gross_cost_cents": gross_cost_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock — PRD §3.2
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to: str, **overrides: Any) -> Dict[str, Any]:
    """POST /_clock/advance — PlanAdmin or Auditor.

    PRD §3.2: payload supplies a `to` instant.
    """
    payload: Dict[str, Any] = {"to": to}
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "parse_iso",
    "iso_date",
    "iso_instant_utc",
    "iso_day_end_utc",
    "iso_day_start_utc",
    "first_of_month",
    "last_of_month",
    "add_months",
    "date_offset",
    "random_suffix",
    "random_medicare_id",
    "random_plan_code",
    "random_ndc",
    "create_beneficiary_payload",
    "create_plan_payload",
    "create_part_d_plan_payload",
    "create_medigap_plan_payload",
    "create_star_rating_payload",
    "create_enrollment_period_payload",
    "create_enrollment_payload",
    "terminate_enrollment_payload",
    "transfer_enrollment_payload",
    "version_body",
    "create_medigap_policy_payload",
    "create_drug_claim_payload",
    "clock_advance_payload",
]
