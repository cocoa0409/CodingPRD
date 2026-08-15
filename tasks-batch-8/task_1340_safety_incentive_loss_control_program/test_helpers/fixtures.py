"""Composite setup helpers.

Every test starts against an empty database with the logical clock at its
startup value, so these helpers build complete precondition chains (program
activation -> roster -> hazard/control verification -> meetings -> program
close) out of PRD-declared endpoints only.

Identity threading: SafetyManager / Supervisor / Employee / CommitteeChair are
entity-backed by Employee, and ContractorRep is entity-backed by ContractorOrg.
Every ownership- or segregation-of-duties-sensitive call uses the per-instance
make_*_headers builders with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_action_item_payload,
    create_claim_payload,
    create_contractor_payload,
    create_control_payload,
    create_employee_payload,
    create_hazard_payload,
    create_job_role_payload,
    create_meeting_payload,
    create_observation_payload,
    create_program_payload,
    create_recommendation_payload,
    create_training_assignment_payload,
    create_training_course_payload,
)
from .test_users import (
    TEST_USERS,
    make_committee_chair_headers,
    make_contractor_rep_headers,
    make_employee_headers,
    make_safety_manager_headers,
    make_supervisor_headers,
)

ADMIN = TEST_USERS["ehs_admin_headers"]
CARRIER = TEST_USERS["carrier_consultant_headers"]

DEFAULT_TEST_CLOCK = "2026-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_TEST_CLOCK):
    """Advance the logical clock (EHSAdmin-only). Returns {current_utc}."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: program lifecycle
# ---------------------------------------------------------------------------

def create_program(**overrides):
    """Create a SafetyProgram in DRAFT. Returns the created program."""
    return get_success_data(api_client.create_program(create_program_payload(**overrides),
                                                      ADMIN))


def activate_program(program_id):
    return get_success_data(api_client.activate_program(program_id, ADMIN))


def create_active_program(**overrides):
    """Create + activate a program. Returns the ACTIVE program."""
    program = create_program(**overrides)
    return activate_program(program["id"])


def get_program(program_id):
    return get_success_data(api_client.get_program(program_id, ADMIN))


def get_leading_indicators(program_id, reader_id=None):
    headers = (make_safety_manager_headers(reader_id) if reader_id else ADMIN)
    return get_success_data(api_client.get_leading_indicators(program_id, headers))


# ---------------------------------------------------------------------------
# Tier 1: catalog and roster
# ---------------------------------------------------------------------------

def create_job_role(title="Laborer", hazard_class="LOW", required_course_ids=None):
    return get_success_data(api_client.create_job_role(
        create_job_role_payload(title=title, hazard_class=hazard_class,
                                required_course_ids=required_course_ids), ADMIN))


def create_course(title="HAZCOM", hazard_class="LOW", validity_months=12,
                  renewal_window_days=None):
    return get_success_data(api_client.create_training_course(
        create_training_course_payload(
            title=title, hazard_class=hazard_class, validity_months=validity_months,
            renewal_window_days=renewal_window_days), ADMIN))


def create_employee_record(job_role_id, full_name="Ann A", hired_on="2026-01-05",
                           committee_member=None):
    return get_success_data(api_client.create_employee(
        create_employee_payload(full_name=full_name, job_role_id=job_role_id,
                                hired_on=hired_on, committee_member=committee_member),
        ADMIN))


def get_employee(employee_id):
    return get_success_data(api_client.get_employee(employee_id, ADMIN))


def setup_roster(member_names=(), plain_names=("Marta M",), hazard_class="LOW",
                 role_title="Laborer", required_course_ids=None):
    """Create a job role plus employees. member_names get committee_member=true.

    Returns (job_role, employees) where employees maps full_name -> employee dict.
    """
    role = create_job_role(title=role_title, hazard_class=hazard_class,
                           required_course_ids=required_course_ids)
    employees = {}
    for name in member_names:
        employees[name] = create_employee_record(role["id"], full_name=name,
                                                 committee_member=True)
    for name in plain_names:
        employees[name] = create_employee_record(role["id"], full_name=name)
    return role, employees


