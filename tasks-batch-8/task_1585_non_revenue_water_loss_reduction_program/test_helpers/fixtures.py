"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch through the public API (the
server restarts before each test, so no state carries over). Setup calls use
the lenient get_success_data() validator so a setup failure surfaces as a
clear "Setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    DEFAULTS,
    create_benchmark_report_payload,
    create_case_payload,
    create_customer_meter_payload,
    create_dma_payload,
    create_intervention_proposal_payload,
    create_leak_payload,
    create_leak_survey_payload,
    create_meter_accuracy_test_payload,
    create_night_flow_assessment_payload,
    create_pressure_project_payload,
    create_water_balance_period_payload,
)
from .test_users import (
    make_field_supervisor_headers,
    make_investigator_headers,
    make_meter_technician_headers,
    make_program_director_headers,
    make_regulator_liaison_headers,
    make_utility_analyst_headers,
)

PD = TEST_DEFAULTS["PROGRAM_DIRECTOR"]
UA = TEST_DEFAULTS["UTILITY_ANALYST"]
UA2 = TEST_DEFAULTS["UTILITY_ANALYST_ALT"]
FS = TEST_DEFAULTS["FIELD_SUPERVISOR"]
FS2 = TEST_DEFAULTS["FIELD_SUPERVISOR_ALT"]
MT = TEST_DEFAULTS["METER_TECHNICIAN"]
INV = TEST_DEFAULTS["INVESTIGATOR"]
RL = TEST_DEFAULTS["REGULATOR_LIAISON"]


# ─── Tier 1/2: DMAs and water balances ────────────────

def create_dma(code="DMA-0001", **overrides) -> dict:
    """Create a DMA as ProgramDirector. Returns the created DMA (posture OPEN)."""
    res = api_client.create_dma(
        create_dma_payload(code=code, **overrides),
        make_program_director_headers(PD),
    )
    return get_success_data(res)


def get_dma(dma_id) -> dict:
    """Fetch a DMA fresh (used to observe posture / OCC version)."""
    return get_success_data(
        api_client.get_dma(dma_id, make_program_director_headers(PD))
    )


def create_water_balance_period(dma_id, expected_dma_version=None,
                                creator=UA, **period_overrides) -> dict:
    """Create a DRAFT water balance period with the OCC guard satisfied.

    When expected_dma_version is None the parent DMA is re-read first so the
    create always carries the parent's current version.
    """
    if expected_dma_version is None:
        expected_dma_version = get_dma(dma_id)["version"]
    res = api_client.create_water_balance_period(
        create_water_balance_period_payload(
            dma_id, expected_dma_version, **period_overrides
        ),
        make_utility_analyst_headers(creator),
    )
    return get_success_data(res)


def submit_water_balance_period(period_id, user=UA) -> dict:
    return get_success_data(
        api_client.submit_water_balance_period(
            period_id, make_utility_analyst_headers(user)
        )
    )


def finalize_water_balance_period(period_id, user=UA2) -> dict:
    return get_success_data(
        api_client.finalize_water_balance_period(
            period_id, make_utility_analyst_headers(user)
        )
    )


def create_submitted_balance(dma_id, creator=UA, **period_overrides) -> dict:
    """DRAFT -> SUBMITTED. Returns the SUBMITTED period."""
    period = create_water_balance_period(dma_id, creator=creator, **period_overrides)
    return submit_water_balance_period(period["id"], user=creator)


def setup_dma_with_finalized_balance(code="DMA-FIN", creator=UA, finalizer=UA2,
                                     dma_overrides=None, period_overrides=None):
    """DMA + pinned 90-day balance driven DRAFT -> SUBMITTED -> FINALIZED.

    The finalizer differs from the creator to satisfy segregation of duties.
    Returns (dma, finalized_period).
    """
    dma = create_dma(code=code, **(dma_overrides or {}))
    period = create_water_balance_period(dma["id"], creator=creator,
                                         **(period_overrides or {}))
    submit_water_balance_period(period["id"], user=creator)
    finalized = finalize_water_balance_period(period["id"], user=finalizer)
    dma = get_dma(dma["id"])
    return dma, finalized


# ─── Tier 2/3: Leak surveys and leaks ─────────────────

def create_leak_survey(dma_id, lead=FS, **overrides) -> dict:
    """Plan a survey (PLANNED) as FieldSupervisor."""
    res = api_client.create_leak_survey(
        create_leak_survey_payload(dma_id, crew_lead_user_id=lead, **overrides),
        make_field_supervisor_headers(lead),
    )
    return get_success_data(res)


