"""Request-payload builders for every creating and transitioning endpoint.

Each builder mirrors the request body PRD §3 describes for its endpoint. Where
the PRD makes a field optional, the builder omits the key entirely when the
caller passes `None` -- an omitted key and an explicit null are different
requests, and several rules turn on that difference.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    INDICATOR_CANONICAL_CATEGORY,
    METHOD_SCREENING_LEVEL,
)


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the `None` sentinel meaning 'omit the field'."""
    return {key: value for key, value in payload.items() if value is not None}


# ---------------------------------------------------------------------------
# Screening areas and burden indicators
# ---------------------------------------------------------------------------


def screening_area_payload(
    area_code: str,
    county: str,
    population: int,
    limited_english_pct: float,
    baseline_load_tpy: float,
    required_translation_languages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Body for `POST /ej/screening-areas`.

    Passing `required_translation_languages=None` omits the key so that the
    declared default can be observed.
    """
    return _prune(
        {
            "area_code": area_code,
            "county": county,
            "population": population,
            "limited_english_pct": limited_english_pct,
            "required_translation_languages": required_translation_languages,
            "baseline_load_tpy": baseline_load_tpy,
        }
    )


def burden_indicator_payload(
    screening_area_id: str,
    indicator_code: str,
    raw_value: float,
    statewide_percentile: Optional[float],
    county_percentile: Optional[float],
    vintage_year: int,
    expected_screening_area_version: int,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Body for `POST /ej/burden-indicators`.

    `category` defaults to the code's canonical family; pass a different value
    to exercise the category-agreement rule.
    """
    return _prune(
        {
            "screening_area_id": screening_area_id,
            "indicator_code": indicator_code,
            "category": category or INDICATOR_CANONICAL_CATEGORY[indicator_code],
            "raw_value": raw_value,
            "statewide_percentile": statewide_percentile,
            "county_percentile": county_percentile,
            "vintage_year": vintage_year,
            "expected_screening_area_version": expected_screening_area_version,
        }
    )


# ---------------------------------------------------------------------------
# Facilities and venues
# ---------------------------------------------------------------------------


def facility_payload(
    screening_area_id: str,
    name: str,
    facility_type: str,
    distance_to_area_centroid_m: int,
) -> Dict[str, Any]:
    """Body for `POST /ej/facilities`."""
    return {
        "screening_area_id": screening_area_id,
        "name": name,
        "facility_type": facility_type,
        "distance_to_area_centroid_m": distance_to_area_centroid_m,
    }


def venue_payload(
    name: str,
    address: str,
    capacity: int,
    transit_accessible: bool,
    ada_accessible: bool,
    interpretation_capable: bool,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Body for `POST /ej/venues`; `status=None` omits the key."""
    return _prune(
        {
            "name": name,
            "address": address,
            "capacity": capacity,
            "transit_accessible": transit_accessible,
            "ada_accessible": ada_accessible,
            "interpretation_capable": interpretation_capable,
            "status": status,
        }
    )


# ---------------------------------------------------------------------------
# Permit applications
# ---------------------------------------------------------------------------


def permit_application_payload(
    facility_id: str,
    permit_type: str,
    proposed_emissions_tpy: float,
    proposed_operating_hours_per_year: int,
    prior_application_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Body for `POST /ej/permit-applications`."""
    return _prune(
        {
            "facility_id": facility_id,
            "permit_type": permit_type,
            "proposed_emissions_tpy": proposed_emissions_tpy,
            "proposed_operating_hours_per_year": proposed_operating_hours_per_year,
            "prior_application_id": prior_application_id,
        }
    )


def return_for_revision_payload(reason: str) -> Dict[str, Any]:
    """Body for `POST /ej/permit-applications/{id}/return-for-revision`."""
    return {"reason": reason}


def resubmit_payload(proposed_emissions_tpy: Optional[float] = None) -> Dict[str, Any]:
    """Body for `POST /ej/permit-applications/{id}/resubmit`."""
    return _prune({"proposed_emissions_tpy": proposed_emissions_tpy})


def withdraw_payload(reason: Optional[str] = None) -> Dict[str, Any]:
    """Body for `POST /ej/permit-applications/{id}/withdraw`."""
    return _prune({"reason": reason})


# ---------------------------------------------------------------------------
# Cumulative impact assessments
# ---------------------------------------------------------------------------


def assessment_payload(
    permit_application_id: str,
    expected_application_version: int,
    method: str = METHOD_SCREENING_LEVEL,
    dispersion_factor: Optional[float] = None,
    receptor_distance_m: Optional[int] = None,
) -> Dict[str, Any]:
    """Body for `POST /ej/cumulative-impact-assessments`."""
    return _prune(
        {
            "permit_application_id": permit_application_id,
            "method": method,
            "dispersion_factor": dispersion_factor,
            "receptor_distance_m": receptor_distance_m,
            "expected_application_version": expected_application_version,
        }
    )


def qa_decision_payload(outcome: str, note: Optional[str] = None) -> Dict[str, Any]:
    """Body for `POST /ej/cumulative-impact-assessments/{id}/qa-decision`."""
    return _prune({"outcome": outcome, "note": note})


def revise_assessment_payload(
    method: str,
    dispersion_factor: Optional[float] = None,
    receptor_distance_m: Optional[int] = None,
) -> Dict[str, Any]:
    """Body for `POST /ej/cumulative-impact-assessments/{id}/revise`."""
    return _prune(
        {
            "method": method,
            "dispersion_factor": dispersion_factor,
            "receptor_distance_m": receptor_distance_m,
        }
    )


# ---------------------------------------------------------------------------
# Participation plans, meetings, comments
# ---------------------------------------------------------------------------


def plan_translation_payload(
    translated_languages: List[str], materials_translated: bool
) -> Dict[str, Any]:
    """Body for `PATCH /ej/participation-plans/{id}`."""
    return {
        "translated_languages": translated_languages,
        "materials_translated": materials_translated,
    }


def open_plan_payload(comment_start_date: str) -> Dict[str, Any]:
    """Body for `POST /ej/participation-plans/{id}/open`."""
    return {"comment_start_date": comment_start_date}


def extend_plan_payload(additional_days: int, reason: str) -> Dict[str, Any]:
    """Body for `POST /ej/participation-plans/{id}/extend`."""
    return {"additional_days": additional_days, "reason": reason}


def meeting_payload(
    participation_plan_id: str,
    venue_id: str,
    starts_at: str,
    ends_at: str,
    interpretation_languages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Body for `POST /ej/public-meetings`."""
    return _prune(
        {
            "participation_plan_id": participation_plan_id,
            "venue_id": venue_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "interpretation_languages": interpretation_languages,
        }
    )


def cancel_meeting_payload(reason: str) -> Dict[str, Any]:
    """Body for `POST /ej/public-meetings/{id}/cancel`."""
    return {"reason": reason}


def public_comment_payload(
    participation_plan_id: str, submitter_name: str, language: str, body: str
) -> Dict[str, Any]:
    """Body for `POST /ej/public-comments`."""
    return {
        "participation_plan_id": participation_plan_id,
        "submitter_name": submitter_name,
        "language": language,
        "body": body,
    }


# ---------------------------------------------------------------------------
# Conditions and decisions
# ---------------------------------------------------------------------------


def condition_payload(
    permit_application_id: str,
    condition_type: str,
    reduction_tpy: float,
    enforceable: bool,
    expected_application_version: int,
    monitoring_frequency: Optional[str] = None,
    benefit_value_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """Body for `POST /ej/permit-conditions`."""
    return _prune(
        {
            "permit_application_id": permit_application_id,
            "condition_type": condition_type,
            "reduction_tpy": reduction_tpy,
            "enforceable": enforceable,
            "monitoring_frequency": monitoring_frequency,
            "benefit_value_usd": benefit_value_usd,
            "expected_application_version": expected_application_version,
        }
    )


def decision_payload(
    permit_application_id: str,
    disposition: str,
    community_benefit_base_usd: Optional[float] = None,
    denial_basis: Optional[str] = None,
) -> Dict[str, Any]:
    """Body for `POST /ej/permit-decisions`."""
    return _prune(
        {
            "permit_application_id": permit_application_id,
            "disposition": disposition,
            "community_benefit_base_usd": community_benefit_base_usd,
            "denial_basis": denial_basis,
        }
    )


def rescind_payload(reason: str) -> Dict[str, Any]:
    """Body for `POST /ej/permit-decisions/{id}/rescind`."""
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Complaints and inspections
# ---------------------------------------------------------------------------


def complaint_payload(
    screening_area_id: str,
    complaint_type: str,
    severity: str,
    description: str,
    submitter_language: str = "en",
    facility_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Body for `POST /ej/community-complaints`."""
    return _prune(
        {
            "screening_area_id": screening_area_id,
            "facility_id": facility_id,
            "complaint_type": complaint_type,
            "severity": severity,
            "description": description,
            "submitter_language": submitter_language,
        }
    )


def triage_payload(outcome: str, dismissal_reason: Optional[str] = None) -> Dict[str, Any]:
    """Body for `POST /ej/community-complaints/{id}/triage`."""
    return _prune({"outcome": outcome, "dismissal_reason": dismissal_reason})


def reopen_complaint_payload(reason: str) -> Dict[str, Any]:
    """Body for `POST /ej/community-complaints/{id}/reopen`."""
    return {"reason": reason}


def resolve_complaint_payload(
    resolution: str, note: Optional[str] = None
) -> Dict[str, Any]:
    """Body for `POST /ej/community-complaints/{id}/resolve`."""
    return _prune({"resolution": resolution, "note": note})


def assign_next_payload(
    inspector_user_id: str,
    scheduled_date: str,
    screening_area_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Body for `POST /ej/inspections/assign-next`."""
    return _prune(
        {
            "inspector_user_id": inspector_user_id,
            "scheduled_date": scheduled_date,
            "screening_area_id": screening_area_id,
        }
    )


def complete_inspection_payload(
    finding: str, notes: Optional[str] = None
) -> Dict[str, Any]:
    """Body for `POST /ej/inspections/{id}/complete`."""
    return _prune({"finding": finding, "notes": notes})


# ---------------------------------------------------------------------------
# Program evaluation
# ---------------------------------------------------------------------------


def program_evaluation_params(
    basis: Optional[str] = None,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    designation: Optional[str] = None,
) -> Dict[str, Any]:
    """Query string for `GET /ej/program-evaluation`."""
    return _prune(
        {
            "basis": basis,
            "period_start": period_start,
            "period_end": period_end,
            "designation": designation,
        }
    )


def page_params(limit: Optional[int] = None, offset: Optional[int] = None, **filters: Any) -> Dict[str, Any]:
    """Query string combining pagination controls with listing filters."""
    return _prune({"limit": limit, "offset": offset, **filters})