# ---------------------------------------------------------------------------
# Tier 1/2: hazards and controls
# ---------------------------------------------------------------------------

def create_hazard_record(program_id, manager_id, identified_by, location="L1",
                         description="Spill"):
    """Report a hazard as the SafetyManager employee. Returns the OPEN hazard."""
    return get_success_data(api_client.create_hazard(
        create_hazard_payload(program_id, location=location, description=description,
                              identified_by=identified_by),
        make_safety_manager_headers(manager_id)))


def assess_hazard(hazard_id, manager_id, severity=3, probability=2):
    return get_success_data(api_client.assess_hazard(
        hazard_id, {"severity": severity, "probability": probability},
        make_safety_manager_headers(manager_id)))


def add_control(hazard_id, implementer_id, actor_manager_id, description="Fix it",
                due_date="2026-06-20T00:00:00Z"):
    """Add a control under a hazard (SafetyManager actor). Returns the control."""
    return get_success_data(api_client.create_control(
        hazard_id,
        create_control_payload(description=description, implementer_id=implementer_id,
                               due_date=due_date),
        make_safety_manager_headers(actor_manager_id)))


def implement_control(control_id, actor_employee_id, role="Supervisor",
                      implemented_at=None):
    payload = {}
    if implemented_at is not None:
        payload["implemented_at"] = implemented_at
    headers = (make_supervisor_headers(actor_employee_id) if role == "Supervisor"
               else make_safety_manager_headers(actor_employee_id))
    return get_success_data(api_client.implement_control(control_id, payload, headers))


def verify_control(control_id, verifier_manager_id, outcome="PASS", outcome_note=None,
                   due_date=None):
    payload = {"outcome": outcome}
    if outcome_note is not None:
        payload["outcome_note"] = outcome_note
    if due_date is not None:
        payload["due_date"] = due_date
    return get_success_data(api_client.verify_control(
        control_id, payload, make_safety_manager_headers(verifier_manager_id)))


def get_hazard(hazard_id, reader_manager_id=None):
    headers = (make_safety_manager_headers(reader_manager_id)
               if reader_manager_id else ADMIN)
    return get_success_data(api_client.get_hazard(hazard_id, headers))


def get_control(control_id):
    return get_success_data(api_client.get_control(control_id, ADMIN))


def setup_hazard_with_controls(program_id, reporter_id, manager_id, control_count=1,
                               implementer_id=None, severity=3, probability=2,
                               due_date="2026-06-20T00:00:00Z", location="L1",
                               description="Hazard"):
    """Hazard reported, assessed, with `control_count` PLANNED controls.

    Returns (hazard, controls). The hazard stands in CONTROLS_PLANNED.
    """
    implementer_id = implementer_id or reporter_id
    hazard = create_hazard_record(program_id, manager_id, identified_by=reporter_id,
                                  location=location, description=description)
    hazard = assess_hazard(hazard["id"], manager_id, severity=severity,
                           probability=probability)
    controls = [
        add_control(hazard["id"], implementer_id, manager_id,
                    description=f"Control {i + 1}", due_date=due_date)
        for i in range(control_count)
    ]
    return hazard, controls


def close_hazard_via_single_control(program_id, reporter_id, manager_id,
                                    implementer_id=None, severity=3, probability=2,
                                    due_date="2026-06-20T00:00:00Z",
                                    implementer_role="Supervisor"):
    """Assessed hazard with one control, implemented then verified PASS.

    Returns (hazard, control); the hazard is CLOSED.
    """
    implementer_id = implementer_id or reporter_id
    hazard, controls = setup_hazard_with_controls(
        program_id, reporter_id, manager_id, control_count=1,
        implementer_id=implementer_id, severity=severity, probability=probability,
        due_date=due_date)
    implement_control(controls[0]["id"], implementer_id, role=implementer_role)
    verify_control(controls[0]["id"], manager_id, outcome="PASS")
    return get_hazard(hazard["id"]), get_control(controls[0]["id"])


# ---------------------------------------------------------------------------
# Tier 1/2: observations
# ---------------------------------------------------------------------------

