"""Composite setup helpers.

Each test runs against a freshly-launched, empty server. Every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use
get_success_data() (lenient) internally so setup failures surface as clear
"Setup failed" errors.

The dominant preamble in this domain is the enroll chain:
    create program -> (pin clock) -> create participant -> create+certify LOC
    (-> ELIGIBLE) -> create care plan + goal + required signatures -> submit ->
    activate (-> participant has active care plan) -> enroll (-> ENROLLED).
Most fixtures below are layered on top of this chain.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS

PA = TEST_USERS["program_admin_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
MD = TEST_USERS["medical_director_headers"]
NS = TEST_USERS["nurse_staff_headers"]
BS = TEST_USERS["billing_specialist_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, PA))


# ---------------------------------------------------------------------------
# Tier 1: primitives
# ---------------------------------------------------------------------------
def create_program(**overrides):
    payload = {
        "name": "Test PACE Center",
        "state_code": "CA",
        "daily_census_capacity": 50,
        "max_roster": 100,
        "medicaid_monthly_rate_cents": 350000,
        "medicare_monthly_rate_cents": 280000,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_program(payload, PA))


def create_participant(program_id, **overrides):
    payload = {
        "program_id": program_id,
        "full_name": "Test Participant",
        "date_of_birth": "1955-01-01",
        "dual_eligible": True,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_participant(payload, IC))


def create_certified_loc(participant_id, nf_score=75, assessed_on="2026-05-01", **overrides):
    """Create a LOC assessment and certify it (bubbles APPLICANT -> ELIGIBLE)."""
    payload = {"participant_id": participant_id, "nf_score": nf_score, "assessed_on": assessed_on}
    payload.update(overrides)
    loc = get_success_data(api_client.create_loc_assessment(payload, IC))
    get_success_data(api_client.certify_loc_assessment(loc["id"], MD))
    return loc


def create_active_care_plan(participant_id, goal_discipline="RN",
                            sign_disciplines=("RN", "SW", "MEDICAL_DIRECTOR"),
                            supersedes_care_plan_id=None, required_disciplines=None):
    """Create a care plan, add a goal, sign required disciplines, submit, and activate.

    Returns the ACTIVE care plan. Signatures are applied with the correct signing
    role per discipline (any of MedicalDirector/NurseStaff/IntakeCoordinator may sign).
    """
    payload = {"participant_id": participant_id}
    if supersedes_care_plan_id is not None:
        payload["supersedes_care_plan_id"] = supersedes_care_plan_id
    if required_disciplines is not None:
        payload["required_disciplines"] = required_disciplines
    cp = get_success_data(api_client.create_care_plan(payload, IC))
    get_success_data(api_client.add_care_plan_goal(
        cp["id"], {"discipline": goal_discipline, "description": "Goal"}, IC))
    for disc in sign_disciplines:
        signer = MD if disc == "MEDICAL_DIRECTOR" else (NS if disc == "RN" else IC)
        get_success_data(api_client.sign_care_plan(cp["id"], {"discipline": disc}, signer))
    get_success_data(api_client.submit_care_plan(cp["id"], IC))
    return get_success_data(api_client.activate_care_plan(cp["id"], MD))


def create_in_review_care_plan(participant_id, sign_disciplines=("RN",)):
    """Create a care plan, add a goal, sign the given disciplines, and submit to IN_REVIEW.

    By default signs only RN so the plan is IN_REVIEW but NOT activatable
    (required set {RN, SW, MEDICAL_DIRECTOR} incomplete)."""
    cp = get_success_data(api_client.create_care_plan({"participant_id": participant_id}, IC))
    get_success_data(api_client.add_care_plan_goal(
        cp["id"], {"discipline": "RN", "description": "Goal"}, IC))
    for disc in sign_disciplines:
        signer = MD if disc == "MEDICAL_DIRECTOR" else (NS if disc == "RN" else IC)
        get_success_data(api_client.sign_care_plan(cp["id"], {"discipline": disc}, signer))
    return get_success_data(api_client.submit_care_plan(cp["id"], IC))


# ---------------------------------------------------------------------------
# Tier 2/3: full lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_eligible_participant(program_id=None, dob="1955-01-01", dual_eligible=True,
                              program_overrides=None, nf_score=75, assessed_on="2026-05-01"):
    """Program + participant + certified LOC. Participant ends ELIGIBLE (no care plan yet).
    Returns (program, participant, loc)."""
    program = create_program(**(program_overrides or {})) if program_id is None else \
        get_success_data(api_client.get_program(program_id, PA))
    participant = create_participant(program["id"], date_of_birth=dob, dual_eligible=dual_eligible)
    loc = create_certified_loc(participant["id"], nf_score=nf_score, assessed_on=assessed_on)
    return program, participant, loc


def setup_enrolled_participant(program=None, program_overrides=None, dob="1955-01-01",
                              dual_eligible=True, effective_date="2026-06-01",
                              nf_score=75, assessed_on="2026-05-01"):
    """Full enroll chain through ENROLLED.

    Returns (program, participant, care_plan). The participant is ENROLLED with an
    OPEN enrollment, an ACTIVE care plan, and a certified LOC.
    """
    if program is None:
        program = create_program(**(program_overrides or {}))
    participant = create_participant(program["id"], date_of_birth=dob, dual_eligible=dual_eligible)
    create_certified_loc(participant["id"], nf_score=nf_score, assessed_on=assessed_on)
    care_plan = create_active_care_plan(participant["id"])
    get_success_data(api_client.enroll_participant(
        participant["id"], {"enrollment_effective_date": effective_date}, IC))
    participant = get_success_data(api_client.get_participant(participant["id"], BS))
    return program, participant, care_plan


def get_participant_version(participant_id, headers=BS):
    return get_success_data(api_client.get_participant(participant_id, headers))["version"]


def create_draft_capitation(participant_id, service_month, proration_mode="FULL_MONTH"):
    """Create a DRAFT capitation payment. Returns the payment."""
    payload = {"participant_id": participant_id, "service_month": service_month,
               "proration_mode": proration_mode}
    return get_success_data(api_client.create_capitation_payment(payload, BS))


def finalize_capitation(payment_id, participant_id):
    """Finalize a capitation payment, reading the participant's current version first."""
    ver = get_participant_version(participant_id)
    return get_success_data(api_client.finalize_capitation_payment(
        payment_id, {"expected_participant_version": ver}, BS))


