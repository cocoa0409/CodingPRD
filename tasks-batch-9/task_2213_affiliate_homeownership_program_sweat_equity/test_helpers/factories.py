"""Request payload builders.

Every builder returns a valid payload for its endpoint and accepts keyword
overrides so a test can perturb exactly the one field it is about. Defaults are
the canonical figures the suite reuses: an affiliate whose area median income is
6,000,000 cents with a 5,000,000-cent subsidy pool, and a four-person household
whose verified income of 3,000,000 cents sits at 50% of area median.
"""

from typing import Any, Dict, List, Optional

from . import constants as C


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload.update(overrides)
    return payload


# --- 3.1 Program ------------------------------------------------------------
def program_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "affiliate_name": C.CANONICAL_AFFILIATE_NAME,
            "service_area_code": C.CANONICAL_SERVICE_AREA,
            "ami_median_income_cents": C.CANONICAL_AMI_MEDIAN_INCOME_CENTS,
            "subsidy_pool_cents": C.CANONICAL_SUBSIDY_POOL_CENTS,
            "sweat_equity_base_hours_required": C.CANONICAL_BASE_HOURS_REQUIRED,
            "committee_quorum": C.CANONICAL_QUORUM,
        },
        overrides,
    )


def pool_adjustment_payload(action: str, expected_program_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": action,
        "expected_program_version": expected_program_version,
    }
    return _merge(payload, overrides)


def waitlist_promotion_payload(promote_count: int = 1, **overrides: Any) -> Dict[str, Any]:
    return _merge({"promote_count": promote_count}, overrides)


# --- 3.2 Household and members ---------------------------------------------
def household_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "household_name": "Alvarez",
            "household_size": 4,
            "current_bedroom_count": 1,
            "habitability_deficiency_count": 3,
            "self_reported_annual_income_cents": 3_600_000,
            "self_reported_housing_cost_cents": 150_000,
            "monthly_debt_payment_cents": 30_000,
            "credit_score": 640,
            "on_time_housing_payment_months": 24,
        },
        overrides,
    )


def member_payload(household_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "household_id": household_id,
            "full_name": "Rosa Alvarez",
            "relationship": C.RELATIONSHIP_APPLICANT,
            "birth_date": "1985-03-15T00:00:00.000Z",
            "is_adult_occupant": True,
        },
        overrides,
    )


def submit_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"attestation_signed": True}, overrides)


def screen_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "income_documents_received": True,
            "verified_annual_income_cents": C.CANONICAL_VERIFIED_ANNUAL_INCOME_CENTS,
            "verified_housing_cost_cents": C.CANONICAL_VERIFIED_HOUSING_COST_CENTS,
        },
        overrides,
    )


def referral_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"referral_memo": "File verified, referred to committee"}, overrides)


def return_to_screening_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": "Additional documentation required for the file"}, overrides)


def selection_decision_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"decision_minutes": "Committee met and recorded its documented decision on the file."},
        overrides,
    )


# --- 3.3 Selection reviews --------------------------------------------------
def review_payload(household_id: str, dimension: str, score: float = 80, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "household_id": household_id,
            "dimension": dimension,
            "score": score,
            "recommendation": C.RECOMMENDATION_ADVANCE,
        },
        overrides,
    )


def retraction_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"retraction_reason": "Reviewer withdrew the filed score for rescoring"}, overrides)


def advancing_review_set(household_id: str, score: float = 80) -> List[Dict[str, Any]]:
    """One ADVANCE review per dimension, for each of two committee reviewers."""
    return [review_payload(household_id, dimension, score) for dimension in C.ALL_DIMENSIONS]


# --- 3.4 Sweat equity -------------------------------------------------------
def entry_payload(
    household_id: str,
    member_id: str,
    category: str = C.CATEGORY_CONSTRUCTION,
    hours_claimed: float = 6.0,
    work_date: str = "2026-08-01T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "household_id": household_id,
            "member_id": member_id,
            "category": category,
            "work_date": work_date,
            "hours_claimed": hours_claimed,
        },
        overrides,
    )


def verification_payload(decision: str = C.DECISION_VERIFIED, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def rejection_payload(reason: str = "Hours could not be corroborated", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": C.DECISION_REJECTED, "rejection_reason": reason}, overrides)


def resubmit_payload(hours_claimed: float, work_date: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"hours_claimed": hours_claimed, "work_date": work_date}, overrides)


def reversal_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"reversal_reason": "Posted hours were later found to be incorrect"}, overrides)


# --- 3.5 Education ----------------------------------------------------------
def enrollment_payload(
    household_id: str,
    curriculum_code: str = C.CURRICULUM_HOMEBUYER_CORE,
    required_module_count: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "household_id": household_id,
            "curriculum_code": curriculum_code,
            "required_module_count": required_module_count,
        },
        overrides,
    )


def module_completion_payload(
    outcome: str = C.OUTCOME_PASSED, module_code: str = "MOD-1", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"outcome": outcome, "module_code": module_code}, overrides)


# --- 3.6 Build sites and costs ---------------------------------------------
def build_site_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "parcel_number": "P-1001",
            "street_address": "12 Cedar Ln",
            "acquisition_cost_cents": C.CANONICAL_ACQUISITION_COST_CENTS,
            "appraised_value_cents": C.CANONICAL_APPRAISED_VALUE_CENTS,
        },
        overrides,
    )