def create_observation_record(program_id, reporter_id, kind="OBSERVATION",
                              description="Observed condition",
                              occurred_at="2026-05-30T00:00:00Z",
                              reporter_role="Employee"):
    headers = (make_employee_headers(reporter_id) if reporter_role == "Employee"
               else make_safety_manager_headers(reporter_id))
    return get_success_data(api_client.create_observation(
        create_observation_payload(program_id, reporter_id, kind=kind,
                                   description=description, occurred_at=occurred_at),
        headers))


def triage_observation_link(observation_id, hazard_id, manager_id):
    return get_success_data(api_client.triage_observation(
        observation_id, {"action": "LINK_EXISTING", "hazard_id": hazard_id},
        make_safety_manager_headers(manager_id)))


def triage_observation_no_action(observation_id, manager_id):
    return get_success_data(api_client.triage_observation(
        observation_id, {"action": "NO_ACTION"},
        make_safety_manager_headers(manager_id)))


def get_observation(observation_id):
    return get_success_data(api_client.get_observation(observation_id, ADMIN))


def list_events(program_id=None, employee_id=None, source_type=None):
    params = {}
    if program_id is not None:
        params["program_id"] = program_id
    if employee_id is not None:
        params["employee_id"] = employee_id
    if source_type is not None:
        params["source_type"] = source_type
    rows, _meta = validate_paginated(
        api_client.list_incentive_events(ADMIN, params=params))
    return rows


# ---------------------------------------------------------------------------
# Tier 1/2: committee meetings and action items
# ---------------------------------------------------------------------------

def create_meeting_record(program_id, chair_id,
                          scheduled_start="2026-06-10T09:00:00Z",
                          scheduled_end="2026-06-10T10:00:00Z", location="Room 1"):
    return get_success_data(api_client.create_committee_meeting(
        create_meeting_payload(program_id, scheduled_start=scheduled_start,
                               scheduled_end=scheduled_end, location=location),
        make_committee_chair_headers(chair_id)))


def hold_meeting(meeting_id, chair_id, attendee_ids):
    return get_success_data(api_client.hold_meeting(
        meeting_id, {"attendee_ids": attendee_ids},
        make_committee_chair_headers(chair_id)))


def publish_meeting_minutes(meeting_id, chair_id, minutes_text="Notes"):
    return get_success_data(api_client.publish_minutes(
        meeting_id, {"minutes_text": minutes_text},
        make_committee_chair_headers(chair_id)))


def setup_published_meeting(program_id, chair_id, attendee_ids,
                            scheduled_start="2026-06-10T09:00:00Z",
                            scheduled_end="2026-06-10T10:00:00Z", location="Room 1",
                            minutes_text="Notes"):
    """Meeting walked SCHEDULED -> HELD -> MINUTES_PUBLISHED."""
    meeting = create_meeting_record(program_id, chair_id,
                                    scheduled_start=scheduled_start,
                                    scheduled_end=scheduled_end, location=location)
    hold_meeting(meeting["id"], chair_id, attendee_ids)
    return publish_meeting_minutes(meeting["id"], chair_id, minutes_text)


def get_meeting(meeting_id):
    return get_success_data(api_client.get_committee_meeting(meeting_id, ADMIN))


def create_action_item_record(meeting_id, chair_id, assignee_id,
                              description="Follow up",
                              due_date="2026-06-20T00:00:00Z", hazard_id=None):
    return get_success_data(api_client.create_action_item(
        meeting_id,
        create_action_item_payload(assignee_id, description=description,
                                   due_date=due_date, hazard_id=hazard_id),
        make_committee_chair_headers(chair_id)))


def complete_action_item(action_item_id, actor_employee_id, role="Supervisor",
                         completed_at=None):
    payload = {}
    if completed_at is not None:
        payload["completed_at"] = completed_at
    headers = (make_supervisor_headers(actor_employee_id) if role == "Supervisor"
               else make_committee_chair_headers(actor_employee_id))
    return get_success_data(api_client.complete_action_item(action_item_id, payload,
                                                            headers))


def verify_action_item(action_item_id, chair_id, outcome="PASS", outcome_note=None,
                       due_date=None):
    payload = {"outcome": outcome}
    if outcome_note is not None:
        payload["outcome_note"] = outcome_note
    if due_date is not None:
        payload["due_date"] = due_date
    return get_success_data(api_client.verify_action_item(
        action_item_id, payload, make_committee_chair_headers(chair_id)))


