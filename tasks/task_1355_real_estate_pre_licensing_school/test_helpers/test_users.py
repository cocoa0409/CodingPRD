"""Pre-built role headers for every role in the PRD (§2.1).

The four staff roles are opaque: X-User-ID is never compared to an entity id, so
shared constants are canonical for them. Instructor, Proctor, and Student are
entity-backed: X-User-ID must reference an existing Instructor/Student entity,
and ownership checks compare it to resource fields — fixtures MUST use the
per-instance builders with the actual entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque staff roles — canonical shared constants.
    "state_commission_headers": build_user_headers("commission-1", "StateCommission"),
    "registrar_headers": build_user_headers("registrar-1", "Registrar"),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    # SchoolDirector is opaque, but director operations are scoped to schools whose
    # director_user_id equals X-User-ID; the shared constant owns schools created
    # with the default shared header. Use make_school_director_headers to bind a
    # second director identity.
    "school_director_headers": build_user_headers("director-1", "SchoolDirector"),
    # Entity-backed roles — shared constants are placeholders for tests that do
    # NOT exercise ownership (e.g. 404 probes). Ownership-gated calls MUST use
    # the builders below with the actual entity id.
    "instructor_headers": build_user_headers("instructor-placeholder", "Instructor"),
    "proctor_headers": build_user_headers("proctor-placeholder", "Proctor"),
    "student_headers": build_user_headers("student-placeholder", "Student"),
}


def make_school_director_headers(user_id: str) -> dict:
    """SchoolDirector identity; pass the X-User-ID that owns the target school."""
    return build_user_headers(user_id, "SchoolDirector")


def make_instructor_headers(instructor_id: str) -> dict:
    """Instructor is entity-backed: pass the actual Instructor.id whenever the
    call is ownership-gated (attendance record/void, exam scoring)."""
    return build_user_headers(instructor_id, "Instructor")


def make_proctor_headers(instructor_id: str) -> dict:
    """Proctor is entity-backed: pass the Instructor.id assigned as the attempt's
    proctor whenever the call is ownership-gated (verify, invalidate)."""
    return build_user_headers(instructor_id, "Proctor")


def make_student_headers(student_id: str) -> dict:
    """Student is entity-backed: pass the actual Student.id whenever the call is
    ownership-gated (self-enroll, own withdraw/pay, own reads)."""
    return build_user_headers(student_id, "Student")
