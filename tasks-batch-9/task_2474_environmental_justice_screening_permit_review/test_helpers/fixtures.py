"""Composite state builders and pytest fixtures.

The harness restarts the API before every individual test, so each test opens
against an empty database. Every precondition below is therefore built from
scratch through the endpoints PRD §4 declares -- there is no seeding shortcut.

Layout of this module:

1. Low-level step helpers (one call each, lenient success validation).
2. Read helpers, including "find the row in a listing" for resources that have
   no single-row GET.
3. Named area specifications reused across scenarios.
4. Scenario builders that chain steps into a state dictionary.
5. pytest fixtures wrapping the scenario builders.

Every builder returns a mutable `state` dict of handles: ids, the current
application `version`, and the version counters captured at each step, because
PRD §2.7 makes three endpoints require an `expected_*_version` guard field.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as build
from .api_client import ApiClient
from .constants import (
    CONDITION_ADDITIONAL_CONTROL,
    DEFAULT_CLOCK_UTC,
    FACILITY_TYPE_INCINERATOR,
    FACILITY_TYPE_MAJOR_SOURCE,
    FACILITY_TYPE_MINOR_SOURCE,
    METHOD_SCREENING_LEVEL,
    PERMIT_TYPE_MODIFICATION,
    PERMIT_TYPE_NEW_SOURCE,
    QA_OUTCOME_ACCEPT,
    QA_OUTCOME_RETURN,
    TRIAGE_ACCEPT,
    VENUE_ACTIVE,
    VENUE_DECOMMISSIONED,
)
from .test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    INSPECTOR_1_HEADERS,
    LIAISON_HEADERS,
    MANAGER_HEADERS,
    QA_HEADERS,
    make_applicant_headers,
    resident_headers,
)
from .types import FixtureState

# ---------------------------------------------------------------------------
# 1. Low-level step helpers
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock. Only a ProgramAdmin may drive it."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN_HEADERS))


def create_area(
    api: ApiClient,
    area_code: str,
    county: str,
    population: int,
    limited_english_pct: float,
    baseline_load_tpy: float,
    languages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Register a screening area and return its payload."""
    return get_success_data(
        api.create_screening_area(
            build.screening_area_payload(
                area_code=area_code,
                county=county,
                population=population,
                limited_english_pct=limited_english_pct,
                baseline_load_tpy=baseline_load_tpy,
                required_translation_languages=languages,
            ),
            ADMIN_HEADERS,
        )
    )


def file_indicator(
    api: ApiClient,
    area_id: str,
    indicator_code: str,
    raw_value: float,
    statewide_percentile: float,
    county_percentile: float,
    expected_area_version: int,
    vintage_year: int = 2024,
) -> Dict[str, Any]:
    """File one burden indicator, threading the area version guard."""
    return get_success_data(
        api.create_burden_indicator(
            build.burden_indicator_payload(
                screening_area_id=area_id,
                indicator_code=indicator_code,
                raw_value=raw_value,
                statewide_percentile=statewide_percentile,
                county_percentile=county_percentile,
                vintage_year=vintage_year,
                expected_screening_area_version=expected_area_version,
            ),
            ANALYST_HEADERS,
        )
    )


def file_indicators(
    api: ApiClient,
    area_id: str,
    start_version: int,
    specs: Sequence[Tuple[str, float, float, float]],
    vintage_year: int = 2024,
) -> Tuple[List[Dict[str, Any]], int]:
    """File a run of indicators, chaining `area_version_after` between them.

    Each spec is `(indicator_code, raw_value, statewide_pct, county_pct)`.
    Returns the filed rows and the area version after the last one.
    """
    version = start_version
    rows: List[Dict[str, Any]] = []
    for code, raw, statewide, county in specs:
        row = file_indicator(
            api,
            area_id,
            code,
            raw,
            statewide,
            county,
            expected_area_version=version,
            vintage_year=vintage_year,
        )
        rows.append(row)
        version = row["area_version_after"]
    return rows, version


def create_facility(
    api: ApiClient,
    area_id: str,
    name: str,
    facility_type: str,
    distance_to_area_centroid_m: int,
) -> Dict[str, Any]:
    """Register a facility inside an area."""
    return get_success_data(
        api.create_facility(
            build.facility_payload(
                screening_area_id=area_id,
                name=name,
                facility_type=facility_type,
                distance_to_area_centroid_m=distance_to_area_centroid_m,
            ),
            ADMIN_HEADERS,
        )
    )


def create_venue(
    api: ApiClient,
    name: str,
    address: str,
    capacity: int,
    transit_accessible: bool = True,
    ada_accessible: bool = True,
    interpretation_capable: bool = True,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a public-meeting venue."""
    return get_success_data(
        api.create_venue(
            build.venue_payload(
                name=name,
                address=address,
                capacity=capacity,
                transit_accessible=transit_accessible,
                ada_accessible=ada_accessible,
                interpretation_capable=interpretation_capable,
                status=status,
            ),
            ADMIN_HEADERS,
        )
    )


def create_application(
    api: ApiClient,
    facility_id: str,
    permit_type: str,
    proposed_emissions_tpy: float,
    proposed_operating_hours_per_year: int,
    prior_application_id: Optional[str] = None,
) -> Dict[str, Any]:
    """File a DRAFT application as the owning facility's representative."""
    return get_success_data(
        api.create_permit_application(
            build.permit_application_payload(
                facility_id=facility_id,
                permit_type=permit_type,
                proposed_emissions_tpy=proposed_emissions_tpy,
                proposed_operating_hours_per_year=proposed_operating_hours_per_year,
                prior_application_id=prior_application_id,
            ),
            make_applicant_headers(facility_id),
        )
    )


# ---------------------------------------------------------------------------
# 2. Read helpers
# ---------------------------------------------------------------------------


def read_area(api: ApiClient, area_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_screening_area(area_id, ANALYST_HEADERS))


def read_facility(api: ApiClient, facility_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_facility(facility_id, ANALYST_HEADERS))


def read_application(api: ApiClient, application_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_permit_application(application_id, ANALYST_HEADERS))


def read_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_participation_plan(plan_id, LIAISON_HEADERS))