# ---------------------------------------------------------------------------
# Tier 1/2: contractors, claims, recommendations
# ---------------------------------------------------------------------------

def create_contractor_record(name="Acme Erectors", contact_email="safety@acme.example",
                             emr=0.50, trir=0.0, safety_audit_pct=80,
                             insurance_cert_expires_on="2026-12-15"):
    return get_success_data(api_client.create_contractor_org(
        create_contractor_payload(
            name=name, contact_email=contact_email, emr=emr, trir=trir,
            safety_audit_pct=safety_audit_pct,
            insurance_cert_expires_on=insurance_cert_expires_on), ADMIN))


def submit_contractor_record(contractor_id, updates=None):
    """Submit as the ContractorRep whose identity is the org's own id."""
    return get_success_data(api_client.submit_contractor(
        contractor_id, updates or {}, make_contractor_rep_headers(contractor_id)))


def get_contractor(contractor_id):
    return get_success_data(api_client.get_contractor_org(contractor_id, ADMIN))


def setup_contractor_under_review(emr=0.50, trir=0.0, safety_audit_pct=80,
                                  insurance_cert_expires_on="2026-12-15",
                                  name="Acme Erectors"):
    """Contractor registered and submitted; stands UNDER_REVIEW."""
    contractor = create_contractor_record(
        name=name, emr=emr, trir=trir, safety_audit_pct=safety_audit_pct,
        insurance_cert_expires_on=insurance_cert_expires_on)
    return submit_contractor_record(contractor["id"])


def create_claim_record(program_id, manager_id, occurred_on="2026-03-01",
                        kind="INDEMNITY", incurred_cents=100_000, employee_id=None,
                        contractor_org_id=None):
    return get_success_data(api_client.create_claim(
        create_claim_payload(program_id, occurred_on=occurred_on, kind=kind,
                             incurred_cents=incurred_cents, employee_id=employee_id,
                             contractor_org_id=contractor_org_id),
        make_safety_manager_headers(manager_id)))


def accept_claim_record(claim_id, manager_id, incurred_cents=None):
    payload = {}
    if incurred_cents is not None:
        payload["incurred_cents"] = incurred_cents
    return get_success_data(api_client.accept_claim(
        claim_id, payload, make_safety_manager_headers(manager_id)))


def create_recommendation_record(program_id, carrier_name="Acme Mutual",
                                 priority="HIGH",
                                 description="Install machine guarding",
                                 due_date="2026-09-01T00:00:00Z"):
    return get_success_data(api_client.create_recommendation(
        create_recommendation_payload(program_id, carrier_name=carrier_name,
                                      priority=priority, description=description,
                                      due_date=due_date), CARRIER))


# ---------------------------------------------------------------------------
# Tier 1/2: training assignments
# ---------------------------------------------------------------------------

def create_assignment_record(employee_id, course_id, actor_employee_id,
                             due_date="2026-06-20T00:00:00Z", role="Supervisor"):
    headers = (make_supervisor_headers(actor_employee_id) if role == "Supervisor"
               else make_safety_manager_headers(actor_employee_id))
    return get_success_data(api_client.create_training_assignment(
        create_training_assignment_payload(employee_id, course_id, due_date=due_date),
        headers))


def complete_assignment(assignment_id, actor_employee_id, role="Supervisor",
                        completed_at=None):
    payload = {}
    if completed_at is not None:
        payload["completed_at"] = completed_at
    headers = (make_supervisor_headers(actor_employee_id) if role == "Supervisor"
               else make_safety_manager_headers(actor_employee_id))
    return get_success_data(api_client.complete_training_assignment(
        assignment_id, payload, headers))


def list_assignments(employee_id=None, course_id=None, status=None):
    params = {}
    if employee_id is not None:
        params["employee_id"] = employee_id
    if course_id is not None:
        params["course_id"] = course_id
    if status is not None:
        params["status"] = status
    rows, _meta = validate_paginated(
        api_client.list_training_assignments(ADMIN, params=params))
    return rows