def setup_finalized_capitation(program_overrides=None, dual_eligible=True,
                               effective_date="2026-06-01", service_month="2026-06-01",
                               proration_mode="FULL_MONTH", clock="2026-06-15T12:00:00Z",
                               assessed_on="2026-05-01"):
    """Enroll a participant and finalize one capitation payment for service_month.
    Returns (program, participant, payment)."""
    program = create_program(**(program_overrides or {}))
    set_clock(clock)
    program, participant, _ = setup_enrolled_participant(
        program=program, dual_eligible=dual_eligible, effective_date=effective_date,
        assessed_on=assessed_on)
    payment = create_draft_capitation(participant["id"], service_month, proration_mode)
    payment = finalize_capitation(payment["id"], participant["id"])
    participant = get_success_data(api_client.get_participant(participant["id"], BS))
    return program, participant, payment


# ---------------------------------------------------------------------------
# Disenrollment helpers
# ---------------------------------------------------------------------------
def submit_disenrollment(participant_id, kind="VOLUNTARY", reason_code="MOVED",
                         requested_effective_date="2026-08-01", as_headers=IC):
    payload = {"participant_id": participant_id, "kind": kind, "reason_code": reason_code,
               "requested_effective_date": requested_effective_date}
    return get_success_data(api_client.create_disenrollment_request(payload, as_headers))