def read_venue(api: ApiClient, venue_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_venue(venue_id, ANALYST_HEADERS))


def read_complaint(api: ApiClient, complaint_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_complaint(complaint_id, ANALYST_HEADERS))


def _rows(response) -> List[Dict[str, Any]]:
    body = response.json()
    assert response.status_code == 200, (
        f"listing failed with {response.status_code}: {response.text}"
    )
    return body["data"]


def _find(rows: List[Dict[str, Any]], row_id: str, resource: str) -> Dict[str, Any]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError(f"{resource} {row_id} is absent from the listing")


def find_assessment(api: ApiClient, application_id: str, assessment_id: str) -> Dict[str, Any]:
    """Assessments have no single-row GET, so read them from the application."""
    rows = _rows(api.list_application_assessments(application_id, ANALYST_HEADERS))
    return _find(rows, assessment_id, "assessment")


def find_condition(api: ApiClient, application_id: str, condition_id: str) -> Dict[str, Any]:
    rows = _rows(api.list_application_conditions(application_id, ANALYST_HEADERS))
    return _find(rows, condition_id, "condition")


def find_decision(api: ApiClient, application_id: str, decision_id: str) -> Dict[str, Any]:
    rows = _rows(api.list_application_decisions(application_id, MANAGER_HEADERS))
    return _find(rows, decision_id, "decision")


def find_meeting(api: ApiClient, plan_id: str, meeting_id: str) -> Dict[str, Any]:
    rows = _rows(api.list_plan_meetings(plan_id, LIAISON_HEADERS))
    return _find(rows, meeting_id, "meeting")


def find_inspection(api: ApiClient, complaint_id: str, inspection_id: str) -> Dict[str, Any]:
    rows = _rows(api.list_complaint_inspections(complaint_id, ANALYST_HEADERS))
    return _find(rows, inspection_id, "inspection")


def plan_id_for(api: ApiClient, application_id: str) -> Optional[str]:
    """The id of the application's participation plan, or None on the standard track."""
    rows = _rows(api.list_application_plans(application_id, LIAISON_HEADERS))
    return rows[0]["id"] if rows else None


def current_app_version(api: ApiClient, application_id: str) -> int:
    """Read the application's live `version` for the next optimistic guard."""
    return read_application(api, application_id)["version"]


# ---------------------------------------------------------------------------
# 3. Named area specifications
# ---------------------------------------------------------------------------

# Kern: heavily burdened, Spanish translation required, four indicators.
AREA_A_SPEC = dict(
    area_code="BG-06-101",
    county="Kern",
    population=4200,
    limited_english_pct=12.5,
    baseline_load_tpy=400.00,
    languages=["es"],
)
AREA_A_INDICATORS = (
    ("PM25", 12.40, 85.00, 62.00),
    ("DIESEL_PM", 4.80, 90.00, 70.00),
    ("ASTHMA_ED_RATE", 62.00, 80.00, 55.00),
    ("POVERTY_RATE", 31.50, 88.00, 65.00),
)
FACILITY_A_SPEC = dict(
    name="Kern Rendering Plant",
    facility_type=FACILITY_TYPE_MAJOR_SOURCE,
    distance_to_area_centroid_m=450,
)
APPLICATION_A_SPEC = dict(
    permit_type=PERMIT_TYPE_NEW_SOURCE,
    proposed_emissions_tpy=80.00,
    proposed_operating_hours_per_year=8000,
)
VENUE_A_SPEC = dict(
    name="Lamont Community Hall",
    address="8600 Main St, Lamont CA",
    capacity=120,
)

# Kings: severely overburdened, two facilities, two plans.
AREA_B_SPEC = dict(
    area_code="BG-06-202",
    county="Kings",
    population=5200,
    limited_english_pct=28.0,
    baseline_load_tpy=500.00,
    languages=["es"],
)
AREA_B_INDICATORS = (
    ("PM25", 18.90, 95.00, 92.00),
    ("DIESEL_PM", 9.10, 93.00, 88.00),
    ("ASTHMA_ED_RATE", 88.00, 90.00, 86.00),
    ("POVERTY_RATE", 41.20, 96.00, 94.00),
)

# Fresno pair sitting either side of the OVERBURDENED threshold.
AREA_C_SPEC = dict(
    area_code="BG-06-505",
    county="Fresno",
    population=3000,
    limited_english_pct=4.0,
    baseline_load_tpy=300.00,
    languages=[],
)
AREA_C_INDICATORS = (
    ("PM25", 11.10, 65.00, 45.00),
    ("ASTHMA_ED_RATE", 55.00, 65.00, 40.00),
)
AREA_C_LOW_SPEC = dict(
    area_code="BG-06-506",
    county="Fresno",
    population=2500,
    limited_english_pct=2.0,
    baseline_load_tpy=250.00,
    languages=[],
)
AREA_C_LOW_INDICATORS = (
    ("PM25", 11.05, 64.99, 30.00),
    ("ASTHMA_ED_RATE", 54.00, 64.99, 30.00),
)

