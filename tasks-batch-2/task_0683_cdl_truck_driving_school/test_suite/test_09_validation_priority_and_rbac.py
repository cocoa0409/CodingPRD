"""Cross-category validation ordering and role-based access control.

Translates queue A (priority_pair_validation_conflict/examiner_not_found_beats_enrollment_not_test_ready)
and queue B (rbac) instances.

NOTE: the queue A instance
priority_pair_validation_conflict/prereq_not_met_beats_truck_class_mismatch is SKIPPED
for PRD-coverage reasons. ERR_PREREQ_NOT_MET and ERR_TRUCK_CLASS_MISMATCH are both
domain-specific §3 business rules; PRD §2.8 orders only the six enumerated categories
(auth, authz, existence, well-formedness, state, OCC) ahead of "the domain-specific
business-safety, referential, and temporal rules described in §3" collectively, and does
not pin any ordering BETWEEN two §3 rules. Two faithful PRD-only implementers could
report either error, so the asserted precedence is not uniquely derivable (error-precedence
silence pattern). No test is emitted; the gap is left as a gap.
"""
from test_helpers import (
    api_client,
    validate_error,
    ApiErrorId, TEST_USERS,
    create_program, create_enrollment, submit_prereq,
    create_program_payload,
    make_instructor_headers,
)

ADMIN = TEST_USERS["school_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
NON_EXISTENT_EXAMINER = "00000000-0000-4000-8000-000000000000"


# ---- Queue A: priority_pair_validation_conflict / examiner_not_found_beats_enrollment_not_test_ready ----

def test_examiner_not_found_beats_enrollment_not_test_ready():
    """PRD §2.8: "Existence is third: any missing path or foreign-key resource yields
    ERR_NOT_FOUND." PRD §2.8: "Only after all of these pass does the system evaluate the
    domain-specific business-safety, referential, and temporal rules described in §3".

    Design: Difficulty/priority_pair_validation_conflict/examiner_not_found_beats_enrollment_not_test_ready
    """
    program = create_program()
    enr = create_enrollment(program["id"])
    # Submit a single document so the enrollment is PREREQ_PENDING (not TEST_READY); the
    # examiner_id below does not exist.
    submit_prereq(enr["id"], "DOT_MEDICAL")
    resp = api_client.create_skills_test(
        enr["id"], {"examiner_id": NON_EXISTENT_EXAMINER}, REGISTRAR)
    # Existence (priority 3) outranks the TEST_READY business rule (in §3): ERR_NOT_FOUND.
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_examiner_not_found_on_applied_enrollment_still_not_found():
    """PRD §2.7: "The same left-to-right rule applies to foreign keys carried in a request
    body: any referenced resource that does not exist yields ERR_NOT_FOUND." PRD §2.8:
    "Existence is third: any missing path or foreign-key resource yields ERR_NOT_FOUND."

    Design: Difficulty/priority_pair_validation_conflict/examiner_not_found_beats_enrollment_not_test_ready
    """
    program = create_program()
    enr = create_enrollment(program["id"])  # APPLIED, also not TEST_READY
    resp = api_client.create_skills_test(
        enr["id"], {"examiner_id": NON_EXISTENT_EXAMINER}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---- Queue B: rbac ----

def test_registrar_cannot_create_program():
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation per the access rules described throughout this
    document, the request is rejected with ERR_FORBIDDEN." PRD §4: "POST /programs |
    Create a training program | SchoolAdmin".

    Design: Corner/rbac/registrar_cannot_create_program
    """
    resp = api_client.create_program(create_program_payload(), REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_instructor_cannot_grade_skills_test():
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation per the access rules described throughout this
    document, the request is rejected with ERR_FORBIDDEN." PRD §4: "POST
    /skills-tests/{id}/grade | Grade a skills test | ThirdPartyExaminer".

    Design: Corner/rbac/instructor_cannot_grade_skills_test
    """
    from test_helpers import setup_scheduled_skills_test
    ctx = setup_scheduled_skills_test(
        skills_pass_threshold=80, classroom_required_hours=0, range_required_hours=0,
        road_required_hours=1)
    # An Instructor (not a ThirdPartyExaminer) attempts to grade.
    resp = api_client.grade_skills_test(
        ctx["test"]["id"],
        {"pre_trip_score": 90, "basic_control_score": 90, "road_score": 90},
        make_instructor_headers(ctx["instructor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_headers_returns_unauthenticated():
    """PRD §2.1: "Every request to the API must be authenticated through two mandatory
    HTTP headers ... If either header is missing or malformed, the request is rejected
    with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api_client.get_program(NON_EXISTENT_EXAMINER, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