def approve_disenrollment(request_id):
    return get_success_data(api_client.approve_disenrollment_request(request_id, MD))


def finalize_disenrollment(request_id, participant_id):
    ver = get_participant_version(participant_id)
    return get_success_data(api_client.finalize_disenrollment_request(
        request_id, {"expected_participant_version": ver}, BS))


def setup_approved_disenrollment(kind="VOLUNTARY", reason_code="MOVED",
                                 requested_effective_date="2026-08-01",
                                 effective_date="2026-06-01", clock="2026-06-15T12:00:00Z",
                                 program_overrides=None, submit_as=IC):
    """Enroll a participant and submit+approve a disenrollment request (participant
    DISENROLLMENT_PENDING). Returns (program, participant, request)."""
    program = create_program(**(program_overrides or {}))
    set_clock(clock)
    program, participant, care_plan = setup_enrolled_participant(
        program=program, effective_date=effective_date)
    req = submit_disenrollment(participant["id"], kind=kind, reason_code=reason_code,
                               requested_effective_date=requested_effective_date,
                               as_headers=submit_as)
    req = approve_disenrollment(req["id"])
    participant = get_success_data(api_client.get_participant(participant["id"], BS))
    return program, participant, req


def setup_disenrolled_participant(reason_code="MOVED",
                                  requested_effective_date="2026-08-01",
                                  effective_date="2026-06-01", clock="2026-06-15T12:00:00Z",
                                  program_overrides=None):
    """Full lifecycle through DISENROLLED. Returns (program, participant, request)."""
    program, participant, req = setup_approved_disenrollment(
        reason_code=reason_code, requested_effective_date=requested_effective_date,
        effective_date=effective_date, clock=clock, program_overrides=program_overrides)
    req = finalize_disenrollment(req["id"], participant["id"])
    participant = get_success_data(api_client.get_participant(participant["id"], BS))
    return program, participant, req


# ---------------------------------------------------------------------------
# Attendance / transport / medication helpers
# ---------------------------------------------------------------------------
def create_attendance_day(participant_id, service_date, as_headers=NS, **overrides):
    payload = {"participant_id": participant_id, "service_date": service_date}
    payload.update(overrides)
    return get_success_data(api_client.create_attendance_day(payload, as_headers))


def create_transport_leg(attendance_day_id, direction="PICKUP", window_start_min=480,
                         window_end_min=540, vehicle_id="VAN1", as_headers=NS):
    payload = {"attendance_day_id": attendance_day_id, "direction": direction,
               "window_start_min": window_start_min, "window_end_min": window_end_min,
               "vehicle_id": vehicle_id}
    return get_success_data(api_client.create_transport_leg(payload, as_headers))


def create_active_med_order(participant_id, care_plan_id, drug_name="Metformin", daily_doses=2):
    """Create a med order and activate it (care plan must be ACTIVE). Returns ACTIVE order."""
    mo = get_success_data(api_client.create_medication_order(
        {"participant_id": participant_id, "care_plan_id": care_plan_id,
         "drug_name": drug_name, "daily_doses": daily_doses}, NS))
    return get_success_data(api_client.activate_medication_order(mo["id"], NS))


def setup_checked_in_day(program_overrides=None, service_date="2026-06-02",
                         clock="2026-06-02T08:00:00Z", effective_date="2026-06-01"):
    """Enrolled participant with one CHECKED_IN attendance day on service_date.
    Returns (program, participant, care_plan, day)."""
    program = create_program(**(program_overrides or {}))
    set_clock(clock)
    program, participant, care_plan = setup_enrolled_participant(
        program=program, effective_date=effective_date)
    day = create_attendance_day(participant["id"], service_date)
    day = get_success_data(api_client.check_in_attendance_day(day["id"], NS))
    return program, participant, care_plan, day


def complete_day(day_id):
    return get_success_data(api_client.complete_attendance_day(day_id, NS))