# ---------------------------------------------------------------------------
# Tier 5: program close-out fixtures
# ---------------------------------------------------------------------------

def list_awards(program_id=None, employee_id=None, status=None):
    params = {}
    if program_id is not None:
        params["program_id"] = program_id
    if employee_id is not None:
        params["employee_id"] = employee_id
    if status is not None:
        params["status"] = status
    rows, _meta = validate_paginated(
        api_client.list_incentive_awards(ADMIN, params=params))
    return rows


def setup_closed_program_with_meeting_awards(member_count=1,
                                             incentive_budget_cents=1_000_000,
                                             scoring_variant="LEADING_ONLY",
                                             clock=DEFAULT_TEST_CLOCK):
    """ACTIVE program whose only leading activity is one held+published meeting
    attended by `member_count` committee members (5 points each), then CLOSED.

    Returns dict(program, members, manager, meeting, awards).
    """
    set_clock(clock)
    program = create_active_program(scoring_variant=scoring_variant,
                                    incentive_budget_cents=incentive_budget_cents,
                                    quorum_min=1)
    member_names = [f"Member {chr(ord('A') + i)}" for i in range(member_count)]
    role, employees = setup_roster(member_names=member_names, plain_names=("Marta M",))
    manager = employees["Marta M"]
    members = [employees[name] for name in member_names]
    meeting = setup_published_meeting(
        program["id"], manager["id"], [m["id"] for m in members])
    program = get_success_data(api_client.close_program(program["id"], ADMIN))
    awards = list_awards(program_id=program["id"])
    return {"program": program, "members": members, "manager": manager,
            "meeting": meeting, "awards": awards}


def setup_closed_program_with_40_point_award(incentive_budget_cents=9_000):
    """CLOSED LEADING_ONLY program where employee Xavier X earned exactly 40
    points: observation validated (10) + control verified late (15) + meeting
    attended (5) + action item verified (10) -> award payout 6000 cents.

    Returns dict(program, x, manager, award, meeting, hazard, control).
    """
    set_clock("2026-06-01T00:00:00Z")
    program = create_active_program(scoring_variant="LEADING_ONLY",
                                    incentive_budget_cents=incentive_budget_cents,
                                    quorum_min=1)
    role, employees = setup_roster(member_names=("Xavier X",),
                                   plain_names=("Marta M",))
    x = employees["Xavier X"]
    manager = employees["Marta M"]

    hazard = create_hazard_record(program["id"], manager["id"],
                                  identified_by=x["id"], location="Yard",
                                  description="Oil sheen")
    hazard = assess_hazard(hazard["id"], manager["id"], severity=3, probability=2)
    control = add_control(hazard["id"], x["id"], manager["id"],
                          description="Absorbent pads",
                          due_date="2026-06-10T00:00:00Z")
    observation = create_observation_record(program["id"], x["id"],
                                            kind="OBSERVATION",
                                            description="Slippery patch")
    triage_observation_link(observation["id"], hazard["id"], manager["id"])

    # Verify LATE (clock past the control's due date) so timeliness is 1.0.
    set_clock("2026-06-15T00:00:00Z")
    implement_control(control["id"], x["id"], role="Supervisor")
    verify_control(control["id"], manager["id"], outcome="PASS")

    meeting = setup_published_meeting(program["id"], manager["id"], [x["id"]],
                                      scheduled_start="2026-06-16T09:00:00Z",
                                      scheduled_end="2026-06-16T10:00:00Z",
                                      minutes_text="Spill review")
    item = create_action_item_record(meeting["id"], manager["id"], x["id"],
                                     description="Post spill kit sign",
                                     due_date="2026-06-20T00:00:00Z")
    complete_action_item(item["id"], x["id"], role="Supervisor")
    verify_action_item(item["id"], manager["id"], outcome="PASS")

    program = get_success_data(api_client.close_program(program["id"], ADMIN))
    award = list_awards(program_id=program["id"], employee_id=x["id"])[0]
    return {"program": program, "x": x, "manager": manager, "award": award,
            "meeting": meeting, "hazard": hazard, "control": control}


