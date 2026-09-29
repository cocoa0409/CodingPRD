"""Pre-built role headers for every role in the PRD (§2.1).

Five roles are operator roles whose ``X-User-ID`` is opaque and never compared
to an entity id, so a shared constant is the canonical form for them.

Two roles are entity-backed: ``Naturalist`` carries the acting ``Educator.id``
and ``TeacherContact`` carries the acting ``SchoolPartner.id``. For those, any
ownership-gated call MUST use the per-instance builder with the real entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Operator identifiers used consistently across fixtures. Two distinct
# CurriculumSpecialist identities exist because PRD §2.11 forbids the enroller
# from recording the assessment.
EDUCATION_DIRECTOR_ID = "ed-01"
EDUCATION_DIRECTOR_ALT_ID = "ed-02"
CURRICULUM_SPECIALIST_ID = "cs-01"
CURRICULUM_SPECIALIST_ASSESSOR_ID = "cs-02"
BOOKING_COORDINATOR_ID = "bc-01"
STEWARDSHIP_MANAGER_ID = "sm-01"
GRANTS_OFFICER_ID = "go-01"

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "education_director_headers": build_user_headers(
        EDUCATION_DIRECTOR_ID, "EducationDirector"
    ),
    "education_director_alt_headers": build_user_headers(
        EDUCATION_DIRECTOR_ALT_ID, "EducationDirector"
    ),
    "curriculum_specialist_headers": build_user_headers(
        CURRICULUM_SPECIALIST_ID, "CurriculumSpecialist"
    ),
    "curriculum_specialist_assessor_headers": build_user_headers(
        CURRICULUM_SPECIALIST_ASSESSOR_ID, "CurriculumSpecialist"
    ),
    "booking_coordinator_headers": build_user_headers(
        BOOKING_COORDINATOR_ID, "BookingCoordinator"
    ),
    "stewardship_manager_headers": build_user_headers(
        STEWARDSHIP_MANAGER_ID, "StewardshipManager"
    ),
    "grants_officer_headers": build_user_headers(GRANTS_OFFICER_ID, "GrantsOfficer"),
    # Entity-backed roles — these shared constants are fallbacks only, for tests
    # that do not exercise ownership (bad payloads, unknown ids, role gating).
    "naturalist_headers": build_user_headers("nat-unbound-01", "Naturalist"),
    "teacher_contact_headers": build_user_headers("tc-unbound-01", "TeacherContact"),
}

ROLE_HEADER_KEYS = {
    "EducationDirector": "education_director_headers",
    "CurriculumSpecialist": "curriculum_specialist_headers",
    "BookingCoordinator": "booking_coordinator_headers",
    "StewardshipManager": "stewardship_manager_headers",
    "GrantsOfficer": "grants_officer_headers",
    "Naturalist": "naturalist_headers",
    "TeacherContact": "teacher_contact_headers",
}


# --- Per-instance builders ----------------------------------------------------------

def make_naturalist_headers(educator_id: str) -> dict:
    """For the ``Naturalist`` role, whose ``X-User-ID`` is the acting Educator's id.

    Pass the real ``Educator.id`` whenever the call is ownership-gated.
    """
    return build_user_headers(educator_id, "Naturalist")


def make_teacher_contact_headers(school_id: str) -> dict:
    """For the ``TeacherContact`` role, whose ``X-User-ID`` is the acting
    SchoolPartner's id. Pass the real ``SchoolPartner.id`` for scope-gated calls.
    """
    return build_user_headers(school_id, "TeacherContact")


def make_education_director_headers(user_id: str) -> dict:
    """Opaque operator identity; useful when a test must pin the reviewing
    ``X-User-ID`` to a specific value (segregation-of-duties scenarios)."""
    return build_user_headers(user_id, "EducationDirector")


def make_curriculum_specialist_headers(user_id: str) -> dict:
    """Opaque operator identity; useful for pinning author vs reviewer identity."""
    return build_user_headers(user_id, "CurriculumSpecialist")


def make_booking_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BookingCoordinator")


def make_stewardship_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StewardshipManager")


def make_grants_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GrantsOfficer")


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder for parametrized role tests."""
    return build_user_headers(user_id, role)
