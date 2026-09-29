"""Composite setup helpers.

Every test starts against an empty database, so every precondition here is built
from scratch through the endpoints the PRD declares. Setup calls use the lenient
validator so a broken precondition reports as a setup failure rather than as a
confusing assertion failure inside a test.

The recurring shape of this domain is a chain: an employer partner, a worksite
whose safety review has been approved, a trained supervisor, an executed
partnership agreement, an eligible student holding an issued work permit, a
placement, and a training plan whose approval activates the placement and opens
its first evaluation cycle. The builders below expose that chain at each of its
useful stopping points.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_employer_supervisor_headers,
    make_student_headers,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
DRAFTER = TEST_USERS["coordinator_drafter_headers"]
SIGNER = TEST_USERS["coordinator_signer_headers"]
APPROVER = TEST_USERS["coordinator_approver_headers"]
AWARDER = TEST_USERS["coordinator_awarder_headers"]
REVIEWER = TEST_USERS["safety_reviewer_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]

DEFAULT_CLOCK = "2026-09-07T08:00:00Z"


# --------------------------------------------------------------------------
# Scenario container
# --------------------------------------------------------------------------


@dataclass
class Scenario:
    """Everything a placement-centred test needs, in one bag."""

    partner: Optional[dict] = None
    worksite: Optional[dict] = None
    review: Optional[dict] = None
    supervisor: Optional[dict] = None
    agreement: Optional[dict] = None
    student: Optional[dict] = None
    permit: Optional[dict] = None
    placement: Optional[dict] = None
    plan: Optional[dict] = None
    objectives: List[dict] = field(default_factory=list)
    cycles: List[dict] = field(default_factory=list)
    entries: List[dict] = field(default_factory=list)

    # --- convenient ids -------------------------------------------------
    @property
    def partner_id(self) -> str:
        return self.partner["id"]

    @property
    def worksite_id(self) -> str:
        return self.worksite["id"]

    @property
    def supervisor_id(self) -> str:
        return self.supervisor["id"]

    @property
    def agreement_id(self) -> str:
        return self.agreement["id"]

    @property
    def student_id(self) -> str:
        return self.student["id"]

    @property
    def permit_id(self) -> str:
        return self.permit["id"]

    @property
    def placement_id(self) -> str:
        return self.placement["id"]

    @property
    def plan_id(self) -> str:
        return self.plan["id"]

    # --- identity-threaded headers --------------------------------------
    @property
    def supervisor_headers(self) -> dict:
        """The acting EmployerSupervisor's `X-User-ID` is the supervisor row's id."""
        return make_employer_supervisor_headers(self.supervisor["id"])

    @property
    def student_headers(self) -> dict:
        """The acting Student's `X-User-ID` is the student row's id."""
        return make_student_headers(self.student["id"])


# --------------------------------------------------------------------------
# Tier 0 — single-step builders and readers
# --------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(f.set_clock_payload(to_iso8601), COORDINATOR))


def recruit_employer_partner(**overrides) -> dict:
    return get_success_data(
        api_client.create_employer_partner(f.create_employer_partner_payload(**overrides), COORDINATOR)
    )


def register_worksite(employer_partner_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_worksite(
            f.create_worksite_payload(employer_partner_id, **overrides), COORDINATOR
        )
    )


def file_safety_review(worksite_id: str, expected_worksite_version: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_safety_review(
            f.create_safety_review_payload(worksite_id, expected_worksite_version, **overrides),
            REVIEWER,
        )
    )


def decide_safety_review(review_id: str, decision: str = "APPROVED") -> dict:
    return get_success_data(
        api_client.decide_safety_review(
            review_id, f.decide_safety_review_payload(decision), REVIEWER
        )
    )


def register_supervisor(worksite_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_supervisor(f.create_supervisor_payload(worksite_id, **overrides), COORDINATOR)
    )


def enrol_student(**overrides) -> dict:
    return get_success_data(
        api_client.create_student(f.create_student_payload(**overrides), COORDINATOR)
    )


def request_work_permit(student_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_work_permit(f.create_work_permit_payload(student_id, **overrides), COORDINATOR)
    )


def issue_work_permit(permit_id: str, expires_on: str = "2027-06-30") -> dict:
    return get_success_data(
        api_client.issue_work_permit(permit_id, f.issue_work_permit_payload(expires_on), OFFICER)
    )


def revoke_work_permit(permit_id: str, revoked_reason: str = "Guardian withdrew consent") -> dict:
    return get_success_data(
        api_client.revoke_work_permit(
            permit_id, f.revoke_work_permit_payload(revoked_reason), OFFICER
        )
    )


# --- readers ---------------------------------------------------------------


def read_partner(partner_id: str) -> dict:
    return get_success_data(api_client.get_employer_partner(partner_id, COORDINATOR))


def read_worksite(worksite_id: str) -> dict:
    return get_success_data(api_client.get_worksite(worksite_id, COORDINATOR))


def read_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, COORDINATOR))


def read_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, COORDINATOR))


def read_permit(student_id: str, permit_id: str) -> dict:
    data = get_success_data(api_client.list_student_work_permits(student_id, COORDINATOR))
    for permit in data:
        if permit["id"] == permit_id:
            return permit
    raise AssertionError(f"Setup step failed: permit {permit_id} not listed for student {student_id}")


def read_placement(placement_id: str) -> dict:
    return get_success_data(api_client.get_placement(placement_id, COORDINATOR))


def read_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_training_plan(plan_id, COORDINATOR))


def read_incident(incident_id: str) -> dict:
    return get_success_data(api_client.get_incident_report(incident_id, COORDINATOR))


def list_cycles(placement_id: str) -> list:
    return get_success_data(api_client.list_placement_evaluation_cycles(placement_id, COORDINATOR))


def read_cycle(placement_id: str, cycle_index: int) -> dict:
    for cycle in list_cycles(placement_id):
        if cycle["cycle_index"] == cycle_index:
            return cycle
    raise AssertionError(
        f"Setup step failed: no evaluation cycle with cycle_index {cycle_index} on placement {placement_id}"
    )


def list_entries(placement_id: str) -> list:
    return get_success_data(api_client.list_placement_timesheet_entries(placement_id, COORDINATOR))


def list_objectives(plan_id: str) -> list:
    return get_success_data(api_client.list_training_plan_objectives(plan_id, COORDINATOR))


# --------------------------------------------------------------------------
# Tier 1 — state progression composites
# --------------------------------------------------------------------------


def register_reviewed_worksite(
    employer_partner_id: str,
    decision: str = "APPROVED",
    review_overrides: Optional[dict] = None,
    **worksite_overrides,
):
    """Register a worksite, file a review against it and decide the review.

    Returns (worksite_after_decision, review_after_decision). The worksite is
    re-read so its `version` reflects the decision's bump.
    """
    worksite = register_worksite(employer_partner_id, **worksite_overrides)
    review = file_safety_review(worksite["id"], worksite["version"], **(review_overrides or {}))
    review = decide_safety_review(review["id"], decision)
    return read_worksite(worksite["id"]), review


def execute_agreement(
    employer_partner_id: str,
    worksite_id: str,
    supervisor_id: str,
    **overrides,
) -> dict:
    """Draft as one coordinator, countersign as the nominated supervisor, then
    execute as a different coordinator. Returns the EXECUTED agreement."""
    agreement = get_success_data(
        api_client.create_agreement(
            f.create_agreement_payload(
                employer_partner_id, worksite_id, supervisor_id, **overrides
            ),
            DRAFTER,
        )
    )
    get_success_data(
        api_client.employer_sign_agreement(
            agreement["id"], {}, make_employer_supervisor_headers(supervisor_id)
        )
    )
    return get_success_data(api_client.execute_agreement(agreement["id"], {}, SIGNER))


def enrol_student_with_issued_permit(
    permit_class: str = "MINOR_16_17",
    hazardous_endorsement: bool = False,
    permit_expires_on: str = "2027-06-30",
    **student_overrides,
):
    """Enrol a student and put an ISSUED work permit of the given band on file.
    Returns (student, permit)."""
    student = enrol_student(**student_overrides)
    permit = request_work_permit(
        student["id"],
        permit_class=permit_class,
        hazardous_endorsement=hazardous_endorsement,
    )
    permit = issue_work_permit(permit["id"], permit_expires_on)
    return student, permit


# --------------------------------------------------------------------------
# Tier 2 — the placement chain
# --------------------------------------------------------------------------


def setup_partner_worksite_supervisor(
    partner_overrides: Optional[dict] = None,
    worksite_overrides: Optional[dict] = None,
    review_decision: str = "APPROVED",
    review_overrides: Optional[dict] = None,
    supervisor_overrides: Optional[dict] = None,
) -> Scenario:
    """Employer partner + reviewed worksite + trained supervisor."""
    scenario = Scenario()
    scenario.partner = recruit_employer_partner(**(partner_overrides or {}))
    scenario.worksite, scenario.review = register_reviewed_worksite(
        scenario.partner_id,
        decision=review_decision,
        review_overrides=review_overrides,
        **(worksite_overrides or {}),
    )
    scenario.supervisor = register_supervisor(
        scenario.worksite_id, **(supervisor_overrides or {})
    )
    return scenario


def setup_agreement_ready(
    partner_overrides: Optional[dict] = None,
    worksite_overrides: Optional[dict] = None,
    review_decision: str = "APPROVED",
    review_overrides: Optional[dict] = None,
    supervisor_overrides: Optional[dict] = None,
    agreement_overrides: Optional[dict] = None,
) -> Scenario:
    """Partner + reviewed worksite + supervisor + EXECUTED agreement."""
    scenario = setup_partner_worksite_supervisor(
        partner_overrides=partner_overrides,
        worksite_overrides=worksite_overrides,
        review_decision=review_decision,
        review_overrides=review_overrides,
        supervisor_overrides=supervisor_overrides,
    )
    scenario.agreement = execute_agreement(
        scenario.partner_id,
        scenario.worksite_id,
        scenario.supervisor_id,
        **(agreement_overrides or {}),
    )
    return scenario


def setup_proposed_placement(
    clock: Optional[str] = DEFAULT_CLOCK,
    partner_overrides: Optional[dict] = None,
    worksite_overrides: Optional[dict] = None,
    review_decision: str = "APPROVED",
    review_overrides: Optional[dict] = None,
    supervisor_overrides: Optional[dict] = None,
    agreement_overrides: Optional[dict] = None,
    student_overrides: Optional[dict] = None,
    permit_class: str = "MINOR_16_17",
    hazardous_endorsement: bool = False,
    permit_expires_on: str = "2027-06-30",
    placement_overrides: Optional[dict] = None,
) -> Scenario:
    """The whole referential chain, ending with a PROPOSED / PENDING_REVIEW placement."""
    if clock:
        set_clock(clock)
    scenario = setup_agreement_ready(
        partner_overrides=partner_overrides,
        worksite_overrides=worksite_overrides,
        review_decision=review_decision,
        review_overrides=review_overrides,
        supervisor_overrides=supervisor_overrides,
        agreement_overrides=agreement_overrides,
    )
    scenario.student, scenario.permit = enrol_student_with_issued_permit(
        permit_class=permit_class,
        hazardous_endorsement=hazardous_endorsement,
        permit_expires_on=permit_expires_on,
        **(student_overrides or {}),
    )
    scenario.worksite = read_worksite(scenario.worksite_id)
    scenario.placement = get_success_data(
        api_client.create_placement(
            f.create_placement_payload(
                scenario.student_id,
                scenario.worksite_id,
                scenario.agreement_id,
                scenario.supervisor_id,
                scenario.worksite["version"],
                **(placement_overrides or {}),
            ),
            COORDINATOR,
        )
    )
    return scenario


def draft_plan_with_objectives(
    scenario: Scenario,
    course_code: str = "MFG-210",
    credit_hours_target: float = 90.00,
    objective_count: int = 3,
    aligned: bool = True,
    plan_overrides: Optional[dict] = None,
) -> Scenario:
    """Draft a training plan on the scenario's placement and add objectives to it.

    `aligned` controls whether each objective's `aligned_course_code` matches the
    plan's `course_code`, which is what makes it count toward the plan's
    `aligned_objective_count`.
    """
    scenario.placement = read_placement(scenario.placement_id)
    scenario.plan = get_success_data(
        api_client.create_training_plan(
            f.create_training_plan_payload(
                scenario.placement_id,
                scenario.placement["version"],
                course_code=course_code,
                credit_hours_target=credit_hours_target,
                **(plan_overrides or {}),
            ),
            COORDINATOR,
        )
    )
    scenario.objectives = []
    for index in range(objective_count):
        scenario.objectives.append(
            get_success_data(
                api_client.create_learning_objective(
                    f.create_learning_objective_payload(
                        scenario.plan_id,
                        course_code if aligned else f"OTHER-{index}",
                        competency_code=f"{course_code}-C{index + 1}",
                    ),
                    COORDINATOR,
                )
            )
        )
    scenario.plan = read_plan(scenario.plan_id)
    return scenario


def submit_and_approve_plan(scenario: Scenario) -> Scenario:
    """Submit the plan and approve it as a coordinator distinct from the drafter
    and the executor. Approval is what clears and activates the placement and
    creates the first evaluation cycle."""
    get_success_data(api_client.submit_training_plan(scenario.plan_id, {}, COORDINATOR))
    scenario.plan = get_success_data(
        api_client.approve_training_plan(scenario.plan_id, {}, APPROVER)
    )
    scenario.placement = read_placement(scenario.placement_id)
    scenario.cycles = list_cycles(scenario.placement_id)
    return scenario


def setup_active_placement(
    clock: Optional[str] = DEFAULT_CLOCK,
    course_code: str = "MFG-210",
    credit_hours_target: float = 90.00,
    **chain_overrides,
) -> Scenario:
    """Full chain through plan approval: the placement is ACTIVE / CLEARED and
    its `cycle_index` 1 evaluation cycle is open."""
    scenario = setup_proposed_placement(clock=clock, **chain_overrides)
    draft_plan_with_objectives(
        scenario, course_code=course_code, credit_hours_target=credit_hours_target
    )
    submit_and_approve_plan(scenario)
    return scenario


# --------------------------------------------------------------------------
# Tier 3 — hour ledger and evaluation cycle progression
# --------------------------------------------------------------------------


def log_shift(
    scenario: Scenario,
    work_date: str,
    start_time: str,
    end_time: str,
    break_minutes: int = 0,
    is_school_day: bool = True,
    placement_id: Optional[str] = None,
    supervisor_id: Optional[str] = None,
) -> dict:
    """Log one shift as the supervising EmployerSupervisor."""
    entry = get_success_data(
        api_client.create_timesheet_entry(
            f.create_timesheet_entry_payload(
                placement_id or scenario.placement_id,
                work_date,
                start_time,
                end_time,
                break_minutes=break_minutes,
                is_school_day=is_school_day,
            ),
            make_employer_supervisor_headers(supervisor_id or scenario.supervisor_id),
        )
    )
    scenario.entries.append(entry)
    return entry


def log_shifts(scenario: Scenario, shifts: list) -> list:
    """Log a list of (work_date, start_time, end_time, break_minutes, is_school_day) shifts."""
    logged = []
    for shift in shifts:
        work_date, start_time, end_time = shift[0], shift[1], shift[2]
        break_minutes = shift[3] if len(shift) > 3 else 0
        is_school_day = shift[4] if len(shift) > 4 else True
        logged.append(
            log_shift(
                scenario,
                work_date,
                start_time,
                end_time,
                break_minutes=break_minutes,
                is_school_day=is_school_day,
            )
        )
    return logged


def submit_cycle_evaluation(
    scenario: Scenario, cycle_id: str, ratings: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.submit_evaluation(
            cycle_id,
            f.submit_evaluation_payload(**(ratings or {})),
            scenario.supervisor_headers,
        )
    )


def submit_cycle_reflection(scenario: Scenario, cycle_id: str, reflection_text: Optional[str] = None) -> dict:
    payload = (
        f.submit_reflection_payload(reflection_text)
        if reflection_text
        else f.submit_reflection_payload()
    )
    return get_success_data(
        api_client.submit_reflection(cycle_id, payload, scenario.student_headers)
    )


def accept_cycle_reflection(cycle_id: str, feedback_note: str = "Complete and specific.") -> dict:
    return get_success_data(
        api_client.decide_reflection(
            cycle_id, f.reflection_decision_payload("ACCEPT", feedback_note), COORDINATOR
        )
    )


def close_cycle(
    scenario: Scenario,
    cycle_id: str,
    ratings: Optional[dict] = None,
    reflection_text: Optional[str] = None,
) -> dict:
    """Advance both dimensions of a cycle to their terminal values so the cycle
    closes: supervisor ratings, then the student reflection, then acceptance."""
    submit_cycle_evaluation(scenario, cycle_id, ratings)
    submit_cycle_reflection(scenario, cycle_id, reflection_text)
    accept_cycle_reflection(cycle_id)
    scenario.cycles = list_cycles(scenario.placement_id)
    scenario.placement = read_placement(scenario.placement_id)
    return next(cycle for cycle in scenario.cycles if cycle["id"] == cycle_id)


def close_all_required_cycles(scenario: Scenario, ratings_per_cycle: Optional[list] = None) -> Scenario:
    """Close as many cycles as the placement's `required_evaluation_cycles`."""
    required = scenario.placement["required_evaluation_cycles"]
    for index in range(1, required + 1):
        cycle = read_cycle(scenario.placement_id, index)
        ratings = (
            ratings_per_cycle[index - 1]
            if ratings_per_cycle and len(ratings_per_cycle) >= index
            else None
        )
        close_cycle(scenario, cycle["id"], ratings=ratings)
    return scenario


