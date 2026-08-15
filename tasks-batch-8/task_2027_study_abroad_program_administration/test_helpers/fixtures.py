"""Composite setup helpers (PRD §3 workflows).

Each helper builds its preconditions from scratch via PRD-declared endpoints
only, and returns the created resources as plain dicts. Setup calls use the
lenient get_success_data() validator so a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion failure.

Segregation of duties (PRD §3.2): clearance is recorded by coordinator
"coord-a" and approval performed by a different coordinator "coord-b".
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_application_payload,
    create_clearance_payload,
    create_course_preapproval_payload,
    create_credit_posting_payload,
    create_incident_payload,
    create_insurance_enrollment_payload,
    create_lifecycle_payload,
    create_partner_agreement_payload,
    create_payment_payload,
    create_program_payload,
    create_review_payload,
    create_student_payload,
    create_travel_advisory_payload,
)
from .test_users import (
    BURSAR_HEADERS,
    COORD_A_HEADERS,
    COORD_B_HEADERS,
    FACULTY_HEADERS,
    SAFETY_HEADERS,
    make_student_headers,
)

# Canonical FR program window used across fixtures (before the 2026-11-01
# deadline at the default logical clock of 2026-08-01T00:00:00Z).
DEFAULT_PROGRAM_START = "2027-01-10T00:00:00Z"
DEFAULT_PROGRAM_END = "2027-05-10T00:00:00Z"
DEFAULT_COVERAGE_START = "2027-01-01T00:00:00Z"
DEFAULT_COVERAGE_END = "2027-05-31T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-entity state progression
# ---------------------------------------------------------------------------

def create_partner_agreement(activate: bool = True, **overrides) -> dict:
    """Create a PartnerAgreement; activate it by default (PRD §3.1)."""
    payload = create_partner_agreement_payload(**overrides)
    agreement = get_success_data(
        api_client.create_partner_agreement(payload, COORD_A_HEADERS)
    )
    if activate:
        agreement = get_success_data(
            api_client.activate_partner_agreement(agreement["id"], COORD_A_HEADERS)
        )
    return agreement


def create_draft_program(agreement_id: Optional[str] = None, **overrides) -> dict:
    """Create a DRAFT Program under an agreement (creates one when omitted)."""
    if agreement_id is None:
        agreement_id = create_partner_agreement()["id"]
    payload = create_program_payload(agreement_id, **overrides)
    return get_success_data(api_client.create_program(payload, COORD_A_HEADERS))


def create_open_program(agreement_id: Optional[str] = None, **overrides) -> dict:
    """Create a Program and publish it to OPEN (PRD §3.1)."""
    program = create_draft_program(agreement_id, **overrides)
    return get_success_data(api_client.publish_program(program["id"], COORD_A_HEADERS))


def create_student(**overrides) -> dict:
    """Register a Student record (PRD §3.2)."""
    return get_success_data(
        api_client.create_student(create_student_payload(**overrides), COORD_A_HEADERS)
    )


def create_submitted_application(student: dict, program: dict) -> dict:
    """Submit an Application (born SUBMITTED) as the owning student."""
    payload = create_application_payload(student["id"], program["id"])
    return get_success_data(
        api_client.create_application(payload, make_student_headers(student["id"]))
    )


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — program + student + application
# ---------------------------------------------------------------------------

def setup_open_program_with_application(
    student_overrides: Optional[dict] = None,
    program_overrides: Optional[dict] = None,
    agreement_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict]:
    """ACTIVE agreement + OPEN program + one SUBMITTED application.

    Returns (program, student, application).
    """
    agreement = create_partner_agreement(**(agreement_overrides or {}))
    program = create_open_program(agreement["id"], **(program_overrides or {}))
    student = create_student(**(student_overrides or {}))
    application = create_submitted_application(student, program)
    return program, student, application


# ---------------------------------------------------------------------------
# Tier 3: application lifecycle shortcuts
# ---------------------------------------------------------------------------

def clear_application(application: dict, decision: str = "CLEARED") -> dict:
    """Record a clearance decision as coordinator coord-a (PRD §3.2)."""
    return get_success_data(
        api_client.record_clearance(
            application["id"], create_clearance_payload(decision), COORD_A_HEADERS,
        )
    )


def approve_application(application_id: str) -> dict:
    """Approve a CLEARED application as coordinator coord-b (distinct from
    the clearance recorder, per the segregation-of-duties rule in PRD §3.2)."""
    return get_success_data(api_client.approve_application(application_id, COORD_B_HEADERS))


def commit_application(application: dict, student: dict) -> dict:
    """Owning student commits an APPROVED application (PRD §3.4)."""
    return get_success_data(
        api_client.commit_application(
            application["id"], make_student_headers(student["id"]),
        )
    )


def create_cleared_application(
    student_overrides: Optional[dict] = None,
    program_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict]:
    """OPEN program + one application walked to CLEARED.

    Returns (program, student, application).
    """
    program, student, application = setup_open_program_with_application(
        student_overrides, program_overrides,
    )
    application = clear_application(application, "CLEARED")
    return program, student, application


def create_approved_application(
    student_overrides: Optional[dict] = None,
    program_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict]:
    """OPEN program + one application walked to APPROVED.

    Returns (program, student, application).
    """
    program, student, application = create_cleared_application(
        student_overrides, program_overrides,
    )
    application = approve_application(application["id"])
    return program, student, application


def create_committed_application(
    student_overrides: Optional[dict] = None,
    program_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict]:
    """OPEN program + one application walked to COMMITTED (billing statement
    created in ISSUED as a commit side effect, PRD §3.4).

    Returns (program, student, application).
    """
    program, student, application = create_approved_application(
        student_overrides, program_overrides,
    )
    application = commit_application(application, student)
    return program, student, application


def enroll_insurance(application: dict, student: dict, **overrides) -> dict:
    """Enroll a COMMITTED application in insurance (born ACTIVE, PRD §3.5)."""
    payload = create_insurance_enrollment_payload(application["id"], **overrides)
    return get_success_data(
        api_client.create_insurance_enrollment(
            payload, make_student_headers(student["id"]),
        )
    )


def create_abroad_application(
    student_overrides: Optional[dict] = None,
    program_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict]:
    """One application walked to ABROAD (committed, insured, departed).

    Returns (program, student, application).
    """
    program, student, application = create_committed_application(
        student_overrides, program_overrides,
    )
    enroll_insurance(application, student)
    application = get_success_data(
        api_client.application_lifecycle(
            application["id"], create_lifecycle_payload("DEPART"), COORD_A_HEADERS,
        )
    )
    return program, student, application


def create_returned_home_application(
    student_overrides: Optional[dict] = None,
    program_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict]:
    """One application walked to RETURNED_HOME.

    Returns (program, student, application).
    """
    program, student, application = create_abroad_application(
        student_overrides, program_overrides,
    )
    application = get_success_data(
        api_client.application_lifecycle(
            application["id"], create_lifecycle_payload("RECORD_RETURN"),
            COORD_A_HEADERS,
        )
    )
    return program, student, application


# ---------------------------------------------------------------------------
# Tier 3b: course pre-approval helpers (PRD §3.3)
# ---------------------------------------------------------------------------

def get_application_version(application_id: str) -> int:
    """Re-read the application and return its current version (OCC guard)."""
    return get_success_data(api_client.get_application(application_id, COORD_A_HEADERS))["version"]


def create_pending_preapproval(
    application: dict,
    student: dict,
    course_code: str = "HIST310",
    host_credits: float = 3,
    course_title: str = "Modern French History",
) -> dict:
    """Create a PENDING course pre-approval, threading the application's
    current version into expected_application_version (OCC, PRD §2.9)."""
    version = get_application_version(application["id"])
    payload = create_course_preapproval_payload(
        version,
        course_code=course_code,
        course_title=course_title,
        host_credits=host_credits,
    )
    return get_success_data(
        api_client.create_course_preapproval(
            application["id"], payload, make_student_headers(student["id"]),
        )
    )


def review_preapproval(cpa_id: str, decision: str, **payload_overrides) -> dict:
    """Faculty review of a PENDING pre-approval (PRD §3.3)."""
    return get_success_data(
        api_client.review_course_preapproval(
            cpa_id, create_review_payload(decision, **payload_overrides),
            FACULTY_HEADERS,
        )
    )


def create_approved_preapproval(
    application: dict,
    student: dict,
    course_code: str = "HIST310",
    host_credits: float = 3,
) -> dict:
    """Create + approve a course pre-approval (status APPROVED)."""
    cpa = create_pending_preapproval(application, student, course_code, host_credits)
    return review_preapproval(cpa["id"], "APPROVED")


# ---------------------------------------------------------------------------
# Tier 3c: billing helpers (PRD §3.4)
# ---------------------------------------------------------------------------

def get_statement_for_application(application_id: str) -> dict:
    """Read the single billing statement created at commit time."""
    data, _meta = _list_billing_statements({"application_id": application_id})
    assert len(data) == 1, (
        f"Setup failed: expected exactly 1 statement for application {application_id}, "
        f"got {len(data)}"
    )
    return data[0]


def _list_billing_statements(params: dict):
    from prd_bench_local_runner.testing import validate_paginated

    resp = api_client.list_billing_statements(BURSAR_HEADERS, params=params)
    return validate_paginated(resp)


def record_payment(statement_id: str, amount_cents: int) -> dict:
    """BursarOffice records a payment against a statement (PRD §3.4)."""
    return get_success_data(
        api_client.record_payment(
            statement_id, create_payment_payload(amount_cents), BURSAR_HEADERS,
        )
    )


def setup_committed_with_statement(
    aid_award_cents: int = 0,
    program_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict, dict]:
    """Application COMMITTED + its ISSUED billing statement.

    Returns (program, student, application, statement).
    """
    program, student, application = create_committed_application(
        student_overrides={"aid_award_cents": aid_award_cents},
        program_overrides=program_overrides,
    )
    statement = get_statement_for_application(application["id"])
    return program, student, application, statement


# ---------------------------------------------------------------------------
# Tier 3d: incidents and credit postings (PRD §3.7, §3.8)
# ---------------------------------------------------------------------------

def create_reported_incident(
    application: dict,
    reporter_student: Optional[dict] = None,
    **overrides,
) -> dict:
    """Report an incident (born REPORTED) for an ABROAD application. Reporter
    defaults to a ProgramCoordinator when no student is supplied."""
    payload = create_incident_payload(application["id"], **overrides)
    headers = (
        make_student_headers(reporter_student["id"])
        if reporter_student is not None
        else COORD_A_HEADERS
    )
    return get_success_data(api_client.create_incident(payload, headers))


def create_transcript_posting(application_id: str, lines: list) -> dict:
    """FacultyApprover uploads a PENDING credit posting (PRD §3.8)."""
    return get_success_data(
        api_client.create_credit_posting(
            application_id, create_credit_posting_payload(lines), FACULTY_HEADERS,
        )
    )


def setup_returned_home_with_approved_courses(
    courses: Optional[list] = None,
    program_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict, list]:
    """Application walked to RETURNED_HOME with N APPROVED pre-approvals.

    `courses` is a list of (course_code, host_credits) tuples.
    Returns (program, student, application, [preapproval, ...]).
    """
    if courses is None:
        courses = [("HIST310", 3), ("ART220", 5)]
    program, student, application = setup_open_program_with_application(
        student_overrides={"aid_award_cents": 0},
        program_overrides=program_overrides,
    )
    cpa_ids = []
    for code, credits in courses:
        cpa = create_approved_preapproval(application, student, code, credits)
        cpa_ids.append(cpa)
    application = clear_application(application, "CLEARED")
    application = approve_application(application["id"])
    application = commit_application(application, student)
    enroll_insurance(application, student)
    application = get_success_data(
        api_client.application_lifecycle(
            application["id"], create_lifecycle_payload("DEPART"), COORD_A_HEADERS,
        )
    )
    application = get_success_data(
        api_client.application_lifecycle(
            application["id"], create_lifecycle_payload("RECORD_RETURN"),
            COORD_A_HEADERS,
        )
    )
    return program, student, application, cpa_ids


# ---------------------------------------------------------------------------
# Tier 4: travel advisories (PRD §3.6)
# ---------------------------------------------------------------------------

def create_travel_advisory(**overrides) -> dict:
    """SafetyOfficer creates an advisory (born ACTIVE)."""
    return get_success_data(
        api_client.create_travel_advisory(
            create_travel_advisory_payload(**overrides), SAFETY_HEADERS,
        )
    )


def create_containing_do_not_travel_advisory(program: dict) -> dict:
    """DO_NOT_TRAVEL advisory whose window fully contains the program dates —
    suspends an OPEN program (PRD §3.6)."""
    return create_travel_advisory(
        country_code=program["country_code"],
        level="DO_NOT_TRAVEL",
        effective_from="2027-01-01T00:00:00Z",
        effective_to="2027-06-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str) -> dict:
    """Drive the server logical clock to the supplied instant."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, COORD_A_HEADERS)
    )
