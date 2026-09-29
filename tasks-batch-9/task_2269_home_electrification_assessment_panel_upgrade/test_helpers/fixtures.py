"""Composite setup helpers and pytest fixtures.

Every test starts against an empty database, so each helper builds its
preconditions from scratch using only the endpoints of §4. The step functions
below mirror the workflow order of §3.1-§3.9 and `build_world` walks that ladder
as far as a test needs.

Identity is threaded explicitly: `Applicant` calls carry the household's own id,
`Contractor` calls the contractor's own id and `FieldInspector` calls the
inspector's own id, as §2.1 requires of the entity-backed roles.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    DEFAULT_CLOCK_UTC,
    MEASURE_HP_HVAC,
    MEASURE_HPWH,
    MEASURE_PANEL_200A,
)
from .factories import (
    build_assessment_decision_payload,
    build_assessment_measure,
    build_assessment_payload,
    build_contractor_payload,
    build_enrollment_decision_payload,
    build_hvac_heat_pump_payload,
    build_household_payload,
    build_income_verification_payload,
    build_inspection_payload,
    build_inspector_payload,
    build_installation_payload,
    build_measure_result,
    build_open_status_payload,
    build_panel_200a_payload,
    build_pass_result_payload,
    build_program_payload,
    build_project_measure,
    build_project_payload,
    build_project_review_payload,
    build_reservation_payload,
    build_suspension_payload,
    build_verify_decision_payload,
    build_water_heater_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    REVIEWER_HEADERS,
    REVIEWER_TWO_HEADERS,
    make_applicant_headers,
    make_contractor_headers,
    make_field_inspector_headers,
)
from .types import (
    AssessmentDecision,
    EnrollmentDecision,
    InspectionType,
    ProgramStatus,
    ProjectReviewDecision,
    SuspensionAction,
)

# --------------------------------------------------------------------------- #
# Client fixture
# --------------------------------------------------------------------------- #


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the runner-provided base URL."""
    return ApiClient()


# --------------------------------------------------------------------------- #
# Clock (§2.5)
# --------------------------------------------------------------------------- #


def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock; returns the clock response payload."""
    return get_success_data(api.set_clock(current_utc, ADMIN_HEADERS))


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    """Return the logical clock to the instant it reads before any manipulation."""
    return set_clock(api, DEFAULT_CLOCK_UTC)


# --------------------------------------------------------------------------- #
# Tier 1 — programs and catalog (§3.1)
# --------------------------------------------------------------------------- #


def create_draft_program(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A program in DRAFT."""
    return get_success_data(
        api.create_program(build_program_payload(**overrides), ADMIN_HEADERS)
    )