# Tulare: starts undesignated so a later indicator can escalate it.
AREA_D_SPEC = dict(
    area_code="BG-06-404",
    county="Tulare",
    population=2100,
    limited_english_pct=3.0,
    baseline_load_tpy=200.00,
    languages=[],
)
AREA_D_INDICATORS = (
    ("PM25", 7.20, 40.00, 30.00),
    ("ASTHMA_ED_RATE", 74.00, 90.00, 70.00),
    ("POVERTY_RATE", 33.80, 92.00, 80.00),
)
FACILITY_D_SPEC = dict(
    name="Tulare Coating Shop",
    facility_type=FACILITY_TYPE_MINOR_SOURCE,
    distance_to_area_centroid_m=1500,
)

# Merced pair used for complaint-eligibility narrowing.
AREA_E_SPEC = dict(
    area_code="BG-06-707",
    county="Merced",
    population=1800,
    limited_english_pct=1.0,
    baseline_load_tpy=150.00,
    languages=[],
)
AREA_F_SPEC = dict(
    area_code="BG-06-808",
    county="Merced",
    population=2200,
    limited_english_pct=2.0,
    baseline_load_tpy=180.00,
    languages=[],
)

# Madera scratch areas, each with no indicators at all.
AREA_G_SPEC = dict(
    area_code="BG-06-903",
    county="Madera",
    population=1500,
    limited_english_pct=2.0,
    baseline_load_tpy=200.00,
    languages=[],
)
AREA_H_SPEC = dict(
    area_code="BG-06-902",
    county="Madera",
    population=1100,
    limited_english_pct=3.0,
    baseline_load_tpy=120.00,
    languages=[],
)
AREA_I_SPEC = dict(
    area_code="BG-06-904",
    county="Madera",
    population=1200,
    limited_english_pct=1.0,
    baseline_load_tpy=10.00,
    languages=[],
)
AREA_J_SPEC = dict(
    area_code="BG-06-905",
    county="Madera",
    population=1300,
    limited_english_pct=1.0,
    baseline_load_tpy=200.00,
    languages=[],
)
AREA_K_SPEC = dict(
    area_code="BG-06-906",
    county="Madera",
    population=2000,
    limited_english_pct=2.0,
    baseline_load_tpy=400.00,
    languages=[],
)
AREA_L_SPEC = dict(
    area_code="BG-06-907",
    county="Fresno",
    population=2600,
    limited_english_pct=12.5,
    baseline_load_tpy=400.00,
    languages=["es"],
)
AREA_M_SPEC = dict(
    area_code="BG-06-908",
    county="Kings",
    population=1800,
    limited_english_pct=4.0,
    baseline_load_tpy=250.00,
    languages=[],
)

VENUE_K_SPEC = dict(
    name="Madera Civic Center",
    address="200 W 4th St, Madera CA",
    capacity=200,
)
VENUE_L_SPEC = dict(
    name="Southwest Fresno Resource Center",
    address="1955 S Elm Ave, Fresno CA",
    capacity=150,
)


# ---------------------------------------------------------------------------
# 4. Scenario builders
# ---------------------------------------------------------------------------


def build_area(
    api: ApiClient,
    spec: Dict[str, Any],
    indicators: Sequence[Tuple[str, float, float, float]] = (),
    vintage_year: int = 2024,
) -> FixtureState:
    """Register one area and file its indicator run.

    Returns a state dict with `area_id`, `area_v0` (the version straight after
    registration) and `area_version` (the version after the last indicator).
    """
    area = create_area(api, **spec)
    state: FixtureState = {
        "area_id": area["id"],
        "area_v0": area["version"],
        "area_version": area["version"],
        "area_spec": spec,
        "indicators": [],
    }
    if indicators:
        rows, version = file_indicators(
            api, area["id"], area["version"], indicators, vintage_year=vintage_year
        )
        state["indicators"] = rows
        state["area_version"] = version
    return state


def add_facility(
    api: ApiClient,
    state: FixtureState,
    spec: Dict[str, Any],
    key: str = "facility_id",
) -> FixtureState:
    """Register a facility in `state["area_id"]` and stash its id under `key`."""
    facility = create_facility(api, state["area_id"], **spec)
    state[key] = facility["id"]
    return state


def add_application(
    api: ApiClient,
    state: FixtureState,
    spec: Dict[str, Any],
    facility_key: str = "facility_id",
    app_key: str = "app_id",
    submit: bool = False,
    screen: bool = False,
) -> FixtureState:
    """File an application, optionally submitting and screening it."""
    facility_id = state[facility_key]
    application = create_application(api, facility_id, **spec)
    state[app_key] = application["id"]
    state["app_version"] = application["version"]
    state["applicant_headers"] = make_applicant_headers(facility_id)
    if submit:
        submitted = get_success_data(
            api.submit_application(application["id"], make_applicant_headers(facility_id))
        )
        state["v_submit"] = submitted["version"]
        state["app_version"] = submitted["version"]
    if screen:
        determination = get_success_data(
            api.screen_application(state[app_key], ANALYST_HEADERS)
        )
        state["determination_id"] = determination["id"]
        state["v_screen"] = determination["application_version_after"]
        state["app_version"] = determination["application_version_after"]
        state["plan_id"] = plan_id_for(api, state[app_key])
    return state


def add_assessment(
    api: ApiClient,
    state: FixtureState,
    method: str = METHOD_SCREENING_LEVEL,
    dispersion_factor: Optional[float] = None,
    receptor_distance_m: Optional[int] = None,
    app_key: str = "app_id",
) -> FixtureState:
    """Author a cumulative impact assessment against the live app version."""
    assessment = get_success_data(
        api.create_assessment(
            build.assessment_payload(
                permit_application_id=state[app_key],
                expected_application_version=state["app_version"],
                method=method,
                dispersion_factor=dispersion_factor,
                receptor_distance_m=receptor_distance_m,
            ),
            ANALYST_HEADERS,
        )
    )
    state["assessment_id"] = assessment["id"]
    state["v_assessment"] = assessment["application_version_after"]
    state["app_version"] = assessment["application_version_after"]
    return state


