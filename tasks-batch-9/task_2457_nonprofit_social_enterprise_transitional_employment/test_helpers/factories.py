"""Request-payload factories.

Each factory returns a valid payload for one endpoint and accepts ``**overrides``
so a test can vary exactly the field under examination.
"""

from typing import Any, Dict, Optional

from .types import (
    AllocationBasis,
    CostClassification,
    MouTier,
    ReviewDecision,
    ScreeningDecision,
    SeparationType,
    SupportCategory,
    WageVerificationAction,
)
from .test_users import SUPERVISOR_USER_ID

# A candidate whose verified inputs score 91 raw points: three barriers (36),
# an FPL ratio of 0.5874 (35) and forty available hours (20).
STANDARD_BARRIER_CODES = [
    "JUSTICE_INVOLVED",
    "HOUSING_INSTABILITY",
    "LONG_TERM_UNEMPLOYED",
]


def business_line_payload(**overrides: Any) -> Dict[str, Any]:
    """A viable line: composite 82.75 with no dimension below 50."""
    payload = {
        "name": "Cafe & Catering",
        "market_viability_score": 90,
        "training_relevance_score": 80,
        "mission_alignment_score": 75,
        "training_slots_total": 3,
        "supervisor_capacity": 2,
        "target_gross_margin_pct": 0.2000,
        "subsidy_cap_cents": 5000000,
    }
    payload.update(overrides)
    return payload


def review_payload(
    decision: str = ReviewDecision.APPROVED, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def referral_partner_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "organization_name": "Eastside Works",
        "mou_tier": MouTier.TIER_1,
        "referral_quota_per_period": 5,
    }
    payload.update(overrides)
    return payload


def referral_payload(referral_partner_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "referral_partner_id": referral_partner_id,
        "candidate_reference": "CAND-001",
        "declared_barrier_codes": list(STANDARD_BARRIER_CODES),
        "household_income_cents": 100000,
        "household_size": 2,
        "hours_available_per_week": 40,
    }
    payload.update(overrides)
    return payload


def screening_payload(
    decision: str = ScreeningDecision.ELIGIBLE, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "verified_barrier_codes": list(STANDARD_BARRIER_CODES),
        "verified_household_income_cents": 100000,
        "verified_household_size": 2,
        "verified_hours_available_per_week": 40,
    }
    payload.update(overrides)
    return payload


def participant_payload(
    referral_id: str,
    business_line_id: str,
    expected_business_line_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "referral_id": referral_id,
        "business_line_id": business_line_id,
        "wage_cents_per_hour": 1650,
        "expected_business_line_version": expected_business_line_version,
    }
    payload.update(overrides)
    return payload


def re_entry_payload(wage_cents_per_hour: int = 1700, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"wage_cents_per_hour": wage_cents_per_hour}
    payload.update(overrides)
    return payload


def work_shift_payload(
    business_line_id: str,
    starts_at: str = "2026-09-07T08:00:00Z",
    ends_at: str = "2026-09-07T20:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "business_line_id": business_line_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "trainee_capacity": 2,
        "supervisor_user_id": SUPERVISOR_USER_ID,
    }
    payload.update(overrides)
    return payload


def shift_assignment_payload(
    work_shift_id: str, participant_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {"work_shift_id": work_shift_id, "participant_id": participant_id}
    payload.update(overrides)
    return payload


def completion_payload(actual_hours: float = 12.000, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"actual_hours": actual_hours}
    payload.update(overrides)
    return payload


def support_activity_payload(
    participant_id: str,
    category: str = SupportCategory.JOB_COACHING,
    duration_minutes: int = 90,
    cost_cents: int = 6000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "participant_id": participant_id,
        "category": category,
        "duration_minutes": duration_minutes,
        "cost_cents": cost_cents,
    }
    payload.update(overrides)
    return payload


def void_payload(
    voided_reason: str = "Session logged against the wrong participant", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"voided_reason": voided_reason}
    payload.update(overrides)
    return payload


def employer_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "organization_name": "Northgate Logistics",
        "industry_code": "LOG",
        "min_starting_wage_cents_per_hour": 1800,
    }
    payload.update(overrides)
    return payload


def placement_payload(
    participant_id: str,
    employer_id: str,
    hire_date: str = "2026-10-01T00:00:00Z",
    starting_wage_cents_per_hour: int = 1900,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "participant_id": participant_id,
        "employer_id": employer_id,
        "hire_date": hire_date,
        "starting_wage_cents_per_hour": starting_wage_cents_per_hour,
        "weekly_hours": 35,
    }
    payload.update(overrides)
    return payload


def wage_verification_payload(
    action: str = WageVerificationAction.VERIFY,
    verified_wage_cents_per_hour: Optional[int] = 1900,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if action == WageVerificationAction.VERIFY:
        payload["verified_wage_cents_per_hour"] = verified_wage_cents_per_hour
    payload.update(overrides)
    return payload


def separation_payload(
    separation_type: str = SeparationType.VOLUNTARY,
    separation_date: str = "2026-10-15T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "separation_type": separation_type,
        "separation_date": separation_date,
    }
    payload.update(overrides)
    return payload


def checkpoint_confirmation_payload(
    still_employed: bool = True,
    verified_wage_cents_per_hour: Optional[int] = 1900,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"still_employed": still_employed}
    if verified_wage_cents_per_hour is not None:
        payload["verified_wage_cents_per_hour"] = verified_wage_cents_per_hour
    payload.update(overrides)
    return payload


def subsidy_period_payload(
    business_line_id: str,
    period_start: str = "2026-09-01T00:00:00Z",
    period_end: str = "2026-09-30T00:00:00Z",
    supervisor_hours: float = 40.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "business_line_id": business_line_id,
        "period_start": period_start,
        "period_end": period_end,
        "supervisor_hours": supervisor_hours,
    }
    payload.update(overrides)
    return payload


def period_close_payload(
    allocation_basis: str = AllocationBasis.HOURS,
    revenue_cents: int = 500000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "allocation_basis": allocation_basis,
        "revenue_cents": revenue_cents,
    }
    payload.update(overrides)
    return payload


def cost_entry_payload(
    subsidy_period_id: str,
    expected_subsidy_period_version: int,
    category: str = "SUPERVISION",
    classification: str = CostClassification.SHARED,
    amount_cents: int = 300000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "subsidy_period_id": subsidy_period_id,
        "category": category,
        "classification": classification,
        "amount_cents": amount_cents,
        "expected_subsidy_period_version": expected_subsidy_period_version,
    }
    payload.update(overrides)
    return payload


def retention_sweep_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload
