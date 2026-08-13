"""Composite setup helpers for the naturalization test suite.

The test harness restarts the API server before every test, so each test starts
against an empty database with the logical clock at 2026-08-01T00:00:00Z (PRD §2.5).
Every helper builds its preconditions from scratch using only PRD-declared endpoints.

Setup calls use the lenient get_success_data validator so a broken precondition
surfaces as a clear "Setup step failed" error rather than a confusing assertion.

Identity threading: ownership-gated calls by entity-backed roles always use
make_volunteer_headers(entity_id) / make_applicant_headers(entity_id) built from the
actual entity id, never the shared TEST_USERS fallback constants.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CASE_STAGE_ORDER
from .factories import (
    STANDARD_ELIGIBLE_SCREENING,
    create_applicant_payload,
    create_attendance_payload,
    create_class_section_payload,
    create_enrollment_payload,
    create_fee_waiver_payload,
    create_mock_interview_payload,
    create_oath_ceremony_payload,
    create_packet_payload,
    create_program_payload,
    create_screening_payload,
    create_seat_payload,
    create_training_credit_payload,
    create_volunteer_payload,
    create_workshop_payload,
)
from .test_users import TEST_USERS, make_volunteer_headers

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["intake_coordinator_headers"]

_email_counter = itertools.count(1)


def _email(prefix: str) -> str:
    return f"{prefix}-{next(_email_counter)}@example.org"


# --- Tier 0: program / clock -------------------------------------------------

def create_program(**overrides) -> dict:
    """Create the singleton Program (PRD §3.1). Returns the Program."""
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), ADMIN)
    )


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock, running the three sweeps (PRD §2.5)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# --- Tier 1: applicants and screenings ----------------------------------------

def register_applicant(full_name="Ana Paz", date_of_birth="1986-04-02", email=None) -> dict:
    payload = create_applicant_payload(
        full_name=full_name, date_of_birth=date_of_birth, email=email or _email("applicant")
    )
    return get_success_data(api_client.create_applicant(payload, COORD))


def get_applicant(applicant_id: str) -> dict:
    return get_success_data(api_client.get_applicant(applicant_id, COORD))


def create_screening(applicant_id: str, **overrides) -> dict:
    """Create a screening under the applicant, reading the applicant fresh so the
    expected_applicant_version concurrency field (PRD §2.7) always matches."""
    applicant = get_applicant(applicant_id)
    payload = create_screening_payload(applicant["version"], **overrides)
    return get_success_data(api_client.create_screening(applicant_id, payload, COORD))


def create_screened_applicant(**screening_overrides) -> tuple:
    """Applicant + ACTIVE screening. With default inputs the outcome is ELIGIBLE and
    the stage advances REGISTERED -> SCREENED (PRD §3.2). Returns (applicant, screening)
    with the applicant re-fetched after the write."""
    applicant = register_applicant()
    screening = create_screening(applicant["id"], **screening_overrides)
    return get_applicant(applicant["id"]), screening


# --- Tier 1: volunteers and accreditation -------------------------------------

def create_volunteer(full_name="Vic Torres", background_check_cleared=True,
                     bar_number=None) -> dict:
    """Create a volunteer (starts TRAINEE, PRD §3.5)."""
    payload = create_volunteer_payload(
        full_name=full_name, email=_email("volunteer"),
        background_check_cleared=background_check_cleared,
    )
    if bar_number is not None:
        payload["bar_number"] = bar_number
    return get_success_data(api_client.create_volunteer(payload, ADMIN))


def get_volunteer(volunteer_id: str) -> dict:
    return get_success_data(api_client.get_volunteer(volunteer_id, ADMIN))


def add_training_credit(volunteer_id: str, hours: int, topic="training",
                        earned_at="2026-07-01T00:00:00Z") -> dict:
    payload = create_training_credit_payload(topic=topic, hours=hours, earned_at=earned_at)
    return get_success_data(api_client.create_training_credit(volunteer_id, payload, ADMIN))


def accredit_volunteer(volunteer_id: str, target_level: str) -> dict:
    return get_success_data(
        api_client.accredit_volunteer(volunteer_id, {"target_level": target_level}, ADMIN)
    )


def create_general_volunteer(training_hours=10, **kwargs) -> dict:
    """Volunteer accredited TRAINEE -> GENERAL (PRD §3.5)."""
    volunteer = create_volunteer(**kwargs)
    add_training_credit(volunteer["id"], training_hours)
    return accredit_volunteer(volunteer["id"], "GENERAL")


def create_legal_volunteer(bar_number="BAR111", **kwargs) -> dict:
    """Volunteer accredited TRAINEE -> GENERAL -> LEGAL via the bar-number path
    (PRD §3.5)."""
    volunteer = create_volunteer(bar_number=bar_number, **kwargs)
    add_training_credit(volunteer["id"], 10)
    accredit_volunteer(volunteer["id"], "GENERAL")
    return accredit_volunteer(volunteer["id"], "LEGAL")


# --- Tier 2: class sections, enrollments, attendance --------------------------

def create_section(instructor_id: str, title="Civics Class", weekday="MON",
                   start_minute=600, end_minute=660, room_id="R1",
                   capacity=2, total_sessions=10) -> dict:
    payload = create_class_section_payload(
        instructor_id, title=title, weekday=weekday, start_minute=start_minute,
        end_minute=end_minute, room_id=room_id, capacity=capacity,
        total_sessions=total_sessions,
    )
    return get_success_data(api_client.create_class_section(payload, ADMIN))


def get_section(section_id: str) -> dict:
    return get_success_data(api_client.get_class_section(section_id, COORD))


def enroll(applicant_id: str, section_id: str) -> dict:
    """Enroll an applicant, reading the section fresh so the expected_section_version
    concurrency field (PRD §2.7) always matches."""
    section = get_section(section_id)
    payload = create_enrollment_payload(applicant_id, section_id, section["version"])
    return get_success_data(api_client.create_enrollment(payload, COORD))


def get_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, COORD))


def record_attendance(enrollment_id: str, entries, instructor_id: str) -> None:
    """Append attendance events. `entries` is a list of (session_index, outcome).
    Recorded as the section's instructor (entity-backed Volunteer identity)."""
    headers = make_volunteer_headers(instructor_id)
    for session_index, outcome in entries:
        get_success_data(
            api_client.create_attendance_record(
                enrollment_id, create_attendance_payload(session_index, outcome), headers
            )
        )


def setup_section_with_enrollees(capacity=1, num_applicants=3, total_sessions=10,
                                 weekday="TUE", start_minute=1080, end_minute=1140,
                                 room_id="R2") -> dict:
    """Program + GENERAL instructor + section + `num_applicants` screened applicants
    each enrolled in order. With capacity < num_applicants the first `capacity`
    enrollments land ENROLLED and the rest WAITLISTED (PRD §3.4).
    Returns dict(section, instructor, applicants, enrollments)."""
    create_program()
    instructor = create_general_volunteer(full_name="Instructor")
    section = create_section(
        instructor["id"], weekday=weekday, start_minute=start_minute,
        end_minute=end_minute, room_id=room_id, capacity=capacity,
        total_sessions=total_sessions,
    )
    applicants, enrollments = [], []
    for i in range(num_applicants):
        applicant, _ = create_screened_applicant()
        applicants.append(applicant)
        enrollments.append(enroll(applicant["id"], section["id"]))
    return {
        "section": get_section(section["id"]),
        "instructor": instructor,
        "applicants": applicants,
        "enrollments": enrollments,
    }


def setup_completed_enrollment(total_sessions=2) -> dict:
    """Section + one ENROLLED enrollment with every session PRESENT, then completed
    by a coordinator (PRD §3.4). Returns dict(section, instructor, applicant, enrollment)."""
    create_program()
    instructor = create_general_volunteer(full_name="Instructor")
    section = create_section(instructor["id"], capacity=2, total_sessions=total_sessions,
                             weekday="TUE", start_minute=600, end_minute=660, room_id="R4")
    applicant, _ = create_screened_applicant()
    enrollment = enroll(applicant["id"], section["id"])
    record_attendance(
        enrollment["id"],
        [(i + 1, "PRESENT") for i in range(total_sessions)],
        instructor["id"],
    )
    enrollment = get_success_data(api_client.complete_enrollment(enrollment["id"], COORD))
    return {
        "section": get_section(section["id"]),
        "instructor": instructor,
        "applicant": applicant,
        "enrollment": enrollment,
    }


# --- Tier 3: workshops and seats ----------------------------------------------

def create_workshop(supervisor_id: str, assisting_volunteer_id=None,
                    scheduled_start="2026-08-05T10:00:00Z", duration_hours=3,
                    capacity=5, title="N-400 Workshop") -> dict:
    payload = create_workshop_payload(
        supervisor_id, title=title, scheduled_start=scheduled_start,
        duration_hours=duration_hours, capacity=capacity,
    )
    if assisting_volunteer_id is not None:
        payload["assisting_volunteer_id"] = assisting_volunteer_id
    return get_success_data(api_client.create_workshop(payload, ADMIN))


def get_workshop(workshop_id: str) -> dict:
    return get_success_data(api_client.get_workshop(workshop_id, COORD))


def reserve_seat(workshop_id: str, applicant_id: str) -> dict:
    """Reserve a seat, reading the workshop fresh so the expected_workshop_version
    concurrency field (PRD §2.7) always matches."""
    workshop = get_workshop(workshop_id)
    payload = create_seat_payload(applicant_id, workshop["version"])
    return get_success_data(api_client.reserve_workshop_seat(workshop_id, payload, COORD))


def get_workshop_seat(seat_id: str) -> dict:
    return get_success_data(api_client.get_workshop_seat(seat_id, COORD))


def complete_workshop(workshop_id: str, supervisor_id: str, at: str = None) -> dict:
    """Advance the clock to `at` (at/after scheduled_start) and mark the workshop held
    as the supervising volunteer (PRD §3.6)."""
    if at is not None:
        set_clock(at)
    return get_success_data(
        api_client.complete_workshop(workshop_id, make_volunteer_headers(supervisor_id))
    )


# --- Tier 4: fee waivers --------------------------------------------------------

def create_fee_waiver(applicant_id: str, household_size=1,
                      self_reported_income_cents=1000000,
                      self_reported_benefit=False) -> dict:
    payload = create_fee_waiver_payload(
        household_size=household_size,
        self_reported_income_cents=self_reported_income_cents,
        self_reported_benefit=self_reported_benefit,
    )
    return get_success_data(api_client.create_fee_waiver_request(applicant_id, payload, COORD))


def get_fee_waiver(request_id: str) -> dict:
    return get_success_data(api_client.get_fee_waiver_request(request_id, COORD))


def submit_fee_waiver(request_id: str, attached_document_count: int) -> dict:
    return get_success_data(
        api_client.submit_fee_waiver_request(
            request_id, {"attached_document_count": attached_document_count}, COORD
        )
    )


def decide_fee_waiver(request_id: str, decision: str, documented_income_cents: int,
                      documented_benefit=False) -> dict:
    payload = {
        "decision": decision,
        "documented_income_cents": documented_income_cents,
        "documented_benefit": documented_benefit,
    }
    return get_success_data(api_client.decide_fee_waiver_request(request_id, payload, ADMIN))


def create_approved_fee_waiver(applicant_id: str, household_size=1, income=1000000,
                               benefit=False) -> dict:
    """Create -> submit (with the computed required document count) -> decide APPROVED
    with documented values equal to the self-reported ones (PRD §3.7)."""
    request = create_fee_waiver(applicant_id, household_size, income, benefit)
    submit_fee_waiver(request["id"], request["required_document_count"])
    return decide_fee_waiver(request["id"], "APPROVED", income, benefit)


# --- Tier 5: packets, filing, cases, ceremonies ---------------------------------

def create_packet(applicant_id: str, seat_id: str, prepared_by: str,
                  fee_waiver_request_id=None) -> dict:
    payload = create_packet_payload(seat_id, prepared_by)
    if fee_waiver_request_id is not None:
        payload["fee_waiver_request_id"] = fee_waiver_request_id
    return get_success_data(api_client.create_packet(applicant_id, payload, COORD))


def get_packet(packet_id: str) -> dict:
    return get_success_data(api_client.get_packet(packet_id, COORD))


def submit_packet_review(packet_id: str) -> dict:
    return get_success_data(api_client.submit_packet_review(packet_id, COORD))


def certify_packet(packet_id: str, certifier_id: str) -> dict:
    """Certify as a LEGAL volunteer distinct from the preparer (PRD §3.8)."""
    return get_success_data(
        api_client.certify_packet(packet_id, make_volunteer_headers(certifier_id))
    )


def setup_packet_pipeline(screening_overrides=None, workshop_start="2026-08-05T10:00:00Z",
                          workshop_capacity=5, duration_hours=3) -> dict:
    """Full preparation pipeline: Program + eligible applicant (attained readiness 80
    with default screening inputs) + GENERAL preparer + LEGAL supervisor + LEGAL
    certifier (distinct from the preparer) + a workshop held at `workshop_start` with
    the applicant's seat ATTENDED.

    Returns dict(program, applicant, screening, preparer, supervisor, certifier,
    workshop, seat).
    """
    program = create_program()
    applicant, screening = create_screened_applicant(**(screening_overrides or {}))
    preparer = create_general_volunteer(full_name="Prep Vol")
    supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
    certifier = create_legal_volunteer(full_name="Cert Vol", bar_number="BAR222")
    workshop = create_workshop(
        supervisor["id"], scheduled_start=workshop_start,
        capacity=workshop_capacity, duration_hours=duration_hours,
    )
    seat = reserve_seat(workshop["id"], applicant["id"])
    workshop = complete_workshop(workshop["id"], supervisor["id"], at=workshop_start)
    return {
        "program": program,
        "applicant": get_applicant(applicant["id"]),
        "screening": screening,
        "preparer": preparer,
        "supervisor": supervisor,
        "certifier": certifier,
        "workshop": workshop,
        "seat": get_workshop_seat(seat["id"]),
    }


def create_packet_in_review(pipeline: dict, fee_waiver_request_id=None) -> dict:
    """Create a packet from the pipeline's ATTENDED seat and move DRAFT ->
    IN_LEGAL_REVIEW (PRD §3.8)."""
    packet = create_packet(
        pipeline["applicant"]["id"], pipeline["seat"]["id"],
        pipeline["preparer"]["id"], fee_waiver_request_id,
    )
    submit_packet_review(packet["id"])
    return get_packet(packet["id"])


def setup_certified_pipeline(**kwargs) -> dict:
    """setup_packet_pipeline + packet certified by the pipeline's certifier.
    Adds key `packet` (status CERTIFIED)."""
    pipeline = setup_packet_pipeline(**kwargs)
    packet = create_packet_in_review(pipeline)
    pipeline["packet"] = certify_packet(packet["id"], pipeline["certifier"]["id"])
    return pipeline


def setup_filed_case(**kwargs) -> dict:
    """setup_certified_pipeline + filing, which creates the applicant's USCISCase
    (PRD §3.8). Adds key `case` (stage FILED, rfe_status NONE)."""
    pipeline = setup_certified_pipeline(**kwargs)
    case = get_success_data(api_client.file_packet(pipeline["packet"]["id"], COORD))
    pipeline["case"] = case
    return pipeline


def advance_case(case_id: str, to_stage: str) -> dict:
    return get_success_data(api_client.advance_case(case_id, {"to_stage": to_stage}, ADMIN))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_case(case_id, ADMIN))


def advance_case_to(case_id: str, target_stage: str) -> dict:
    """Walk the case along the linear stage order (PRD §3.9) to `target_stage`."""
    case = get_case(case_id)
    index = CASE_STAGE_ORDER.index(case["stage"])
    while CASE_STAGE_ORDER[index] != target_stage:
        index += 1
        case = advance_case(case_id, CASE_STAGE_ORDER[index])
    return case


def setup_oath_ready_case(**kwargs) -> dict:
    """setup_filed_case + advancement to APPROVED_PENDING_OATH (PRD §3.9)."""
    pipeline = setup_filed_case(**kwargs)
    pipeline["case"] = advance_case_to(pipeline["case"]["id"], "APPROVED_PENDING_OATH")
    return pipeline


def setup_two_oath_ready_cases() -> dict:
    """Two applicants whose cases both sit at APPROVED_PENDING_OATH, sharing one
    completed workshop (capacity 5, one seat each) and the same preparer/certifier
    volunteers. Returns dict(supervisor, preparer, certifier, workshop, applicants,
    packets, cases)."""
    create_program()
    applicant_a, _ = create_screened_applicant()
    applicant_b, _ = create_screened_applicant()
    preparer = create_general_volunteer(full_name="Prep Vol")
    supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
    certifier = create_legal_volunteer(full_name="Cert Vol", bar_number="BAR222")
    workshop = create_workshop(supervisor["id"], capacity=5)
    seat_a = reserve_seat(workshop["id"], applicant_a["id"])
    seat_b = reserve_seat(workshop["id"], applicant_b["id"])
    complete_workshop(workshop["id"], supervisor["id"], at="2026-08-05T10:00:00Z")
    cases, packets = [], []
    for applicant, seat in ((applicant_a, seat_a), (applicant_b, seat_b)):
        packet = create_packet(applicant["id"], seat["id"], preparer["id"])
        submit_packet_review(packet["id"])
        packet = certify_packet(packet["id"], certifier["id"])
        packets.append(packet)
        case = get_success_data(api_client.file_packet(packet["id"], COORD))
        cases.append(advance_case_to(case["id"], "APPROVED_PENDING_OATH"))
    return {
        "supervisor": supervisor,
        "preparer": preparer,
        "certifier": certifier,
        "workshop": get_workshop(workshop["id"]),
        "applicants": [applicant_a, applicant_b],
        "packets": packets,
        "cases": cases,
    }


# --- Tier 5: oath ceremonies ----------------------------------------------------

def create_ceremony(ceremony_date="2026-09-01T17:00:00Z", venue="City Hall",
                    capacity=2) -> dict:
    return get_success_data(
        api_client.create_oath_ceremony(
            create_oath_ceremony_payload(
                ceremony_date=ceremony_date, venue=venue, capacity=capacity
            ),
            ADMIN,
        )
    )


def get_ceremony(ceremony_id: str) -> dict:
    return get_success_data(api_client.get_oath_ceremony(ceremony_id, ADMIN))


def assign_case_to_ceremony(ceremony_id: str, case_id: str) -> dict:
    """Assign a case, reading the ceremony fresh so the expected_ceremony_version
    concurrency field (PRD §2.7) always matches."""
    ceremony = get_ceremony(ceremony_id)
    payload = {"case_id": case_id, "expected_ceremony_version": ceremony["version"]}
    return get_success_data(api_client.assign_oath_ceremony(ceremony_id, payload, ADMIN))


# --- Tier 2: mock interviews ----------------------------------------------------

def book_mock_interview(applicant_id: str, volunteer_id: str,
                        scheduled_start="2026-08-10T10:00:00Z",
                        duration_minutes=30) -> dict:
    payload = create_mock_interview_payload(
        applicant_id, volunteer_id, scheduled_start=scheduled_start,
        duration_minutes=duration_minutes,
    )
    return get_success_data(api_client.create_mock_interview(payload, COORD))


def setup_mock_booking_context() -> dict:
    """Program + eligible applicant (attained readiness 80, which clears the 40-point
    mock booking floor) + GENERAL volunteer interviewer (PRD §3.3).
    Returns dict(applicant, screening, volunteer)."""
    create_program()
    applicant, screening = create_screened_applicant()
    volunteer = create_general_volunteer(full_name="Interviewer")
    return {"applicant": applicant, "screening": screening, "volunteer": volunteer}
