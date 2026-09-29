"""Request payload builders with sane defaults and keyword overrides.

Every builder returns a fresh dict, so callers may mutate the result freely.
Passing ``None`` for an optional key removes it from the payload, which is how
tests exercise omitted-field behaviour.
"""

import itertools
from typing import Any, Dict, List, Optional

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Cycle
# ---------------------------------------------------------------------------
def make_cycle_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "code": f"CY-{2027 + _next() % 900:04d}-{_next():04d}",
        "open_at": "2026-08-01T00:00:00Z",
        "close_at": "2026-09-30T00:00:00Z",
        "application_fee_cents": 5000,
        "panel_quorum": 2,
        "cohort_target_size": 10,
        "alumni_reserve_pct": 0.25,
        "stipend_pool_cents": 20000000,
        "slate_min_score": 60.0,
        "stipend_weekly_rate_cents": 70000,
        "session_length_options_weeks": [4, 5, 8, 9],
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Discipline
# ---------------------------------------------------------------------------
def make_discipline_payload(cycle_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "cycle_id": cycle_id,
        "code": "SCULPT",
        "name": "Sculpture",
        "portfolio_min_items": 1,
        "portfolio_max_items": 6,
        "required_media_types": ["IMAGE"],
        "requires_hazmat_review": False,
        "cohort_min_slots": 1,
        "cohort_max_slots": 6,
        "required_capability_tags": ["WELDING"],
        "required_ventilation_class": "LOCAL",
    }
    return _apply(payload, overrides)


def make_print_discipline_payload(cycle_id: str, **overrides) -> Dict[str, Any]:
    payload = make_discipline_payload(
        cycle_id,
        code="PRINT",
        name="Printmaking",
        required_capability_tags=["PRINT_PRESS"],
        required_ventilation_class="NONE",
        cohort_max_slots=4,
    )
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Applicant
# ---------------------------------------------------------------------------
def make_applicant_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    payload = {
        "full_name": f"Ada Rivet {n}",
        "email": f"ada.rivet.{n}@example.org",
        "affiliation_org": "North Shore Collective",
        "citizenship_country": "US",
        "treaty_country": False,
        "declared_annual_income_cents": 2000000,
    }
    return _apply(payload, overrides)


def make_international_applicant_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    payload = make_applicant_payload(
        full_name=f"Camille Roux {n}",
        email=f"camille.roux.{n}@example.org",
        affiliation_org="Atelier Sud",
        citizenship_country="FR",
        treaty_country=True,
        declared_annual_income_cents=1900000,
    )
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
def make_application_payload(
    cycle_id: str, applicant_id: str, discipline_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "cycle_id": cycle_id,
        "applicant_id": applicant_id,
        "discipline_id": discipline_id,
        "requested_session_length_weeks": 8,
        "project_statement": "A welded steel series exploring shoreline erosion.",
        "fee_waiver_requested": False,
    }
    return _apply(payload, overrides)


def make_portfolio_item_payload(application_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "application_id": application_id,
        "media_type": "IMAGE",
        "title": f"Plate {_next()}",
        "file_size_mb": 12.5,
        "hazardous_materials_declared": False,
    }
    return _apply(payload, overrides)


