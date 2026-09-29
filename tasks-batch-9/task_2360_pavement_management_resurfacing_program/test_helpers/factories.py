"""Request payload builders for the Pavement Management & Resurfacing Program API.

Every builder emits a complete, valid payload from the PRD's declared input
fields and lets a test override exactly the field under examination.
"""

from typing import Any, Dict, Optional

from .constants import (
    COLLECTION_AUTOMATED,
    CONTRACTOR_NAME,
    DEFAULT_CLOCK,
    FUNDING_STANDARD,
    HORIZON_YEARS,
    PROJECT_END,
    PROJECT_START,
    QC_ACCEPT_NOTE,
    SCENARIO_NAME,
    SEG_MAPLE,
    STRATEGY_WORST_FIRST,
    SURVEY_YEAR,
    WORK_WINDOW_END,
    WORK_WINDOW_START,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    """Sentinel that removes an otherwise-defaulted field from a payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<omit>"


_OMIT = _Omit()
OMIT = _OMIT


# ----------------------------------------------------------------------
# Clock
# ----------------------------------------------------------------------
def clock_payload(current_utc: str = DEFAULT_CLOCK, **overrides: Any) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


# ----------------------------------------------------------------------
# Inventory
# ----------------------------------------------------------------------
def segment_payload(profile: Optional[Dict[str, Any]] = None, **overrides: Any) -> Dict[str, Any]:
    return _merge(dict(profile or SEG_MAPLE), overrides)


# ----------------------------------------------------------------------
# Survey campaign
# ----------------------------------------------------------------------
def survey_payload(
    survey_year: int = SURVEY_YEAR,
    collection_method: str = COLLECTION_AUTOMATED,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {"survey_year": survey_year, "collection_method": collection_method}, overrides
    )


def observation_payload(
    survey_id: str,
    segment_id: str,
    profile: Dict[str, Any],
    **overrides: Any,
) -> Dict[str, Any]:
    base = {"survey_id": survey_id, "segment_id": segment_id}
    base.update(profile)
    return _merge(base, overrides)


def qc_payload(
    qc_decision: str = "ACCEPT", qc_note: Optional[str] = QC_ACCEPT_NOTE, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"qc_decision": qc_decision, "qc_note": qc_note}, overrides)


# ----------------------------------------------------------------------
# Candidates
# ----------------------------------------------------------------------
def override_payload(
    treatment_type: str, override_reason: str = "engineering judgement", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"treatment_type": treatment_type, "override_reason": override_reason}, overrides
    )


# ----------------------------------------------------------------------
# Budget scenarios
# ----------------------------------------------------------------------
def scenario_payload(
    survey_id: str,
    scenario_name: str = SCENARIO_NAME,
    funding_cents: int = FUNDING_STANDARD,
    strategy: str = STRATEGY_WORST_FIRST,
    horizon_years: int = HORIZON_YEARS,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "survey_id": survey_id,
            "scenario_name": scenario_name,
            "funding_cents": funding_cents,
            "strategy": strategy,
            "horizon_years": horizon_years,
        },
        overrides,
    )


def allocation_payload(
    scenario_id: str, candidate_id: str, expected_scenario_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "scenario_id": scenario_id,
            "candidate_id": candidate_id,
            "expected_scenario_version": expected_scenario_version,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Contractors
# ----------------------------------------------------------------------
def contractor_payload(
    legal_name: str = CONTRACTOR_NAME,
    max_concurrent_projects: Optional[int] = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {"legal_name": legal_name, "max_concurrent_projects": max_concurrent_projects},
        overrides,
    )


# ----------------------------------------------------------------------
# Projects and lines
# ----------------------------------------------------------------------
def project_payload(
    scenario_id: str,
    geo_zone: str = "Z1",
    project_name: str = "Zone 1 fall package",
    planned_start_date: str = PROJECT_START,
    planned_end_date: str = PROJECT_END,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "scenario_id": scenario_id,
            "project_name": project_name,
            "geo_zone": geo_zone,
            "planned_start_date": planned_start_date,
            "planned_end_date": planned_end_date,
        },
        overrides,
    )


def project_segment_payload(
    project_id: str,
    segment_id: str,
    candidate_id: str,
    expected_project_version: int,
    work_window_start: str = WORK_WINDOW_START,
    work_window_end: str = WORK_WINDOW_END,
    design_thickness_in: Optional[float] = 2.0,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "project_id": project_id,
            "segment_id": segment_id,
            "candidate_id": candidate_id,
            "work_window_start": work_window_start,
            "work_window_end": work_window_end,
            "expected_project_version": expected_project_version,
            "design_thickness_in": design_thickness_in,
        },
        overrides,
    )


def advance_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


def award_payload(contractor_id: str, award_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"contractor_id": contractor_id, "award_amount_cents": award_amount_cents}, overrides
    )


def cancel_award_payload(
    cancellation_reason: Optional[str] = "bid protest sustained", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"cancellation_reason": cancellation_reason}, overrides)


def accept_payload(
    acceptance_note: Optional[str] = "final walk complete", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"acceptance_note": acceptance_note}, overrides)


# ----------------------------------------------------------------------
# Resident notices
# ----------------------------------------------------------------------
def notice_payload(
    action: str,
    parking_restriction_start: Optional[str] = None,
    parking_restriction_end: Optional[str] = None,
    driveway_access_plan: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"action": action}
    if parking_restriction_start is not None:
        base["parking_restriction_start"] = parking_restriction_start
    if parking_restriction_end is not None:
        base["parking_restriction_end"] = parking_restriction_end
    if driveway_access_plan is not None:
        base["driveway_access_plan"] = driveway_access_plan
    return _merge(base, overrides)


def schedule_notice_payload(
    parking_restriction_start: str,
    parking_restriction_end: str,
    driveway_access_plan: str = "MAINTAINED",
    **overrides: Any,
) -> Dict[str, Any]:
    return notice_payload(
        "SCHEDULE",
        parking_restriction_start=parking_restriction_start,
        parking_restriction_end=parking_restriction_end,
        driveway_access_plan=driveway_access_plan,
        **overrides,
    )


# ----------------------------------------------------------------------
# Utility coordination
# ----------------------------------------------------------------------
def respond_payload(
    response: str,
    response_note: Optional[str] = None,
    planned_work_start: Optional[str] = None,
    planned_work_end: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"response": response}
    if response_note is not None:
        base["response_note"] = response_note
    if planned_work_start is not None:
        base["planned_work_start"] = planned_work_start
    if planned_work_end is not None:
        base["planned_work_end"] = planned_work_end
    return _merge(base, overrides)


# ----------------------------------------------------------------------
# Cut permits
# ----------------------------------------------------------------------
def cut_permit_payload(
    segment_id: str,
    applicant_utility: str = "WATER",
    requested_start: str = "2026-10-05T00:00:00Z",
    requested_end: str = "2026-10-06T00:00:00Z",
    cut_area_sqft: float = 100.0,
    emergency: Optional[bool] = False,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "segment_id": segment_id,
            "applicant_utility": applicant_utility,
            "requested_start": requested_start,
            "requested_end": requested_end,
            "cut_area_sqft": cut_area_sqft,
            "emergency": emergency,
        },
        overrides,
    )


def cut_decide_payload(
    decision: str = "APPROVE", waiver_reason: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"decision": decision}
    if waiver_reason is not None:
        base["waiver_reason"] = waiver_reason
    return _merge(base, overrides)


# ----------------------------------------------------------------------
# Acceptance tests
# ----------------------------------------------------------------------
def acceptance_test_payload(
    project_segment_id: str,
    witness_inspector_user_id: str,
    core_density_pct: float = 97.0,
    iri_in_per_mi: float = 55.0,
    thickness_in: float = 2.10,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "project_segment_id": project_segment_id,
            "core_density_pct": core_density_pct,
            "iri_in_per_mi": iri_in_per_mi,
            "thickness_in": thickness_in,
            "witness_inspector_user_id": witness_inspector_user_id,
        },
        overrides,
    )


def acceptance_decision_payload(
    decision: str, decision_note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"decision": decision}
    if decision_note is not None:
        base["decision_note"] = decision_note
    return _merge(base, overrides)


# ----------------------------------------------------------------------
# Service requests
# ----------------------------------------------------------------------
def service_request_payload(
    segment_id: str,
    complaint_type: str = "POTHOLE",
    reported_severity: str = "HIGH",
    location_note: str = "outside 214 Maple St",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "segment_id": segment_id,
            "complaint_type": complaint_type,
            "reported_severity": reported_severity,
            "location_note": location_note,
        },
        overrides,
    )


def triage_payload(
    disposition: str, target_project_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"disposition": disposition}
    if target_project_id is not None:
        base["target_project_id"] = target_project_id
    return _merge(base, overrides)


def close_payload(closure_code: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"closure_code": closure_code}, overrides)
