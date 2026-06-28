"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server before
each test), so every fixture builds all preconditions from scratch using only
PRD-declared endpoints. Fixtures use get_success_data() (lenient) internally so a
setup failure surfaces as a clear "Setup failed" rather than an opaque assertion.

Role-identity threading: SchoolAdmin and Registrar are opaque identities (PRD §2.1)
and use the shared TEST_USERS constants. Instructor and ThirdPartyExaminer are backed
by Instructor records — any ownership-gated call (complete a session as its delivering
instructor, grade as the named examiner) uses make_instructor_headers(instructor_id)
or make_examiner_headers(examiner_id) with the real Instructor.id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_instructor_headers, make_examiner_headers
from .factories import (
    create_program_payload, create_truck_payload, create_instructor_payload,
    create_carrier_payload, create_enrollment_payload, create_prereq_document_payload,
    create_clock_session_payload, create_skills_test_payload, grade_skills_test_payload,
    create_sponsorship_offer_payload, create_finance_plan_payload,
    create_completion_report_payload,
)

ADMIN = TEST_USERS["school_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
FUTURE_EXPIRY = "2027-01-01T00:00:00Z"


# --- Tier 1: primitive resource creation -------------------------------------

def create_program(**overrides) -> dict:
    resp = api_client.create_program(create_program_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_truck(**overrides) -> dict:
    resp = api_client.create_truck(create_truck_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_instructor(**overrides) -> dict:
    resp = api_client.create_instructor(create_instructor_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_carrier(**overrides) -> dict:
    resp = api_client.create_carrier(create_carrier_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_enrollment(program_id, **overrides) -> dict:
    resp = api_client.create_enrollment(
        create_enrollment_payload(program_id, **overrides), REGISTRAR)
    return get_success_data(resp)


# --- Tier 1: state progression for enrollment --------------------------------

def submit_prereq(enrollment_id, kind, expires_on=FUTURE_EXPIRY) -> dict:
    resp = api_client.create_prereq_document(
        enrollment_id, create_prereq_document_payload(kind, expires_on=expires_on), REGISTRAR)
    return get_success_data(resp)


def approve_prereq(document_id) -> dict:
    return get_success_data(api_client.approve_prereq_document(document_id, REGISTRAR))


def create_enrollment_in_training(program_id, **enr_overrides):
    """Create an enrollment and drive it to TRAINING by approving both prereqs.

    Returns (enrollment_id, dot_med_doc_id, clp_doc_id).
    """
    enr = create_enrollment(program_id, **enr_overrides)
    eid = enr["id"]
    med = submit_prereq(eid, "DOT_MEDICAL")
    clp = submit_prereq(eid, "CLP_PERMIT")
    approve_prereq(med["id"])
    approve_prereq(clp["id"])
    return eid, med["id"], clp["id"]


def setup_enrollment_training(program_overrides=None, **enr_overrides):
    """Active program + instructor + truck + enrollment driven to TRAINING.

    Returns dict with keys: program, truck, instructor, enrollment_id,
    dot_med_id, clp_id.
    """
    program = create_program(**(program_overrides or {}))
    truck = create_truck()
    instructor = create_instructor()
    eid, med_id, clp_id = create_enrollment_in_training(program["id"])
    return {
        "program": program,
        "truck": truck,
        "instructor": instructor,
        "enrollment_id": eid,
        "dot_med_id": med_id,
        "clp_id": clp_id,
    }


# --- Tier 1/3: clock sessions ------------------------------------------------

def book_session(enrollment_id, phase, instructor_id, starts_at, duration_minutes,
                 truck_id=None, as_headers=REGISTRAR) -> dict:
    payload = create_clock_session_payload(
        phase, instructor_id, starts_at, duration_minutes, truck_id=truck_id)
    return get_success_data(api_client.create_clock_session(enrollment_id, payload, as_headers))


def complete_session(session_id, instructor_id) -> dict:
    """Complete a session as the instructor who delivers it (ownership-gated)."""
    headers = make_instructor_headers(instructor_id)
    return get_success_data(api_client.complete_clock_session(session_id, headers))


def book_and_complete_session(enrollment_id, phase, instructor_id, starts_at,
                              duration_minutes, truck_id=None) -> dict:
    sess = book_session(enrollment_id, phase, instructor_id, starts_at,
                        duration_minutes, truck_id=truck_id)
    return complete_session(sess["id"], instructor_id)


# --- Tier 3: drive enrollment to TEST_READY ----------------------------------

def setup_enrollment_test_ready(skills_pass_threshold=80,
                                classroom_required_hours=1,
                                range_required_hours=1,
                                road_required_hours=1):
    """Drive an enrollment to TEST_READY by completing one session per required phase,
    plus register a certified examiner who NEVER instructed the enrollment.

    Each required phase gets a 60-minute completed session (1.0 logged hour), so the
    program's per-phase requirements should be <= 1 for the gate to flip. Phases with a
    0 requirement are skipped.

    Returns dict: program, truck, instructor, examiner, enrollment_id, sessions (dict
    keyed by phase), dot_med_id, clp_id.
    """
    program = create_program(
        classroom_required_hours=classroom_required_hours,
        range_required_hours=range_required_hours,
        road_required_hours=road_required_hours,
        skills_pass_threshold=skills_pass_threshold,
    )
    truck = create_truck()
    instructor = create_instructor(full_name="Ivy")
    examiner = create_instructor(full_name="Examiner Ed", examiner_certified=True)
    eid, med_id, clp_id = create_enrollment_in_training(program["id"])

    sessions = {}
    # Use distinct past dates so instructor/truck intervals never overlap.
    if classroom_required_hours and classroom_required_hours > 0:
        sessions["CLASSROOM"] = book_and_complete_session(
            eid, "CLASSROOM", instructor["id"], "2026-03-10T09:00:00Z", 60)
    if range_required_hours and range_required_hours > 0:
        sessions["RANGE"] = book_and_complete_session(
            eid, "RANGE", instructor["id"], "2026-03-11T09:00:00Z", 60, truck_id=truck["id"])
    if road_required_hours and road_required_hours > 0:
        sessions["ROAD"] = book_and_complete_session(
            eid, "ROAD", instructor["id"], "2026-03-12T09:00:00Z", 60, truck_id=truck["id"])

    return {
        "program": program,
        "truck": truck,
        "instructor": instructor,
        "examiner": examiner,
        "enrollment_id": eid,
        "sessions": sessions,
        "dot_med_id": med_id,
        "clp_id": clp_id,
    }


def schedule_skills_test(enrollment_id, examiner_id, supersedes_test_id=None) -> dict:
    payload = create_skills_test_payload(examiner_id)
    if supersedes_test_id is not None:
        payload["supersedes_test_id"] = supersedes_test_id
    return get_success_data(api_client.create_skills_test(enrollment_id, payload, REGISTRAR))


def grade_test(test_id, examiner_id, pre_trip_score, basic_control_score, road_score) -> dict:
    """Grade a skills test as the named examiner (ownership-gated)."""
    headers = make_examiner_headers(examiner_id)
    payload = grade_skills_test_payload(pre_trip_score, basic_control_score, road_score)
    return get_success_data(api_client.grade_skills_test(test_id, payload, headers))


def setup_scheduled_skills_test(skills_pass_threshold=80, **kwargs):
    """Drive to TEST_READY and schedule a SCHEDULED skills test with a clean examiner.

    Returns dict: ...same as setup_enrollment_test_ready plus test (the SkillsTest).
    """
    ctx = setup_enrollment_test_ready(skills_pass_threshold=skills_pass_threshold, **kwargs)
    test = schedule_skills_test(ctx["enrollment_id"], ctx["examiner"]["id"])
    ctx["test"] = test
    return ctx


# --- Tier 3/5: drive enrollment to PASSED and to a DRAFT completion report ----

def setup_enrollment_passed(skills_pass_threshold=80, **kwargs):
    """Drive an enrollment to PASSED via a GRADED PASS skills test (90/90/90).

    Returns dict: ...same as setup_scheduled_skills_test plus the graded test (under
    'test') reflecting outcome PASS.
    """
    ctx = setup_scheduled_skills_test(skills_pass_threshold=skills_pass_threshold, **kwargs)
    graded = grade_test(ctx["test"]["id"], ctx["examiner"]["id"], 90, 90, 90)
    ctx["test"] = graded
    return ctx


def setup_draft_completion_report(**kwargs):
    """Drive to PASSED and draft a CompletionReport referencing the passing test.

    Returns dict: ...same as setup_enrollment_passed plus report (the DRAFT report).
    """
    ctx = setup_enrollment_passed(**kwargs)
    payload = create_completion_report_payload(ctx["test"]["id"])
    report = get_success_data(
        api_client.create_completion_report(ctx["enrollment_id"], payload, ADMIN))
    ctx["report"] = report
    return ctx


def setup_completed_enrollment(**kwargs):
    """Drive an enrollment all the way to COMPLETED (transmitted report).

    Returns dict: ...same as setup_draft_completion_report plus the transmitted report.
    """
    ctx = setup_draft_completion_report(**kwargs)
    transmitted = get_success_data(
        api_client.transmit_completion_report(ctx["report"]["id"], ADMIN))
    ctx["report"] = transmitted
    return ctx


# --- Tier 2/3: sponsorship --------------------------------------------------

def extend_offer(enrollment_id, carrier_id) -> dict:
    payload = create_sponsorship_offer_payload(carrier_id)
    return get_success_data(api_client.create_sponsorship_offer(enrollment_id, payload, REGISTRAR))


def accept_offer(offer_id) -> dict:
    return get_success_data(api_client.accept_sponsorship_offer(offer_id, REGISTRAR))


def setup_accepted_sponsorship(commitment_months=12, reimbursement_cents=600000,
                               months_served=0, drive_to_training=True):
    """Enrollment with an ACCEPTED SponsorshipOffer; optionally advance service months.

    Returns dict: program, carrier, enrollment_id, offer_id.
    """
    program = create_program()
    carrier = create_carrier(commitment_months=commitment_months,
                             reimbursement_cents=reimbursement_cents)
    if drive_to_training:
        eid, _, _ = create_enrollment_in_training(program["id"])
    else:
        eid = create_enrollment(program["id"])["id"]
    offer = extend_offer(eid, carrier["id"])
    accept_offer(offer["id"])
    if months_served > 0:
        get_success_data(api_client.advance_service_months(offer["id"], months_served, ADMIN))
    return {
        "program": program,
        "carrier": carrier,
        "enrollment_id": eid,
        "offer_id": offer["id"],
    }


# --- Tier 4: finance plans ---------------------------------------------------

def create_finance_plan(enrollment_id, term_months, expected_version) -> dict:
    payload = create_finance_plan_payload(term_months, expected_version)
    return get_success_data(api_client.create_finance_plan(enrollment_id, payload, REGISTRAR))


def setup_enrollment_for_finance(tuition_cents=700000):
    """A fresh enrollment (APPLIED is fine for finance plans) on a program with the
    given tuition. Returns dict: program, enrollment (full object with version).
    """
    program = create_program(tuition_cents=tuition_cents)
    enrollment = create_enrollment(program["id"])
    return {"program": program, "enrollment": enrollment}