def make_fee_resolution_payload(action: str = "PAY", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    return _apply(payload, overrides)


def make_screening_decision_payload(
    decision: str = "ADVANCE", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    return _apply(payload, overrides)


def make_offer_response_payload(response: str = "ACCEPT", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"response": response}
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------
# Every discipline code the suite configures. The default reviewer is
# credentialed in all of them so that `expertise_matched` is true — and the
# multiplier therefore "exactly 1.00" — for any application the default
# reviewer is seated on, whatever discipline it competes in. A test that wants
# the 0.90 mismatch leg passes `discipline_expertise` explicitly.
ALL_DISCIPLINE_EXPERTISE = [
    "CLAYWORK",
    "ETCH",
    "KILNWORK",
    "PRINT",
    "SCULPT",
    "TEXTILE",
]


def make_panelist_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    payload = {
        "full_name": f"Rae Reviewer {n}",
        "email": f"rae.reviewer.{n}@example.org",
        "affiliation_org": f"Museum {n}",
        "discipline_expertise": list(ALL_DISCIPLINE_EXPERTISE),
        "chair_eligible": False,
    }
    return _apply(payload, overrides)


def make_chair_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    payload = make_panelist_payload(
        full_name=f"Chair Vey {n}",
        email=f"chair.vey.{n}@example.org",
        affiliation_org=f"Museum Chair {n}",
        chair_eligible=True,
    )
    return _apply(payload, overrides)


def make_panel_assignment_payload(
    application_id: str, panelist_id: str, **overrides
) -> Dict[str, Any]:
    payload = {"application_id": application_id, "panelist_id": panelist_id}
    return _apply(payload, overrides)


def make_score_payload(
    artistic: int = 8,
    feasibility: int = 8,
    community: int = 8,
    technical: int = 8,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "score_artistic_merit": artistic,
        "score_feasibility": feasibility,
        "score_community_fit": community,
        "score_technical_readiness": technical,
    }
    return _apply(payload, overrides)


def make_conflict_payload(
    conflict_type: str = "FAMILIAL", detail: str = "Sibling of the artist", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "conflict_type": conflict_type,
        "conflict_detail": detail,
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Residency
# ---------------------------------------------------------------------------
def make_residency_payload(
    cycle_id: str, applicant_id: str, discipline_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "cycle_id": cycle_id,
        "applicant_id": applicant_id,
        "discipline_id": discipline_id,
    }
    return _apply(payload, overrides)


def make_schedule_payload(
    session_start_date: str = "2026-11-02", session_length_weeks: int = 8, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "session_start_date": session_start_date,
        "session_length_weeks": session_length_weeks,
    }
    return _apply(payload, overrides)


def make_lifecycle_payload(action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    return _apply(payload, overrides)


def make_compliance_payload(action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    return _apply(payload, overrides)


def make_training_payload(training_type: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"training_type": training_type}
    return _apply(payload, overrides)


def make_stipend_schedule_payload(
    expected_residency_version: Optional[int], **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if expected_residency_version is not None:
        payload["expected_residency_version"] = expected_residency_version
    return _apply(payload, overrides)


def make_settlement_payload(action: str = "PAY", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    return _apply(payload, overrides)


def make_obligation_progress_payload(
    action: str = "LOG_COMPLETION", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Facilities
# ---------------------------------------------------------------------------
def make_studio_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "code": f"S-{_next():03d}",
        "capability_tags": ["WELDING", "KILN"],
        "ventilation_class": "LOCAL",
        "max_concurrent_residents": 1,
        "status": "AVAILABLE",
    }
    return _apply(payload, overrides)


def make_housing_unit_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "code": f"H-{_next():03d}",
        "bed_count": 1,
        "meal_plan_included": True,
        "accessibility_features": ["STEP_FREE"],
        "status": "AVAILABLE",
    }
    return _apply(payload, overrides)


def make_studio_assignment_payload(
    residency_id: str,
    start_date: str,
    end_date: str,
    expected_residency_version: Optional[int],
    studio_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "residency_id": residency_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if expected_residency_version is not None:
        payload["expected_residency_version"] = expected_residency_version
    if studio_id is not None:
        payload["studio_id"] = studio_id
    return _apply(payload, overrides)


def make_housing_assignment_payload(
    housing_unit_id: str,
    residency_id: str,
    check_in_date: str,
    check_out_date: str,
    expected_housing_unit_version: Optional[int],
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "housing_unit_id": housing_unit_id,
        "residency_id": residency_id,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
    }
    if expected_housing_unit_version is not None:
        payload["expected_housing_unit_version"] = expected_housing_unit_version
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Visa
# ---------------------------------------------------------------------------
def make_visa_case_payload(residency_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"residency_id": residency_id}
    return _apply(payload, overrides)


def make_visa_docs_payload(
    action: str = "REQUEST", doc_list: Optional[List[str]] = None, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": action,
        "doc_list": ["PASSPORT", "INVITATION_LETTER"] if doc_list is None else doc_list,
    }
    return _apply(payload, overrides)


def make_visa_adjudication_payload(action: str = "FILE", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    return _apply(payload, overrides)