def complete_placement(scenario: Scenario) -> dict:
    scenario.placement = get_success_data(
        api_client.complete_placement(scenario.placement_id, {}, COORDINATOR)
    )
    return scenario.placement


def setup_completed_placement(
    clock: Optional[str] = DEFAULT_CLOCK,
    shifts: Optional[list] = None,
    shift_clock: Optional[str] = None,
    ratings_per_cycle: Optional[list] = None,
    course_code: str = "MFG-210",
    credit_hours_target: float = 90.00,
    **chain_overrides,
) -> Scenario:
    """Full chain through COMPLETED: activate the placement, optionally log the
    given shifts, close every required evaluation cycle, then complete."""
    scenario = setup_active_placement(
        clock=clock,
        course_code=course_code,
        credit_hours_target=credit_hours_target,
        **chain_overrides,
    )
    if shifts:
        if shift_clock:
            set_clock(shift_clock)
        log_shifts(scenario, shifts)
    close_all_required_cycles(scenario, ratings_per_cycle=ratings_per_cycle)
    complete_placement(scenario)
    scenario.placement = read_placement(scenario.placement_id)
    return scenario


# --------------------------------------------------------------------------
# Tier 4 — incidents and the compliance dimension
# --------------------------------------------------------------------------


def report_incident(
    scenario: Scenario,
    occurred_at: str,
    severity: str = "MINOR",
    injury_type: str = "LACERATION",
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_incident_report(
            f.create_incident_report_payload(
                scenario.placement_id,
                scenario.worksite_id,
                occurred_at,
                severity=severity,
                injury_type=injury_type,
                **overrides,
            ),
            COORDINATOR,
        )
    )