def submit_assessment_for_qa(api: ApiClient, state: FixtureState) -> FixtureState:
    """Move the live assessment DRAFT -> SUBMITTED_FOR_QA."""
    get_success_data(api.submit_assessment_for_qa(state["assessment_id"], ANALYST_HEADERS))
    state["app_version"] = current_app_version(api, state["app_id"])
    return state


def qa_accept_assessment(
    api: ApiClient, state: FixtureState, note: str = "methodology verified"
) -> FixtureState:
    """QA accept the live assessment; the reviewer is never its author."""
    accepted = get_success_data(
        api.decide_assessment_qa(
            state["assessment_id"],
            build.qa_decision_payload(QA_OUTCOME_ACCEPT, note=note),
            QA_HEADERS,
        )
    )
    state["v_qa"] = accepted.get("application_version_after")
    state["app_version"] = current_app_version(api, state["app_id"])
    return state


def qa_return_assessment(api: ApiClient, state: FixtureState, note: str) -> FixtureState:
    """QA return the live assessment for rework."""
    get_success_data(
        api.decide_assessment_qa(
            state["assessment_id"],
            build.qa_decision_payload(QA_OUTCOME_RETURN, note=note),
            QA_HEADERS,
        )
    )
    state["app_version"] = current_app_version(api, state["app_id"])
    return state


def accept_screening_assessment(api: ApiClient, state: FixtureState) -> FixtureState:
    """Author, QA-submit and QA-accept a screening-level assessment in one go."""
    add_assessment(api, state, method=METHOD_SCREENING_LEVEL)
    submit_assessment_for_qa(api, state)
    qa_accept_assessment(api, state)
    return state