def setup_dual_variant_scenario():
    """Two programs, identical leading-indicator activity by employee Ann A,
    differing only in scoring variant; both CLOSED. Ann A: observation validated
    (10) + control verified on time (19) + meeting attended (5) = 34 points;
    the BALANCED program adds the 50-point claims-free bonus.

    Returns dict(leading, balanced, a, manager) where each program entry carries
    the program dict and Ann A's award in it.
    """
    set_clock("2026-06-01T00:00:00Z")
    role = create_job_role(title="Laborer", hazard_class="LOW")
    ann = create_employee_record(role["id"], full_name="Ann A",
                                 committee_member=True)
    manager = create_employee_record(role["id"], full_name="Marta M")

    result = {"a": ann, "manager": manager}
    for key, variant, year in (("leading", "LEADING_ONLY", 2026),
                               ("balanced", "BALANCED", 2027)):
        program = create_active_program(
            program_year=year, scoring_variant=variant,
            incentive_budget_cents=1_000_000, quorum_min=1)
        hazard, controls = setup_hazard_with_controls(
            program["id"], ann["id"], manager["id"], control_count=1,
            implementer_id=ann["id"], severity=3, probability=2,
            due_date="2026-06-20T00:00:00Z",
            location="Dock 1" if key == "leading" else "Dock 2",
            description="Frayed cable" if key == "leading" else "Blocked exit")
        observation = create_observation_record(
            program["id"], ann["id"], kind="OBSERVATION",
            description="Cable sparks" if key == "leading" else "Exit blocked")
        triage_observation_link(observation["id"], hazard["id"], manager["id"])
        implement_control(controls[0]["id"], ann["id"], role="Supervisor")
        verify_control(controls[0]["id"], manager["id"], outcome="PASS")
        setup_published_meeting(program["id"], manager["id"], [ann["id"]],
                                minutes_text="Reviewed dock hazards")
        program = get_success_data(api_client.close_program(program["id"], ADMIN))
        award = list_awards(program_id=program["id"], employee_id=ann["id"])[0]
        result[key] = {"program": program, "award": award,
                       "hazard_id": hazard["id"], "observation_id": observation["id"]}
    return result


def setup_emr_claims_scenario():
    """ACTIVE 2026 program (payroll $400k/$300k/$100k at ELR 1.10/1.80/3.20) with
    three claims: C1 INDEMNITY $20000 ACCEPTED, C2 MEDICAL_ONLY $8000 ACCEPTED,
    C3 INDEMNITY $50000 still REPORTED (provisional-basis only).

    Returns dict(program, program_version, manager, claims).
    """
    set_clock("2026-06-01T00:00:00Z")
    program = create_active_program(
        program_year=2026, scoring_variant="LEADING_ONLY",
        incentive_budget_cents=1_000_000,
        payroll_by_class=[{"hazard_class": "LOW", "payroll_cents": 40_000_000},
                          {"hazard_class": "MODERATE", "payroll_cents": 30_000_000},
                          {"hazard_class": "HIGH", "payroll_cents": 10_000_000}],
        elr_by_class=[{"hazard_class": "LOW", "elr": 1.10},
                      {"hazard_class": "MODERATE", "elr": 1.80},
                      {"hazard_class": "HIGH", "elr": 3.20}])
    role = create_job_role(title="EHS Manager", hazard_class="LOW")
    manager = create_employee_record(role["id"], full_name="Mgr One")
    claims = {
        "c1": create_claim_record(program["id"], manager["id"],
                                  occurred_on="2026-03-01", kind="INDEMNITY",
                                  incurred_cents=2_000_000),
        "c2": create_claim_record(program["id"], manager["id"],
                                  occurred_on="2026-03-05", kind="MEDICAL_ONLY",
                                  incurred_cents=800_000),
        "c3": create_claim_record(program["id"], manager["id"],
                                  occurred_on="2026-04-01", kind="INDEMNITY",
                                  incurred_cents=5_000_000),
    }
    accept_claim_record(claims["c1"]["id"], manager["id"])
    accept_claim_record(claims["c2"]["id"], manager["id"])
    return {"program": program, "program_version": program["version"],
            "manager": manager, "claims": claims}