def substantiate_incident(incident_id: str) -> dict:
    return get_success_data(
        api_client.record_incident_finding(
            incident_id, f.incident_finding_payload("SUBSTANTIATED"), OFFICER
        )
    )


def block_placement_with_critical_incident(
    scenario: Scenario,
    occurred_at: str,
    injury_type: str = "FRACTURE",
) -> dict:
    """A substantiated CRITICAL incident drives the worksite to FAILED and the
    placement's compliance dimension to BLOCKED. Returns the incident."""
    incident = report_incident(
        scenario, occurred_at, severity="CRITICAL", injury_type=injury_type
    )
    incident = substantiate_incident(incident["id"])
    scenario.placement = read_placement(scenario.placement_id)
    return incident


def compliance_decision(placement_id: str, decision: str, note: str) -> dict:
    return get_success_data(
        api_client.placement_compliance_decision(
            placement_id, f.compliance_decision_payload(decision, note), OFFICER
        )
    )


# --------------------------------------------------------------------------
# Tier 5 — capacity and multi-worksite arrangements
# --------------------------------------------------------------------------


def setup_two_worksite_scenarios(
    clock: Optional[str] = DEFAULT_CLOCK,
    student_overrides: Optional[dict] = None,
    permit_class: str = "ADULT_18_PLUS",
    placement_overrides: Optional[dict] = None,
):
    """One student placed at two worksites belonging to two different partners.

    Returns (scenario_a, scenario_b) sharing the same student and permit, each
    with its own partner, worksite, supervisor, agreement, placement, approved
    training plan and open first cycle.
    """
    if clock:
        set_clock(clock)

    student, permit = enrol_student_with_issued_permit(
        permit_class=permit_class, **(student_overrides or {})
    )

    scenarios = []
    for label, sector in (("A", "MANUFACTURING"), ("B", "HOSPITALITY")):
        scenario = setup_agreement_ready(
            partner_overrides={
                "legal_name": f"Partner {label} LLC",
                "industry_sector": sector,
            },
            worksite_overrides={"site_name": f"Site {label}"},
            supervisor_overrides={
                "full_name": f"Supervisor {label}",
                "email": f"supervisor.{label.lower()}@example.test",
            },
        )
        scenario.student = student
        scenario.permit = permit
        scenario.worksite = read_worksite(scenario.worksite_id)
        scenario.placement = get_success_data(
            api_client.create_placement(
                f.create_placement_payload(
                    student["id"],
                    scenario.worksite_id,
                    scenario.agreement_id,
                    scenario.supervisor_id,
                    scenario.worksite["version"],
                    **(placement_overrides or {}),
                ),
                COORDINATOR,
            )
        )
        draft_plan_with_objectives(scenario, course_code=f"CTE-{label}00")
        submit_and_approve_plan(scenario)
        scenarios.append(scenario)

    return scenarios[0], scenarios[1]


def add_second_student_placement(
    scenario: Scenario,
    student_overrides: Optional[dict] = None,
    permit_class: str = "MINOR_16_17",
    placement_overrides: Optional[dict] = None,
):
    """Enrol a second student with an issued permit and attempt a second
    placement at the scenario's worksite. Returns (student, response) — the
    response is left unvalidated so capacity and load tests can assert on it."""
    student, _permit = enrol_student_with_issued_permit(
        permit_class=permit_class, **(student_overrides or {})
    )
    worksite = read_worksite(scenario.worksite_id)
    response = api_client.create_placement(
        f.create_placement_payload(
            student["id"],
            scenario.worksite_id,
            scenario.agreement_id,
            scenario.supervisor_id,
            worksite["version"],
            **(placement_overrides or {}),
        ),
        COORDINATOR,
    )
    return student, response
