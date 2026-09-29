"""Payload builders with valid defaults; keyword overrides for every field."""
from typing import Any, Dict, List, Optional

from .types import (
    ActivityCategory,
    AllegationReason,
    BudgetingMethod,
    ClaimType,
    ComputationMethod,
    ExclusionType,
    ExtensionType,
    GoodCauseReason,
    IncomeSourceType,
    RecoveryMethod,
    RequestedProgram,
    ResourceItemType,
    ServiceType,
    VerificationSource,
    VerificationStatus,
)


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; an override of ``None`` drops the field entirely."""
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


# --- Households -------------------------------------------------------------


def household_payload(**overrides: Any) -> Dict[str, Any]:
    """A single-parent unit of three whose youngest child is 84 months old."""
    return _merge(
        {
            "head_of_household_name": "Dana Reyes",
            "county_code": "ADA",
            "household_size": 3,
            "adult_count": 1,
            "youngest_child_age_months": 84,
        },
        overrides,
    )


def prior_assistance_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "source_state_code": "OR",
            "state_clock_months": 0,
            "federal_clock_months": 0,
        },
        overrides,
    )


# --- Applications -----------------------------------------------------------


def application_payload(household_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "household_id": household_id,
            "application_month": "2026-08",
            "requested_program": RequestedProgram.ONGOING_ASSISTANCE.value,
            "budgeting_method": BudgetingMethod.PROSPECTIVE.value,
        },
        overrides,
    )


def income_source_payload(**overrides: Any) -> Dict[str, Any]:
    """Recurring earned income of 40000 cents a month."""
    return _merge(
        {
            "source_type": IncomeSourceType.EARNED.value,
            "gross_monthly_cents": 40000,
            "month_1_cents": 0,
            "month_2_cents": 0,
            "month_3_cents": 0,
            "is_recurring": True,
        },
        overrides,
    )


def verify_income_payload(
    verification_status: str = VerificationStatus.VERIFIED.value,
) -> Dict[str, Any]:
    return {"verification_status": verification_status}


def resource_item_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "item_type": ResourceItemType.LIQUID_ASSET.value,
            "gross_value_cents": 10000,
            "encumbrance_cents": 0,
            "exclusion_type": ExclusionType.NONE.value,
        },
        overrides,
    )


def approve_payload(certification_start_month: str = "2026-08") -> Dict[str, Any]:
    return {"certification_start_month": certification_start_month}


def deny_payload(denial_reason: str = "OTHER") -> Dict[str, Any]:
    return {"denial_reason": denial_reason}


def withdraw_payload(withdrawal_reason: str = "Family found employment") -> Dict[str, Any]:
    return {"withdrawal_reason": withdrawal_reason}


def decline_diversion_payload(
    decline_reason: str = "Prefers ongoing assistance",
) -> Dict[str, Any]:
    return {"decline_reason": decline_reason}


# --- Issuance and extensions -----------------------------------------------


def issuance_payload(benefit_month: str = "2026-08") -> Dict[str, Any]:
    return {"benefit_month": benefit_month}


def extension_request_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "extension_type": ExtensionType.HARDSHIP_DISABILITY.value,
            "months_requested": 3,
            "first_effective_month": "2026-08",
        },
        overrides,
    )


def grant_extension_payload(months_granted: int = 3) -> Dict[str, Any]:
    return {"months_granted": months_granted}


def deny_extension_payload(denial_reason: str = "Insufficient documentation") -> Dict[str, Any]:
    return {"denial_reason": denial_reason}


def revoke_extension_payload(
    revocation_reason: str = "Hardship no longer applies",
) -> Dict[str, Any]:
    return {"revocation_reason": revocation_reason}


# --- Work assignments -------------------------------------------------------


def work_assignment_payload(**overrides: Any) -> Dict[str, Any]:
    """A core community-service activity of 30 weekly hours over one quarter."""
    return _merge(
        {
            "activity_category": ActivityCategory.COMMUNITY_SERVICE.value,
            "scheduled_weekly_hours": 30,
            "start_date": "2026-08-01",
            "end_date": "2026-11-01",
        },
        overrides,
    )


def terminate_assignment_payload(termination_reason: str) -> Dict[str, Any]:
    return {"termination_reason": termination_reason}


# --- Participation reports --------------------------------------------------


def participation_report_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "report_month": "2026-08",
            "reported_hours": 120,
            "verification_source": VerificationSource.TIMESHEET.value,
        },
        overrides,
    )


def verify_report_payload(verified_hours: int) -> Dict[str, Any]:
    return {"verified_hours": verified_hours}


def reject_report_payload(rejection_reason: str = "Timesheet illegible") -> Dict[str, Any]:
    return {"rejection_reason": rejection_reason}


# --- Compliance episodes ----------------------------------------------------


def compliance_episode_payload(
    case_id: str,
    expected_case_version: int,
    allegation_reason: str = AllegationReason.MISSED_APPOINTMENT.value,
    prior_episode_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "case_id": case_id,
            "allegation_reason": allegation_reason,
            "expected_case_version": expected_case_version,
            "prior_episode_id": prior_episode_id,
        },
        overrides,
    )


def good_cause_payload(
    good_cause_reason: str = GoodCauseReason.ILLNESS.value,
) -> Dict[str, Any]:
    return {"good_cause_reason": good_cause_reason}


def begin_cure_payload(cure_plan_note: str = "Weekly check-ins agreed") -> Dict[str, Any]:
    return {"cure_plan_note": cure_plan_note}


# --- Supportive services ----------------------------------------------------


def supportive_authorization_payload(
    case_id: str,
    work_assignment_id: str,
    expected_case_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "case_id": case_id,
            "work_assignment_id": work_assignment_id,
            "service_type": ServiceType.TRANSPORTATION.value,
            "requested_amount_cents": 40000,
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "expected_case_version": expected_case_version,
        },
        overrides,
    )


def void_payload(void_reason: str = "Service no longer needed") -> Dict[str, Any]:
    return {"void_reason": void_reason}


# --- Overpayments -----------------------------------------------------------


def overpayment_payload(
    case_id: str, months_covered: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "case_id": case_id,
            "claim_type": ClaimType.CLIENT_ERROR.value,
            "months_covered": months_covered or ["2026-08"],
            "gross_amount_cents": 50000,
            "computation_method": ComputationMethod.GROSS.value,
            "offsetting_underpayment_cents": 0,
        },
        overrides,
    )


def recovery_transaction_payload(
    expected_overpayment_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "method": RecoveryMethod.CASH_PAYMENT.value,
            "amount_cents": 10000,
            "applied_month": "2026-08",
            "expected_overpayment_version": expected_overpayment_version,
        },
        overrides,
    )


def write_off_payload(write_off_reason: str = "Uncollectible") -> Dict[str, Any]:
    return {"write_off_reason": write_off_reason}


def fraud_referral_payload(referral_note: str = "Unreported earnings") -> Dict[str, Any]:
    return {"referral_note": referral_note}


def fraud_disposition_payload(disposition: str) -> Dict[str, Any]:
    return {"disposition": disposition}


# --- Federal reporting ------------------------------------------------------


def reporting_period_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "fiscal_year": 2026,
            "quarter": 4,
            "prior_year_caseload": 100.00,
            "eligibility_change_caseload_effect": 0.00,
        },
        overrides,
    )