def open_program(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """Drive DRAFT -> OPEN and return the refreshed program."""
    return get_success_data(
        api.set_program_status(program_id, build_open_status_payload(**overrides), ADMIN_HEADERS)
    )


def create_open_program(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A program in OPEN with its appropriation fully available."""
    program = create_draft_program(api, **overrides)
    return open_program(api, program["id"])


def set_program_status(api: ApiClient, program_id: str, new_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"new_status": new_status}
    payload.update(overrides)
    return get_success_data(api.set_program_status(program_id, payload, ADMIN_HEADERS))


def add_catalog_item(
    api: ApiClient, program_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    return get_success_data(api.create_catalog_item(program_id, payload, ADMIN_HEADERS))


DEFAULT_CATALOG_BUILDERS = (
    build_hvac_heat_pump_payload,
    build_water_heater_payload,
    build_panel_200a_payload,
)


def add_catalog(
    api: ApiClient,
    program_id: str,
    payloads: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Create catalog items and return them keyed by `measure_code`."""
    if payloads is None:
        payloads = [builder() for builder in DEFAULT_CATALOG_BUILDERS]
    catalog: Dict[str, Dict[str, Any]] = {}
    for payload in payloads:
        item = add_catalog_item(api, program_id, payload)
        catalog[item["measure_code"]] = item
    return catalog


def read_program(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_program(program_id, REVIEWER_HEADERS))


def program_version(api: ApiClient, program_id: str) -> int:
    return read_program(api, program_id)["version"]


def sweep(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.sweep_program(program_id, ADMIN_HEADERS))


# --------------------------------------------------------------------------- #
# Tier 1 — households and income tier (§3.2)
# --------------------------------------------------------------------------- #


def create_household(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """An intake record with a null tier and zeroed cap balances."""
    return get_success_data(
        api.create_household(build_household_payload(program_id, **overrides), ADMIN_HEADERS)
    )


def file_income_verification(
    api: ApiClient, household_id: str, **overrides: Any
) -> Dict[str, Any]:
    """File a packet as the owning Applicant, leaving it in SUBMITTED."""
    return get_success_data(
        api.create_income_verification(
            household_id,
            build_income_verification_payload(**overrides),
            make_applicant_headers(household_id),
        )
    )


def verify_income_verification(
    api: ApiClient, verification_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Record VERIFY, which runs the tier assignment onto the household."""
    return get_success_data(
        api.verify_income_verification(
            verification_id,
            build_verify_decision_payload(**overrides),
            headers or REVIEWER_HEADERS,
        )
    )


def create_verified_household(
    api: ApiClient,
    program_id: str,
    income_overrides: Optional[Dict[str, Any]] = None,
    **household_overrides: Any,
) -> Dict[str, Any]:
    """A household holding a VERIFIED verification, so a tier and cap exist.

    Returns `{household, income_verification}` with the household re-read after
    the tier assignment.
    """
    household = create_household(api, program_id, **household_overrides)
    verification = file_income_verification(
        api, household["id"], **(income_overrides or {})
    )
    verify_income_verification(api, verification["id"])
    return {
        "household": read_household(api, household["id"]),
        "income_verification": read_income_verification(api, household["id"], verification["id"]),
    }


def read_household(api: ApiClient, household_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_household(household_id, REVIEWER_HEADERS))


def household_version(api: ApiClient, household_id: str) -> int:
    return read_household(api, household_id)["version"]


def read_income_verification(
    api: ApiClient, household_id: str, verification_id: str
) -> Dict[str, Any]:
    rows, _meta = _paginated(api.list_income_verifications(household_id, REVIEWER_HEADERS))
    for row in rows:
        if row["id"] == verification_id:
            return row
    raise AssertionError(
        f"Income verification {verification_id} not present on household {household_id}"
    )


# --------------------------------------------------------------------------- #
# Tier 1 — contractors and inspectors (§3.3)
# --------------------------------------------------------------------------- #


def create_contractor(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """An application in PENDING_ENROLLMENT."""
    return get_success_data(
        api.create_contractor(build_contractor_payload(program_id, **overrides), ADMIN_HEADERS)
    )


def decide_enrollment(
    api: ApiClient, contractor_id: str, decision: str = EnrollmentDecision.APPROVE, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_contractor_enrollment(
            contractor_id,
            build_enrollment_decision_payload(decision, **overrides),
            REVIEWER_HEADERS,
        )
    )


def create_enrolled_contractor(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """A contractor in ENROLLED_ACTIVE with a rolling quality score of 100."""
    contractor = create_contractor(api, program_id, **overrides)
    return decide_enrollment(api, contractor["id"])


def suspend_contractor(api: ApiClient, contractor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.set_contractor_suspension(
            contractor_id, build_suspension_payload(SuspensionAction.SUSPEND, **overrides), ADMIN_HEADERS
        )
    )


def reinstate_contractor(api: ApiClient, contractor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.set_contractor_suspension(
            contractor_id,
            build_suspension_payload(SuspensionAction.REINSTATE, **overrides),
            ADMIN_HEADERS,
        )
    )


def read_contractor(api: ApiClient, contractor_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contractor(contractor_id, REVIEWER_HEADERS))


def read_quality_review(api: ApiClient, contractor_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contractor_quality_review(contractor_id, REVIEWER_HEADERS))


def create_inspector(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_inspector(build_inspector_payload(program_id, **overrides), ADMIN_HEADERS)
    )


# --------------------------------------------------------------------------- #
# Tier 2 — assessments (§3.4)
# --------------------------------------------------------------------------- #


def create_assessment(
    api: ApiClient,
    household_id: str,
    contractor_id: str,
    measures: Optional[List[Dict[str, Any]]] = None,
    expected_household_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record an assessment as the owning contractor, reading the household
    version first so the §2.8 concurrency token matches."""
    version = (
        expected_household_version
        if expected_household_version is not None
        else household_version(api, household_id)
    )
    payload = build_assessment_payload(
        household_id, contractor_id, version, measures, **overrides
    )
    return get_success_data(
        api.create_assessment(payload, make_contractor_headers(contractor_id))
    )


def decide_assessment(
    api: ApiClient, assessment_id: str, decision: str = AssessmentDecision.APPROVE, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.review_assessment(
            assessment_id,
            build_assessment_decision_payload(decision, **overrides),
            REVIEWER_HEADERS,
        )
    )


def create_approved_assessment(
    api: ApiClient,
    household_id: str,
    contractor_id: str,
    measures: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    assessment = create_assessment(
        api, household_id, contractor_id, measures, **overrides
    )
    return decide_assessment(api, assessment["id"])


def read_assessment(api: ApiClient, assessment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_assessment(assessment_id, REVIEWER_HEADERS))


def read_eligible_measures(api: ApiClient, assessment_id: str, **params: Any) -> List[Dict[str, Any]]:
    rows, _meta = _paginated(
        api.list_eligible_measures(assessment_id, REVIEWER_HEADERS, params or None)
    )
    return rows


# --------------------------------------------------------------------------- #
# Tier 3 — projects (§3.5, §3.6)
# --------------------------------------------------------------------------- #


def create_project(
    api: ApiClient,
    household_id: str,
    assessment_id: str,
    contractor_id: str,
    income_verification_id: str,
    measures: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a project in DRAFT as the contractor of record."""
    payload = build_project_payload(
        household_id,
        assessment_id,
        contractor_id,
        income_verification_id,
        measures,
        **overrides,
    )
    return get_success_data(
        api.create_rebate_project(payload, make_contractor_headers(contractor_id))
    )


def submit_project(
    api: ApiClient,
    project_id: str,
    contractor_id: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_rebate_project(project_id, make_contractor_headers(contractor_id), payload)
    )


def review_project(
    api: ApiClient,
    project_id: str,
    decision: str = ProjectReviewDecision.APPROVE,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.review_rebate_project(
            project_id,
            build_project_review_payload(decision, **overrides),
            headers or REVIEWER_HEADERS,
        )
    )


def reserve_project(
    api: ApiClient,
    project_id: str,
    program_id: str,
    headers: Optional[Dict[str, str]] = None,
    expected_program_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Encumber the appropriation. The acting reviewer must differ from the one
    who recorded the review decision, per §2.9."""
    version = (
        expected_program_version
        if expected_program_version is not None
        else program_version(api, program_id)
    )
    return get_success_data(
        api.create_reservation(
            project_id,
            build_reservation_payload(version, **overrides),
            headers or REVIEWER_TWO_HEADERS,
        )
    )


def read_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rebate_project(project_id, REVIEWER_HEADERS))


def read_project_measures(api: ApiClient, project_id: str, **params: Any) -> List[Dict[str, Any]]:
    rows, _meta = _paginated(
        api.list_project_measures(project_id, REVIEWER_HEADERS, params or None)
    )
    return rows


def read_quote(api: ApiClient, project_id: str, variant: Optional[str] = None) -> Dict[str, Any]:
    params = {"variant": variant} if variant else None
    return get_success_data(api.get_incentive_quote(project_id, REVIEWER_HEADERS, params))


def read_reservation(api: ApiClient, reservation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_reservation(reservation_id, REVIEWER_HEADERS))


def project_reservation(api: ApiClient, project_id: str) -> Dict[str, Any]:
    """The single reservation of a project, whatever status it now holds."""
    rows, _meta = _paginated(
        api.list_reservations(REVIEWER_HEADERS, {"project_id": project_id})
    )
    assert len(rows) == 1, f"Expected one reservation for project {project_id}, got {len(rows)}"
    return rows[0]


# --------------------------------------------------------------------------- #
# Tier 4 — installation, inspection, payment (§3.7-§3.9)
# --------------------------------------------------------------------------- #


def report_installation(
    api: ApiClient,
    project_id: str,
    contractor_id: str,
    measure_results: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = build_installation_payload(measure_results, **overrides)
    return get_success_data(
        api.report_installation(project_id, payload, make_contractor_headers(contractor_id))
    )


def schedule_inspection(
    api: ApiClient,
    project_id: str,
    inspector_id: str,
    inspection_type: str = InspectionType.POST_INSTALL,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = build_inspection_payload(project_id, inspector_id, inspection_type, **overrides)
    return get_success_data(api.create_inspection(payload, headers or REVIEWER_HEADERS))


def record_result(
    api: ApiClient, inspection_id: str, inspector_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    return get_success_data(
        api.record_inspection_result(
            inspection_id, payload, make_field_inspector_headers(inspector_id)
        )
    )


def cancel_inspection(api: ApiClient, inspection_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.cancel_inspection(inspection_id, REVIEWER_HEADERS, overrides or None))


def read_inspection(api: ApiClient, inspection_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_inspection(inspection_id, REVIEWER_HEADERS))


def open_remediation(
    api: ApiClient, project_id: str, contractor_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.open_remediation(
            project_id, make_contractor_headers(contractor_id), overrides or None
        )
    )


def declare_stacking(
    api: ApiClient,
    project_id: str,
    household_id: str,
    utility_rebate_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "utility_program_name": "Xcel Home Electrification",
        "utility_rebate_cents": utility_rebate_cents,
    }
    payload.update(overrides)
    return get_success_data(
        api.create_stacking_declaration(
            project_id, payload, make_applicant_headers(household_id)
        )
    )


def pay_project(
    api: ApiClient, project_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.disburse_payment(project_id, headers or REVIEWER_TWO_HEADERS, overrides or None)
    )


def read_clawback_actions(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    rows, _meta = _paginated(api.list_clawback_actions(REVIEWER_HEADERS, params or None))
    return rows


# --------------------------------------------------------------------------- #
# The world ladder
# --------------------------------------------------------------------------- #

STAGES = (
    "program",
    "household",
    "contractor",
    "assessment",
    "project",
    "submitted",
    "approved",
    "reserved",
    "installed",
    "inspection_scheduled",
    "verified",
    "paid",
)

DEFAULT_ASSESSMENT_MEASURES = [
    build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
]


def build_world(
    api: ApiClient,
    stage: str = "reserved",
    program_overrides: Optional[Dict[str, Any]] = None,
    catalog: Optional[List[Dict[str, Any]]] = None,
    household_overrides: Optional[Dict[str, Any]] = None,
    income_overrides: Optional[Dict[str, Any]] = None,
    contractor_overrides: Optional[Dict[str, Any]] = None,
    assessed_panel_amps: int = 200,
    assessment_measures: Optional[List[Dict[str, Any]]] = None,
    assessment_overrides: Optional[Dict[str, Any]] = None,
    approve_assessment: bool = True,
    project_measures: Optional[List[Dict[str, Any]]] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
    installation_overrides: Optional[Dict[str, Any]] = None,
    measure_results: Optional[List[Dict[str, Any]]] = None,
    inspection_type: str = InspectionType.POST_INSTALL,
    inspection_overrides: Optional[Dict[str, Any]] = None,
    result_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Walk the workflow of §3.1-§3.9 up to `stage` and return every record made.

    The returned mapping always carries `program` and `catalog`; later keys
    (`household`, `income_verification`, `contractor`, `assessment`, `project`,
    `reservation`, `inspector`, `inspection`) appear once their stage is reached,
    along with ready-made `applicant_headers`, `contractor_headers` and
    `inspector_headers`.
    """
    assert stage in STAGES, f"Unknown stage {stage!r}; expected one of {STAGES}"
    reached = STAGES.index(stage)

    world: Dict[str, Any] = {}

    program = create_open_program(api, **(program_overrides or {}))
    world["program"] = program
    world["program_id"] = program["id"]
    world["catalog"] = add_catalog(api, program["id"], catalog)
    if reached == STAGES.index("program"):
        return world

    verified = create_verified_household(
        api, program["id"], income_overrides, **(household_overrides or {})
    )
    world["household"] = verified["household"]
    world["household_id"] = verified["household"]["id"]
    world["income_verification"] = verified["income_verification"]
    world["applicant_headers"] = make_applicant_headers(verified["household"]["id"])
    if reached == STAGES.index("household"):
        return world

    contractor = create_enrolled_contractor(
        api, program["id"], **(contractor_overrides or {})
    )
    world["contractor"] = contractor
    world["contractor_id"] = contractor["id"]
    world["contractor_headers"] = make_contractor_headers(contractor["id"])
    if reached == STAGES.index("contractor"):
        return world

    measures = (
        assessment_measures if assessment_measures is not None else DEFAULT_ASSESSMENT_MEASURES
    )
    assessment = create_assessment(
        api,
        world["household_id"],
        contractor["id"],
        measures,
        assessed_panel_amps=assessed_panel_amps,
        **(assessment_overrides or {}),
    )
    if approve_assessment:
        assessment = decide_assessment(api, assessment["id"])
    world["assessment"] = assessment
    world["assessment_id"] = assessment["id"]
    if reached == STAGES.index("assessment"):
        return world

    lines = (
        project_measures
        if project_measures is not None
        else [
            build_project_measure(
                entry["measure_code"],
                entry["proposed_quantity"],
                entry["estimated_cost_cents"],
            )
            for entry in measures
        ]
    )
    project_kwargs: Dict[str, Any] = {
        "estimated_project_cost_cents": sum(line["estimated_cost_cents"] for line in lines) or 1
    }
    project_kwargs.update(project_overrides or {})
    project = create_project(
        api,
        world["household_id"],
        assessment["id"],
        contractor["id"],
        world["income_verification"]["id"],
        lines,
        **project_kwargs,
    )
    world["project"] = project
    world["project_id"] = project["id"]
    if reached == STAGES.index("project"):
        return world

    world["project"] = submit_project(api, project["id"], contractor["id"])
    if reached == STAGES.index("submitted"):
        return world

    world["project"] = review_project(api, project["id"])
    if reached == STAGES.index("approved"):
        return world

    reservation = reserve_project(api, project["id"], program["id"])
    world["reservation"] = reservation
    world["reservation_id"] = reservation["id"]
    world["project"] = read_project(api, project["id"])
    world["program"] = read_program(api, program["id"])
    world["household"] = read_household(api, world["household_id"])
    if reached == STAGES.index("reserved"):
        return world

    install_kwargs: Dict[str, Any] = dict(installation_overrides or {})
    results = (
        measure_results
        if measure_results is not None
        else [build_measure_result(line["measure_code"], line["planned_quantity"]) for line in lines]
    )
    install_kwargs.setdefault(
        "actual_project_cost_cents", sum(entry["actual_cost_cents"] for entry in results) or 1
    )
    world["project"] = report_installation(
        api, project["id"], contractor["id"], results, **install_kwargs
    )
    if reached == STAGES.index("installed"):
        return world

    inspector = create_inspector(api, program["id"])
    world["inspector"] = inspector
    world["inspector_id"] = inspector["id"]
    world["inspector_headers"] = make_field_inspector_headers(inspector["id"])
    inspection = schedule_inspection(
        api,
        project["id"],
        inspector["id"],
        inspection_type,
        **(inspection_overrides or {}),
    )
    world["inspection"] = inspection
    world["inspection_id"] = inspection["id"]
    if reached == STAGES.index("inspection_scheduled"):
        return world

    world["inspection"] = record_result(
        api, inspection["id"], inspector["id"], result_payload or build_pass_result_payload()
    )
    world["project"] = read_project(api, project["id"])
    if reached == STAGES.index("verified"):
        return world

    world["project"] = pay_project(api, project["id"])
    world["program"] = read_program(api, program["id"])
    world["household"] = read_household(api, world["household_id"])
    world["reservation"] = read_reservation(api, reservation["id"])
    return world


def refresh(api: ApiClient, world: Dict[str, Any]) -> Dict[str, Any]:
    """Re-read every record a world holds, so cascades become visible."""
    world["program"] = read_program(api, world["program_id"])
    if "household_id" in world:
        world["household"] = read_household(api, world["household_id"])
    if "contractor_id" in world:
        world["contractor"] = read_contractor(api, world["contractor_id"])
    if "assessment_id" in world:
        world["assessment"] = read_assessment(api, world["assessment_id"])
    if "project_id" in world:
        world["project"] = read_project(api, world["project_id"])
    if "reservation_id" in world:
        world["reservation"] = read_reservation(api, world["reservation_id"])
    if "inspection_id" in world:
        world["inspection"] = read_inspection(api, world["inspection_id"])
    return world


# --------------------------------------------------------------------------- #
# Canonical pytest fixtures
# --------------------------------------------------------------------------- #

FULL_CATALOG_BUILDERS = (
    build_hvac_heat_pump_payload,
    build_water_heater_payload,
    build_panel_200a_payload,
)

#  The electrification package the money-path fixtures use: a heat pump, a heat
#  pump water heater and the 200 A service upgrade that powers them.
ELECTRIFICATION_ASSESSMENT_MEASURES = [
    build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
    build_assessment_measure(MEASURE_HPWH, 1, 300000),
    build_assessment_measure(MEASURE_PANEL_200A, 1, 600000),
]


@pytest.fixture
def open_program_world(api: ApiClient) -> Dict[str, Any]:
    """An OPEN program carrying the shared catalog."""
    return build_world(api, stage="program")


@pytest.fixture
def household_world(api: ApiClient) -> Dict[str, Any]:
    """Adds a household verified at exactly 80.0 percent AMI, so tier LOW."""
    return build_world(api, stage="household")


@pytest.fixture
def contractor_world(api: ApiClient) -> Dict[str, Any]:
    """Adds an ENROLLED_ACTIVE contractor."""
    return build_world(api, stage="contractor")


@pytest.fixture
def assessment_world(api: ApiClient) -> Dict[str, Any]:
    """Adds an APPROVED single-line assessment."""
    return build_world(api, stage="assessment")


@pytest.fixture
def project_world(api: ApiClient) -> Dict[str, Any]:
    """Adds a DRAFT project carrying one heat-pump line."""
    return build_world(api, stage="project")


@pytest.fixture
def approved_project_world(api: ApiClient) -> Dict[str, Any]:
    """Adds submission and an APPROVE review decision."""
    return build_world(api, stage="approved")


@pytest.fixture
def reserved_project_world(api: ApiClient) -> Dict[str, Any]:
    """Adds the reservation that encumbers 800000 of the appropriation."""
    return build_world(api, stage="reserved")


@pytest.fixture
def installed_project_world(api: ApiClient) -> Dict[str, Any]:
    """Adds an installation report with an actual cost of 700000."""
    return build_world(
        api,
        stage="installed",
        measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
    )


@pytest.fixture
def scheduled_inspection_world(api: ApiClient) -> Dict[str, Any]:
    """Adds an inspector and a SCHEDULED POST_INSTALL inspection."""
    return build_world(
        api,
        stage="inspection_scheduled",
        measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
    )


@pytest.fixture
def verified_project_world(api: ApiClient) -> Dict[str, Any]:
    """Adds a passing POST_INSTALL result, so the project is VERIFIED."""
    return build_world(
        api,
        stage="verified",
        measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
    )


@pytest.fixture
def paid_project_world(api: ApiClient) -> Dict[str, Any]:
    """Adds disbursement, so the project is PAID and the reservation COMMITTED."""
    return build_world(
        api,
        stage="paid",
        measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
    )


# --------------------------------------------------------------------------- #
# Internal
# --------------------------------------------------------------------------- #


def _paginated(response: Any) -> Any:
    """Read a list response during setup without asserting the exact envelope."""
    body = get_success_data(response)
    meta = response.json().get("meta", {})
    return body, meta


__all__ = [
    "api",
    "set_clock",
    "reset_clock",
    "create_draft_program",
    "open_program",
    "create_open_program",
    "set_program_status",
    "add_catalog_item",
    "add_catalog",
    "read_program",
    "program_version",
    "sweep",
    "create_household",
    "file_income_verification",
    "verify_income_verification",
    "create_verified_household",
    "read_household",
    "household_version",
    "read_income_verification",
    "create_contractor",
    "decide_enrollment",
    "create_enrolled_contractor",
    "suspend_contractor",
    "reinstate_contractor",
    "read_contractor",
    "read_quality_review",
    "create_inspector",
    "create_assessment",
    "decide_assessment",
    "create_approved_assessment",
    "read_assessment",
    "read_eligible_measures",
    "create_project",
    "submit_project",
    "review_project",
    "reserve_project",
    "read_project",
    "read_project_measures",
    "read_quote",
    "read_reservation",
    "project_reservation",
    "report_installation",
    "schedule_inspection",
    "record_result",
    "cancel_inspection",
    "read_inspection",
    "open_remediation",
    "declare_stacking",
    "pay_project",
    "read_clawback_actions",
    "build_world",
    "refresh",
    "STAGES",
    "ELECTRIFICATION_ASSESSMENT_MEASURES",
    "open_program_world",
    "household_world",
    "contractor_world",
    "assessment_world",
    "project_world",
    "approved_project_world",
    "reserved_project_world",
    "installed_project_world",
    "scheduled_inspection_world",
    "verified_project_world",
    "paid_project_world",
]