#: Every readiness step with the document reference that evidences it.
READINESS_STEPS = (
    (C.STEP_TITLE, "TITLE-1001"),
    (C.STEP_ENVIRONMENTAL, "ENV-1001"),
    (C.STEP_UTILITIES, "UTL-1001"),
    (C.STEP_FINAL_INSPECTION, "FINAL-1001"),
)


def readiness_payload(step: str, document_reference: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    if document_reference is None:
        document_reference = dict(READINESS_STEPS)[step]
    return _merge({"step": step, "document_reference": document_reference}, overrides)


def safety_posture_payload(posture: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"posture": posture}
    if posture == C.POSTURE_HOLD:
        payload["incident_note"] = "Trench collapse hazard reported on the lot"
    return _merge(payload, overrides)


def cash_cost_payload(
    build_site_id: str, amount_cents: int = 100_000, category: str = C.COST_CATEGORY_MATERIALS, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "build_site_id": build_site_id,
            "category": category,
            "is_in_kind": False,
            "amount_cents": amount_cents,
            "fair_market_value_cents": 0,
        },
        overrides,
    )


def in_kind_cost_payload(
    build_site_id: str,
    fair_market_value_cents: int = 250_000,
    category: str = C.COST_CATEGORY_MATERIALS,
    donor_name: str = "Cedar Lumber Co",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "build_site_id": build_site_id,
            "category": category,
            "is_in_kind": True,
            "amount_cents": 0,
            "fair_market_value_cents": fair_market_value_cents,
            "donor_name": donor_name,
        },
        overrides,
    )


def void_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"void_reason": "Line was recorded against the wrong site"}, overrides)


# --- 3.7 Shifts, volunteers, seats -----------------------------------------
def shift_payload(
    build_site_id: str,
    start_at: str = "2026-08-05T08:00:00.000Z",
    end_at: str = "2026-08-05T12:00:00.000Z",
    volunteer_slots: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "build_site_id": build_site_id,
            "crew_lead_user_id": "cm-1",
            "start_at": start_at,
            "end_at": end_at,
            "volunteer_slots": volunteer_slots,
        },
        overrides,
    )


def volunteer_payload(
    program_id: str,
    full_name: str = "Dana Ruiz",
    birth_date: str = "1990-06-01T00:00:00.000Z",
    trade_certifications: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "full_name": full_name,
        "birth_date": birth_date,
        "waiver_expires_on": C.WAIVER_FAR_FUTURE,
    }
    if trade_certifications is not None:
        payload["trade_certifications"] = trade_certifications
    return _merge(payload, overrides)


def certification(trade: str, expires_on: str = C.WAIVER_FAR_FUTURE) -> Dict[str, Any]:
    return {"trade": trade, "expires_on": expires_on}


def assignment_payload(
    shift_id: str,
    expected_shift_version: int,
    role: str = C.SEAT_GENERAL,
    volunteer_id: Optional[str] = None,
    household_member_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "shift_id": shift_id,
        "expected_shift_version": expected_shift_version,
        "role": role,
    }
    if volunteer_id is not None:
        payload["volunteer_id"] = volunteer_id
    if household_member_id is not None:
        payload["household_member_id"] = household_member_id
    return _merge(payload, overrides)


def lock_payload(safety_briefing_reference: str = "SB-2026-08-05", **overrides: Any) -> Dict[str, Any]:
    return _merge({"safety_briefing_reference": safety_briefing_reference}, overrides)


def completion_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"completion_note": "Framing crew closed out the day"}, overrides)


def cancellation_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"cancellation_reason": "Weather forced the crew off the lot"}, overrides)


# --- 3.8 Mortgage applications ---------------------------------------------
def application_payload(
    household_id: str,
    build_site_id: str,
    expected_household_version: int,
    term_months: int = C.TERM_240,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "household_id": household_id,
            "build_site_id": build_site_id,
            "expected_household_version": expected_household_version,
            "term_months": term_months,
        },
        overrides,
    )


def approval_payload(
    expected_program_version: int, resale_restriction_months: int = 240, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "expected_program_version": expected_program_version,
            "resale_restriction_months": resale_restriction_months,
        },
        overrides,
    )


def denial_payload(denial_reason_code: str = C.APP_DENIAL_READINESS, **overrides: Any) -> Dict[str, Any]:
    return _merge({"denial_reason_code": denial_reason_code}, overrides)


def return_to_draft_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"return_reason": "Site was re-appraised and the file needs repricing"}, overrides)


def closing_payload(closing_date: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"closing_date": closing_date}, overrides)


def lien_action_payload(action: str, effective_date: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action, "effective_date": effective_date}, overrides)


# --- 3.9 Grant awards -------------------------------------------------------
def grant_payload(
    program_id: str,
    award_code: str = "FHLB-2026-Q3",
    amount_cents: int = 2_500_000,
    period_start: str = "2026-07-01T00:00:00.000Z",
    period_end: str = "2026-09-30T00:00:00.000Z",
    households_served_target: int = 4,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "award_code": award_code,
            "donor_name": "Federal Home Loan Bank",
            "amount_cents": amount_cents,
            "period_start": period_start,
            "period_end": period_end,
            "households_served_target": households_served_target,
        },
        overrides,
    )