def add_condition(
    api: ApiClient,
    state: FixtureState,
    condition_type: str,
    reduction_tpy: float,
    enforceable: bool,
    monitoring_frequency: Optional[str] = None,
    benefit_value_usd: Optional[float] = None,
    key: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach a permit condition against the live application version."""
    condition = get_success_data(
        api.create_permit_condition(
            build.condition_payload(
                permit_application_id=state["app_id"],
                condition_type=condition_type,
                reduction_tpy=reduction_tpy,
                enforceable=enforceable,
                expected_application_version=state["app_version"],
                monitoring_frequency=monitoring_frequency,
                benefit_value_usd=benefit_value_usd,
            ),
            ANALYST_HEADERS,
        )
    )
    state.setdefault("condition_ids", []).append(condition["id"])
    if key:
        state[key] = condition["id"]
    state["condition_id"] = condition["id"]
    state["app_version"] = condition["application_version_after"]
    return condition


def translate_plan(
    api: ApiClient,
    state: FixtureState,
    languages: Sequence[str] = ("es",),
    materials_translated: bool = True,
) -> FixtureState:
    """Record translated-materials publication on the plan."""
    get_success_data(
        api.update_participation_plan(
            state["plan_id"],
            build.plan_translation_payload(list(languages), materials_translated),
            LIAISON_HEADERS,
        )
    )
    return state


def open_plan(
    api: ApiClient, state: FixtureState, comment_start_date: str, plan_key: str = "plan_id"
) -> Dict[str, Any]:
    """Open the plan's comment period."""
    return get_success_data(
        api.open_comment_period(
            state[plan_key], build.open_plan_payload(comment_start_date), LIAISON_HEADERS
        )
    )


def add_meeting(
    api: ApiClient,
    state: FixtureState,
    starts_at: str,
    ends_at: str,
    interpretation_languages: Optional[Sequence[str]] = None,
    plan_key: str = "plan_id",
    venue_key: str = "venue_id",
    key: Optional[str] = None,
) -> Dict[str, Any]:
    """Book a public meeting at the state's venue."""
    meeting = get_success_data(
        api.create_public_meeting(
            build.meeting_payload(
                participation_plan_id=state[plan_key],
                venue_id=state[venue_key],
                starts_at=starts_at,
                ends_at=ends_at,
                interpretation_languages=(
                    list(interpretation_languages) if interpretation_languages else None
                ),
            ),
            LIAISON_HEADERS,
        )
    )
    state.setdefault("meeting_ids", []).append(meeting["id"])
    state["meeting_id"] = meeting["id"]
    if key:
        state[key] = meeting["id"]
    return meeting


def close_plan(
    api: ApiClient, state: FixtureState, plan_key: str = "plan_id"
) -> Dict[str, Any]:
    """Close an elapsed comment period and compute adequacy."""
    return get_success_data(api.close_comment_period(state[plan_key], LIAISON_HEADERS))


def advance_to_decision(api: ApiClient, state: FixtureState) -> Dict[str, Any]:
    """Move a reviewed application into PENDING_DECISION."""
    advanced = get_success_data(api.advance_to_decision(state["app_id"], ANALYST_HEADERS))
    state["app_version"] = advanced["version"]
    return advanced


def issue_permit(
    api: ApiClient, state: FixtureState, community_benefit_base_usd: Optional[float] = None
) -> Dict[str, Any]:
    """Issue the permit and book both emissions ledgers."""
    decision = get_success_data(
        api.create_permit_decision(
            build.decision_payload(
                permit_application_id=state["app_id"],
                disposition="ISSUE",
                community_benefit_base_usd=community_benefit_base_usd,
            ),
            MANAGER_HEADERS,
        )
    )
    state["decision_id"] = decision["id"]
    state["app_version"] = current_app_version(api, state["app_id"])
    return decision


def deny_permit(api: ApiClient, state: FixtureState, denial_basis: str) -> Dict[str, Any]:
    """Deny the permit on a stated basis."""
    decision = get_success_data(
        api.create_permit_decision(
            build.decision_payload(
                permit_application_id=state["app_id"],
                disposition="DENY",
                denial_basis=denial_basis,
            ),
            MANAGER_HEADERS,
        )
    )
    state["decision_id"] = decision["id"]
    state["app_version"] = current_app_version(api, state["app_id"])
    return decision


def add_complaint(
    api: ApiClient,
    state: FixtureState,
    complaint_type: str,
    severity: str,
    description: str,
    resident: int,
    submitter_language: str = "en",
    facility_key: Optional[str] = "facility_id",
    key: Optional[str] = None,
) -> Dict[str, Any]:
    """Intake a community complaint from a resident."""
    facility_id = state.get(facility_key) if facility_key else None
    complaint = get_success_data(
        api.create_complaint(
            build.complaint_payload(
                screening_area_id=state["area_id"],
                complaint_type=complaint_type,
                severity=severity,
                description=description,
                submitter_language=submitter_language,
                facility_id=facility_id,
            ),
            resident_headers(resident),
        )
    )
    state.setdefault("complaint_ids", []).append(complaint["id"])
    state["complaint_id"] = complaint["id"]
    if key:
        state[key] = complaint["id"]
    return complaint


def triage_accept(api: ApiClient, complaint_id: str) -> Dict[str, Any]:
    """Accept a complaint into the inspection queue."""
    return get_success_data(
        api.triage_complaint(complaint_id, build.triage_payload(TRIAGE_ACCEPT), ANALYST_HEADERS)
    )


def triage_dismiss(api: ApiClient, complaint_id: str, dismissal_reason: str) -> Dict[str, Any]:
    """Dismiss a complaint out of the inspection queue."""
    return get_success_data(
        api.triage_complaint(
            complaint_id,
            build.triage_payload("DISMISS", dismissal_reason=dismissal_reason),
            ANALYST_HEADERS,
        )
    )


def assign_next(
    api: ApiClient,
    state: FixtureState,
    inspector_user_id: str,
    scheduled_date: str,
    narrow_to_area: bool = False,
    key: Optional[str] = None,
) -> Dict[str, Any]:
    """Assign the highest-priority inspectable complaint to an inspector."""
    inspection = get_success_data(
        api.assign_next_inspection(
            build.assign_next_payload(
                inspector_user_id=inspector_user_id,
                scheduled_date=scheduled_date,
                screening_area_id=state["area_id"] if narrow_to_area else None,
            ),
            ANALYST_HEADERS,
        )
    )
    state.setdefault("inspection_ids", []).append(inspection["id"])
    state["inspection_id"] = inspection["id"]
    if key:
        state[key] = inspection["id"]
    return inspection


def complete_inspection(
    api: ApiClient, inspection_id: str, finding: str, notes: str
) -> Dict[str, Any]:
    """Record an inspector's field finding."""
    return get_success_data(
        api.complete_inspection(
            inspection_id,
            build.complete_inspection_payload(finding, notes=notes),
            INSPECTOR_1_HEADERS,
        )
    )


# --- Full AREA_A chains ----------------------------------------------------


def build_area_a(api: ApiClient) -> FixtureState:
    """AREA_A registered with its four burden indicators."""
    return build_area(api, AREA_A_SPEC, AREA_A_INDICATORS)


def build_app_a_screened(api: ApiClient, with_venue: bool = False) -> FixtureState:
    """AREA_A + its major source + a submitted, screened application."""
    state = build_area_a(api)
    add_facility(api, state, FACILITY_A_SPEC)
    if with_venue:
        state["venue_id"] = create_venue(api, **VENUE_A_SPEC)["id"]
    add_application(api, state, APPLICATION_A_SPEC, submit=True, screen=True)
    return state


def build_app_a_assessment_accepted(api: ApiClient, with_venue: bool = False) -> FixtureState:
    """AREA_A screened application carrying an ACCEPTED screening assessment."""
    state = build_app_a_screened(api, with_venue=with_venue)
    accept_screening_assessment(api, state)
    return state


def build_app_a_plan_open(
    api: ApiClient,
    meeting_starts_at: str = "2026-08-20T18:00:00Z",
    meeting_ends_at: str = "2026-08-20T20:30:00Z",
    accepted: bool = True,
) -> FixtureState:
    """AREA_A enhanced-track application with a translated, open plan and meeting."""
    state = (
        build_app_a_assessment_accepted(api, with_venue=True)
        if accepted
        else build_app_a_screened(api, with_venue=True)
    )
    if not accepted:
        add_assessment(api, state, method=METHOD_SCREENING_LEVEL)
    translate_plan(api, state, languages=["es"], materials_translated=True)
    open_plan(api, state, "2026-08-01")
    add_meeting(api, state, meeting_starts_at, meeting_ends_at, ["es"])
    return state


def build_app_a_pending_decision(
    api: ApiClient,
    close_clock: str = "2026-10-10T09:00:00Z",
    meeting_starts_at: str = "2026-08-20T18:00:00Z",
    meeting_ends_at: str = "2026-08-20T20:30:00Z",
) -> FixtureState:
    """AREA_A application advanced into PENDING_DECISION with its plan closed."""
    state = build_app_a_plan_open(
        api, meeting_starts_at=meeting_starts_at, meeting_ends_at=meeting_ends_at
    )
    set_clock(api, close_clock)
    close_plan(api, state)
    advance_to_decision(api, state)
    return state


def build_app_a_issued(
    api: ApiClient,
    community_benefit_base_usd: float = 95000.00,
    reduction_tpy: float = 30.00,
    monitoring_frequency: Optional[str] = None,
    meeting_starts_at: str = "2026-08-20T18:00:00Z",
    meeting_ends_at: str = "2026-08-20T20:30:00Z",
    close_clock: str = "2026-10-10T09:00:00Z",
) -> FixtureState:
    """AREA_A application issued with one enforceable additional-control condition."""
    state = build_app_a_plan_open(
        api, meeting_starts_at=meeting_starts_at, meeting_ends_at=meeting_ends_at
    )
    add_condition(
        api,
        state,
        CONDITION_ADDITIONAL_CONTROL,
        reduction_tpy,
        enforceable=True,
        monitoring_frequency=monitoring_frequency,
    )
    set_clock(api, close_clock)
    close_plan(api, state)
    advance_to_decision(api, state)
    issue_permit(api, state, community_benefit_base_usd=community_benefit_base_usd)
    return state


# --- Other area chains -----------------------------------------------------


def build_area_b_two_applications(api: ApiClient) -> FixtureState:
    """AREA_B (severely overburdened) with two screened enhanced applications."""
    state = build_area(api, AREA_B_SPEC, AREA_B_INDICATORS)
    add_facility(
        api,
        state,
        dict(
            name="Kings Asphalt Terminal",
            facility_type=FACILITY_TYPE_MAJOR_SOURCE,
            distance_to_area_centroid_m=300,
        ),
        key="facility_b1_id",
    )
    add_facility(
        api,
        state,
        dict(
            name="Kings Medical Waste Incinerator",
            facility_type=FACILITY_TYPE_INCINERATOR,
            distance_to_area_centroid_m=600,
        ),
        key="facility_b2_id",
    )
    app_spec = dict(
        permit_type=PERMIT_TYPE_MODIFICATION,
        proposed_emissions_tpy=20.00,
        proposed_operating_hours_per_year=6000,
    )
    add_application(
        api, state, app_spec, facility_key="facility_b1_id", app_key="app_b1_id",
        submit=True, screen=True,
    )
    state["plan_b1_id"] = state.pop("plan_id")
    add_application(
        api, state, app_spec, facility_key="facility_b2_id", app_key="app_b2_id",
        submit=True, screen=True,
    )
    state["plan_b2_id"] = state.pop("plan_id")
    return state


def build_area_c_boundary_pair(api: ApiClient) -> FixtureState:
    """Two Fresno areas one hundredth apart, both one indicator short."""
    high = build_area(api, AREA_C_SPEC, AREA_C_INDICATORS)
    low = build_area(api, AREA_C_LOW_SPEC, AREA_C_LOW_INDICATORS)
    return {
        "area_c_id": high["area_id"],
        "area_c_version": high["area_version"],
        "area_c_low_id": low["area_id"],
        "area_c_low_version": low["area_version"],
    }


def build_area_d_standard_track(api: ApiClient) -> FixtureState:
    """AREA_D undesignated, with a minor source routed onto the standard track."""
    state = build_area(api, AREA_D_SPEC, AREA_D_INDICATORS)
    state["indicator_pm25_id"] = state["indicators"][0]["id"]
    add_facility(api, state, FACILITY_D_SPEC)
    add_application(
        api,
        state,
        dict(
            permit_type=PERMIT_TYPE_MODIFICATION,
            proposed_emissions_tpy=10.00,
            proposed_operating_hours_per_year=4000,
        ),
        submit=True,
        screen=True,
    )
    return state


def build_area_e_f_complaint_pool(api: ApiClient) -> FixtureState:
    """A Merced area whose complaints are all ineligible, plus an eligible neighbour."""
    state = build_area(api, AREA_E_SPEC)
    add_facility(
        api,
        state,
        dict(
            name="Merced Grain Dryer",
            facility_type=FACILITY_TYPE_MINOR_SOURCE,
            distance_to_area_centroid_m=2000,
        ),
        key="facility_e_id",
    )
    # Triaged but facility-less: never selectable.
    no_facility = add_complaint(
        api,
        state,
        "NOISE",
        "MEDIUM",
        "Night-time compressor noise, source not identified",
        resident=3,
        facility_key=None,
        key="complaint_no_facility_id",
    )
    triage_accept(api, no_facility["id"])
    # Dismissed out of the queue entirely.
    dismissed = add_complaint(
        api,
        state,
        "ODOR",
        "LOW",
        "Faint grain odor for one hour",
        resident=4,
        facility_key="facility_e_id",
        key="complaint_dismissed_id",
    )
    triage_dismiss(
        api, dismissed["id"], "Odor traced to off-site agricultural activity"
    )

    neighbour = build_area(api, AREA_F_SPEC)
    add_facility(
        api,
        neighbour,
        dict(
            name="Merced Coating Line",
            facility_type=FACILITY_TYPE_MINOR_SOURCE,
            distance_to_area_centroid_m=1200,
        ),
        key="facility_f_id",
    )
    eligible = add_complaint(
        api,
        neighbour,
        "ODOR",
        "MEDIUM",
        "Solvent odor at the property line each afternoon",
        resident=5,
        facility_key="facility_f_id",
        key="complaint_f_id",
    )
    triage_accept(api, eligible["id"])

    state["area_f_id"] = neighbour["area_id"]
    state["facility_f_id"] = neighbour["facility_f_id"]
    state["complaint_f_id"] = neighbour["complaint_f_id"]
    return state


def build_area_g_facility(api: ApiClient) -> FixtureState:
    """A bare Madera area with one minor source and no indicators."""
    state = build_area(api, AREA_G_SPEC)
    add_facility(
        api,
        state,
        dict(
            name="Madera Cabinet Shop",
            facility_type=FACILITY_TYPE_MINOR_SOURCE,
            distance_to_area_centroid_m=1500,
        ),
    )
    return state


def build_area_h(api: ApiClient) -> FixtureState:
    """A bare Madera area used to probe indicator-filing validation."""
    return build_area(api, AREA_H_SPEC)


def build_area_i_pending_decision(api: ApiClient) -> FixtureState:
    """A standard-track application in PENDING_DECISION whose area cap is tiny."""
    state = build_area(api, AREA_I_SPEC)
    add_facility(
        api,
        state,
        dict(
            name="Madera Grain Dryer",
            facility_type=FACILITY_TYPE_MINOR_SOURCE,
            distance_to_area_centroid_m=1500,
        ),
    )
    add_application(
        api,
        state,
        dict(
            permit_type=PERMIT_TYPE_MODIFICATION,
            proposed_emissions_tpy=20.00,
            proposed_operating_hours_per_year=4000,
        ),
        submit=True,
        screen=True,
    )
    advance_to_decision(api, state)
    return state


def build_area_j_pending_decision(api: ApiClient) -> FixtureState:
    """A standard-track application in PENDING_DECISION with a clean record."""
    state = build_area(api, AREA_J_SPEC)
    add_facility(
        api,
        state,
        dict(
            name="Madera Sign Shop",
            facility_type=FACILITY_TYPE_MINOR_SOURCE,
            distance_to_area_centroid_m=1500,
        ),
    )
    add_application(
        api,
        state,
        dict(
            permit_type=PERMIT_TYPE_MODIFICATION,
            proposed_emissions_tpy=10.00,
            proposed_operating_hours_per_year=2000,
        ),
        submit=True,
        screen=True,
    )
    advance_to_decision(api, state)
    return state


def build_area_k_screened(api: ApiClient, with_venue: bool = False) -> FixtureState:
    """The compact enhanced-track scenario: an undesignated area with a major source.

    Only the facility-type trigger fires, so the plan's required comment days
    stay at the base figure and the screening-level assessment runs against a
    zero baseline burden score.
    """
    state = build_area(api, AREA_K_SPEC)
    add_facility(
        api,
        state,
        dict(
            name="Madera Asphalt Plant",
            facility_type=FACILITY_TYPE_MAJOR_SOURCE,
            distance_to_area_centroid_m=1500,
        ),
    )
    if with_venue:
        state["venue_id"] = create_venue(api, **VENUE_K_SPEC)["id"]
    add_application(
        api,
        state,
        dict(
            permit_type=PERMIT_TYPE_NEW_SOURCE,
            proposed_emissions_tpy=20.00,
            proposed_operating_hours_per_year=4000,
        ),
        submit=True,
        screen=True,
    )
    return state


def build_area_k_assessment_accepted(api: ApiClient, with_venue: bool = False) -> FixtureState:
    """AREA_K screened application carrying an ACCEPTED screening assessment."""
    state = build_area_k_screened(api, with_venue=with_venue)
    accept_screening_assessment(api, state)
    return state


def build_area_l_comment_scenario(api: ApiClient) -> FixtureState:
    """A Spanish-required Fresno plan that receives a Vietnamese comment."""
    state = build_area(api, AREA_L_SPEC)
    add_facility(
        api,
        state,
        dict(
            name="Fresno Metal Coating",
            facility_type=FACILITY_TYPE_MAJOR_SOURCE,
            distance_to_area_centroid_m=1500,
        ),
    )
    state["venue_id"] = create_venue(api, **VENUE_L_SPEC)["id"]
    add_application(
        api,
        state,
        dict(
            permit_type=PERMIT_TYPE_NEW_SOURCE,
            proposed_emissions_tpy=20.00,
            proposed_operating_hours_per_year=4000,
        ),
        submit=True,
        screen=True,
    )
    translate_plan(api, state, languages=["es"], materials_translated=True)
    open_plan(api, state, "2026-08-01")
    add_meeting(api, state, "2026-08-20T18:00:00Z", "2026-08-20T20:00:00Z", ["es"])
    get_success_data(
        api.create_public_comment(
            build.public_comment_payload(
                participation_plan_id=state["plan_id"],
                submitter_name="Tran Minh",
                language="vi",
                body="Khoi bui tu nha may lam tre em bi ho.",
            ),
            resident_headers(9),
        )
    )
    return state


def build_area_m_facility(api: ApiClient) -> FixtureState:
    """A Kings area with one feed mill, used for complaint and inspection load."""
    state = build_area(api, AREA_M_SPEC)
    add_facility(
        api,
        state,
        dict(
            name="Hanford Feed Mill",
            facility_type=FACILITY_TYPE_MINOR_SOURCE,
            distance_to_area_centroid_m=1200,
        ),
    )
    return state


# ---------------------------------------------------------------------------
# 5. pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def clock(api: ApiClient) -> str:
    """Pin the logical clock to its declared default before the test runs."""
    set_clock(api, DEFAULT_CLOCK_UTC)
    return DEFAULT_CLOCK_UTC


# --- AREA_A tiers ----------------------------------------------------------


@pytest.fixture
def area_a(api: ApiClient, clock: str) -> FixtureState:
    return build_area_a(api)


@pytest.fixture
def area_a_facility(api: ApiClient, clock: str) -> FixtureState:
    state = build_area_a(api)
    add_facility(api, state, FACILITY_A_SPEC)
    return state


@pytest.fixture
def app_a_screened(api: ApiClient, clock: str) -> FixtureState:
    return build_app_a_screened(api)


@pytest.fixture
def app_a_screening_assessment(api: ApiClient, clock: str) -> FixtureState:
    """A screened AREA_A application with one DRAFT screening-level assessment."""
    state = build_app_a_screened(api)
    add_assessment(api, state, method=METHOD_SCREENING_LEVEL)
    return state


@pytest.fixture
def app_a_assessment_accepted(api: ApiClient, clock: str) -> FixtureState:
    return build_app_a_assessment_accepted(api)


@pytest.fixture
def app_a_plan_open(api: ApiClient, clock: str) -> FixtureState:
    return build_app_a_plan_open(api)


@pytest.fixture
def app_a_plan_open_draft_assessment(api: ApiClient, clock: str) -> FixtureState:
    """Plan open and meeting booked, but the assessment is still a DRAFT."""
    return build_app_a_plan_open(api, accepted=False)


@pytest.fixture
def app_a_pending_decision(api: ApiClient, clock: str) -> FixtureState:
    return build_app_a_pending_decision(api)


@pytest.fixture
def app_a_issued(api: ApiClient, clock: str) -> FixtureState:
    return build_app_a_issued(api, monitoring_frequency="QUARTERLY")


@pytest.fixture
def area_a_inspection_pending(api: ApiClient, clock: str) -> FixtureState:
    """AREA_A with a triaged odour complaint already assigned to an inspector."""
    state = build_area_a(api)
    add_facility(api, state, FACILITY_A_SPEC)
    complaint = add_complaint(
        api,
        state,
        "ODOR",
        "HIGH",
        "Rendering odor overnight for three consecutive nights",
        resident=1,
        submitter_language="es",
    )
    triage_accept(api, complaint["id"])
    assign_next(api, state, "insp-1", "2026-08-05", narrow_to_area=True)
    return state


# --- Other named areas -----------------------------------------------------


@pytest.fixture
def area_b_two_applications(api: ApiClient, clock: str) -> FixtureState:
    return build_area_b_two_applications(api)


@pytest.fixture
def area_c_boundary_pair(api: ApiClient, clock: str) -> FixtureState:
    return build_area_c_boundary_pair(api)


@pytest.fixture
def area_d_standard_track(api: ApiClient, clock: str) -> FixtureState:
    return build_area_d_standard_track(api)


@pytest.fixture
def area_e_f_complaint_pool(api: ApiClient, clock: str) -> FixtureState:
    return build_area_e_f_complaint_pool(api)


@pytest.fixture
def area_g(api: ApiClient, clock: str) -> FixtureState:
    return build_area(api, AREA_G_SPEC)


@pytest.fixture
def area_g_facility(api: ApiClient, clock: str) -> FixtureState:
    return build_area_g_facility(api)


@pytest.fixture
def area_h(api: ApiClient, clock: str) -> FixtureState:
    return build_area_h(api)


@pytest.fixture
def area_i_pending_decision(api: ApiClient, clock: str) -> FixtureState:
    return build_area_i_pending_decision(api)


@pytest.fixture
def area_j_pending_decision(api: ApiClient, clock: str) -> FixtureState:
    return build_area_j_pending_decision(api)


@pytest.fixture
def area_k_screened(api: ApiClient, clock: str) -> FixtureState:
    return build_area_k_screened(api)


@pytest.fixture
def area_k_screened_with_venue(api: ApiClient, clock: str) -> FixtureState:
    return build_area_k_screened(api, with_venue=True)


@pytest.fixture
def area_k_assessment_accepted(api: ApiClient, clock: str) -> FixtureState:
    return build_area_k_assessment_accepted(api)


@pytest.fixture
def area_k_draft_application(api: ApiClient, clock: str) -> FixtureState:
    """AREA_K with a DRAFT application and a second, unrelated facility."""
    state = build_area(api, AREA_K_SPEC)
    add_facility(
        api,
        state,
        dict(
            name="Madera Asphalt Plant",
            facility_type=FACILITY_TYPE_MAJOR_SOURCE,
            distance_to_area_centroid_m=1500,
        ),
    )
    add_facility(
        api,
        state,
        dict(
            name="Madera Print Works",
            facility_type="AUTO_BODY_SHOP",
            distance_to_area_centroid_m=1700,
        ),
        key="facility_other_id",
    )
    add_application(
        api,
        state,
        dict(
            permit_type=PERMIT_TYPE_NEW_SOURCE,
            proposed_emissions_tpy=20.00,
            proposed_operating_hours_per_year=4000,
        ),
    )
    return state


@pytest.fixture
def area_k_submitted_application(api: ApiClient, clock: str) -> FixtureState:
    """AREA_K with a SUBMITTED, not yet screened application."""
    state = build_area(api, AREA_K_SPEC)
    add_facility(
        api,
        state,
        dict(
            name="Madera Asphalt Plant",
            facility_type=FACILITY_TYPE_MAJOR_SOURCE,
            distance_to_area_centroid_m=1500,
        ),
    )
    add_application(
        api,
        state,
        dict(
            permit_type=PERMIT_TYPE_NEW_SOURCE,
            proposed_emissions_tpy=20.00,
            proposed_operating_hours_per_year=4000,
        ),
        submit=True,
    )
    return state


@pytest.fixture
def area_l_comment_scenario(api: ApiClient, clock: str) -> FixtureState:
    return build_area_l_comment_scenario(api)


@pytest.fixture
def area_m_facility(api: ApiClient, clock: str) -> FixtureState:
    return build_area_m_facility(api)


@pytest.fixture
def venue_pair(api: ApiClient, clock: str) -> Dict[str, str]:
    """One decommissioned hall and one active hall, both fully accessible."""
    decommissioned = create_venue(
        api,
        name="Old Lamont Annex",
        address="120 Depot Rd, Lamont CA",
        capacity=90,
        status=VENUE_DECOMMISSIONED,
    )
    active = create_venue(api, **VENUE_A_SPEC, status=VENUE_ACTIVE)
    return {
        "venue_decommissioned_id": decommissioned["id"],
        "venue_active_id": active["id"],
    }