def create_in_field_survey(dma_id, lead=FS, **overrides) -> dict:
    """Plan + start a survey (IN_FIELD). The default planned window starts
    after the initial logical-clock reading, so no clock advance is needed."""
    survey = create_leak_survey(dma_id, lead=lead, **overrides)
    res = api_client.start_leak_survey(
        survey["id"], make_field_supervisor_headers(lead)
    )
    return get_success_data(res)


def report_leak(survey_id, reporter=FS, **overrides) -> dict:
    """Report a leak under an IN_FIELD survey. Returns the REPORTED leak."""
    res = api_client.create_leak(
        create_leak_payload(survey_id, **overrides),
        make_field_supervisor_headers(reporter),
    )
    return get_success_data(res)


def create_verified_leak(survey_id, reporter=FS, **overrides) -> dict:
    """Report + verify a leak (VERIFIED)."""
    leak = report_leak(survey_id, reporter=reporter, **overrides)
    res = api_client.verify_leak(leak["id"], make_field_supervisor_headers(reporter))
    return get_success_data(res)


def create_repaired_leak(dma_id, reporter=FS, actual_repair_cost=None,
                         survey_overrides=None, leak_overrides=None):
    """Survey IN_FIELD + leak REPORTED -> VERIFIED -> REPAIR_SCHEDULED -> REPAIRED.

    Returns (survey, repaired_leak).
    """
    survey = create_in_field_survey(dma_id, lead=reporter, **(survey_overrides or {}))
    leak = report_leak(survey["id"], reporter=reporter, **(leak_overrides or {}))
    get_success_data(
        api_client.verify_leak(leak["id"], make_field_supervisor_headers(reporter))
    )
    get_success_data(
        api_client.schedule_leak_repair(
            leak["id"], make_field_supervisor_headers(reporter)
        )
    )
    payload = {
        "actual_repair_cost": (
            DEFAULTS["ACTUAL_REPAIR_COST"] if actual_repair_cost is None
            else actual_repair_cost
        )
    }
    repaired = get_success_data(
        api_client.complete_leak_repair(
            leak["id"], payload, make_field_supervisor_headers(reporter)
        )
    )
    return survey, repaired


# ─── Tier 2: Meters and accuracy tests ────────────────

def create_customer_meter(dma_id, serial_number="SN-0001", tech=MT, **overrides) -> dict:
    """Register a customer meter (IN_SERVICE) as MeterTechnician."""
    res = api_client.create_customer_meter(
        create_customer_meter_payload(dma_id, serial_number=serial_number, **overrides),
        make_meter_technician_headers(tech),
    )
    return get_success_data(res)


def create_scheduled_accuracy_test(meter_id, tech=MT, **overrides) -> dict:
    """Schedule an accuracy test (SCHEDULED) as MeterTechnician."""
    res = api_client.create_meter_accuracy_test(
        create_meter_accuracy_test_payload(meter_id, **overrides),
        make_meter_technician_headers(tech),
    )
    return get_success_data(res)


def complete_accuracy_test(test_id, registered_volume_m3, reference_volume_m3,
                           tech=MT) -> dict:
    """Complete a SCHEDULED accuracy test (COMPLETED)."""
    res = api_client.complete_meter_accuracy_test(
        test_id,
        {
            "registered_volume_m3": registered_volume_m3,
            "reference_volume_m3": reference_volume_m3,
        },
        make_meter_technician_headers(tech),
    )
    return get_success_data(res)


# ─── Tier 2/3: Unauthorized-consumption cases ─────────

def create_case(dma_id, investigator=INV, **overrides) -> dict:
    """Open a case (OPEN x NONE) as Investigator."""
    res = api_client.create_unauthorized_consumption_case(
        create_case_payload(dma_id, **overrides),
        make_investigator_headers(investigator),
    )
    return get_success_data(res)


def create_substantiated_case(dma_id, investigator=INV, estimated_loss_m3=1200,
                              **overrides) -> dict:
    """OPEN -> EVIDENCE_GATHERING -> SUBSTANTIATED. Returns the case."""
    case = create_case(dma_id, investigator=investigator, **overrides)
    headers = make_investigator_headers(investigator)
    get_success_data(api_client.begin_evidence(case["id"], headers))
    res = api_client.substantiate_case(
        case["id"], {"estimated_loss_m3": estimated_loss_m3}, headers
    )
    return get_success_data(res)


def create_case_with_proposed_adjustment(dma_id, investigator=INV,
                                         estimated_loss_m3=1200,
                                         proposed_adjustment_amount=5000,
                                         **overrides) -> dict:
    """SUBSTANTIATED case with billing NONE -> PROPOSED. Returns the case."""
    case = create_substantiated_case(
        dma_id, investigator=investigator,
        estimated_loss_m3=estimated_loss_m3, **overrides,
    )
    res = api_client.propose_adjustment(
        case["id"],
        {"proposed_adjustment_amount": proposed_adjustment_amount},
        make_investigator_headers(investigator),
    )
    return get_success_data(res)


# ─── Tier 3: Pressure projects ────────────────────────

def create_pressure_project(dma_id, analyst=UA, **overrides) -> dict:
    """Draft a pressure project (PROPOSED) as UtilityAnalyst."""
    res = api_client.create_pressure_project(
        create_pressure_project_payload(dma_id, **overrides),
        make_utility_analyst_headers(analyst),
    )
    return get_success_data(res)


def create_approved_pressure_project(dma_id, analyst=UA, **overrides) -> dict:
    """PROPOSED -> APPROVED (DMA posture must be OPEN at approval time)."""
    project = create_pressure_project(dma_id, analyst=analyst, **overrides)
    res = api_client.approve_pressure_project(
        project["id"], make_program_director_headers(PD)
    )
    return get_success_data(res)


def create_active_pressure_project(dma_id, analyst=UA, **overrides) -> dict:
    """PROPOSED -> APPROVED -> ACTIVE. The default planned_start equals the
    initial logical-clock reading, so activation is immediately allowed."""
    project = create_approved_pressure_project(dma_id, analyst=analyst, **overrides)
    res = api_client.activate_pressure_project(
        project["id"], make_program_director_headers(PD)
    )
    return get_success_data(res)


def create_in_field_survey_with_active_project(dma_id, lead=FS, analyst=UA,
                                               survey_overrides=None,
                                               project_overrides=None):
    """IN_FIELD survey plus an ACTIVE pressure project over the same DMA.

    Ordering matters: starting field work requires the DMA posture to be
    exactly OPEN, and activating a project moves the posture to RESTRICTED, so
    the survey is planned and started first, then the project is drafted,
    approved, and activated. Returns (project, survey).
    """
    survey = create_in_field_survey(dma_id, lead=lead, **(survey_overrides or {}))
    project = create_active_pressure_project(dma_id, analyst=analyst,
                                             **(project_overrides or {}))
    return project, survey


# ─── Tier 2/3: Intervention proposals ─────────────────

def create_intervention_proposal(dma_id, analyst=UA, **overrides) -> dict:
    """Draft an intervention proposal (DRAFT, provisional ratio computed)."""
    res = api_client.create_intervention_proposal(
        create_intervention_proposal_payload(dma_id, **overrides),
        make_utility_analyst_headers(analyst),
    )
    return get_success_data(res)


def create_submitted_proposal(dma_id, analyst=UA, **overrides) -> dict:
    """DRAFT -> SUBMITTED. Returns the SUBMITTED proposal."""
    proposal = create_intervention_proposal(dma_id, analyst=analyst, **overrides)
    res = api_client.submit_intervention_proposal(
        proposal["id"], make_utility_analyst_headers(analyst)
    )
    return get_success_data(res)


# ─── Tier 5: Benchmark reports and frozen districts ───

def create_benchmark_report(dma_ids, liaison=RL, **overrides) -> dict:
    """Draft a benchmark report (DRAFT) as RegulatorLiaison."""
    res = api_client.create_benchmark_report(
        create_benchmark_report_payload(dma_ids, **overrides),
        make_regulator_liaison_headers(liaison),
    )
    return get_success_data(res)


def submit_benchmark_report(report_id, expected_report_version=None, liaison=RL) -> dict:
    """DRAFT|RETURNED -> SUBMITTED with the report OCC guard satisfied."""
    if expected_report_version is None:
        expected_report_version = get_success_data(
            api_client.get_benchmark_report(
                report_id, make_regulator_liaison_headers(liaison)
            )
        )["version"]
    res = api_client.submit_benchmark_report(
        report_id, {"expected_report_version": expected_report_version},
        make_regulator_liaison_headers(liaison),
    )
    return get_success_data(res)


def setup_frozen_dma(code="DMA-FRZ", dma_overrides=None, period_overrides=None):
    """DMA with a FINALIZED balance plus a SUBMITTED benchmark report over it,
    leaving the DMA FROZEN. Returns (dma, finalized_period, report).
    """
    dma, period = setup_dma_with_finalized_balance(
        code=code, dma_overrides=dma_overrides, period_overrides=period_overrides
    )
    report = create_benchmark_report([dma["id"]])
    submitted = submit_benchmark_report(report["id"])
    dma = get_dma(dma["id"])
    return dma, period, submitted


# ─── Night-flow assessments ───────────────────────────

def create_night_flow_assessment(dma_id, analyst=UA, **overrides) -> dict:
    """Record a night-flow assessment (RECORDED) as UtilityAnalyst."""
    res = api_client.create_night_flow_assessment(
        create_night_flow_assessment_payload(dma_id, **overrides),
        make_utility_analyst_headers(analyst),
    )
    return get_success_data(res)
