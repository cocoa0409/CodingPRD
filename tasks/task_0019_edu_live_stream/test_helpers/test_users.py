"""Pre-built role headers for every role in the Edu Live Stream platform.

Two forms are provided per role:

- **Shared-constant entries in TEST_USERS** — safe for tests whose success does
  NOT depend on the caller owning the subject resource. Opaque roles
  (AcademicAdmin) use the shared constant as their canonical form per PRD §2.1
  ("X-User-ID is an opaque operator identifier not tied to any persisted
  entity"). The shared entity-backed entries are appropriate only for tests
  that do not exercise ownership (auth-failure probes, plain 404 probes,
  forbidden-role probes).

- **Per-instance builders make_<role>_headers(user_id)** — mandatory for every
  role whose identity is entity-backed (Instructor, TeachingAssistant,
  Student). PRD §2.1 says the X-User-ID for these roles is the id of the
  corresponding entity, so ownership-gated calls require X-User-ID to equal
  the actual entity's id. Falling back to a shared constant for an
  ownership-gated call would make every ownership check reject every request.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ──────────────────────────────────────────────────────────
# Shared constants — safe for AcademicAdmin (opaque per PRD §2.1) and for
# tests that do NOT exercise ownership.
# ──────────────────────────────────────────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque role: AcademicAdmin's X-User-ID is never compared to an entity id.
    "admin_headers": build_user_headers("test-admin-1", "AcademicAdmin"),

    # Entity-backed role fallbacks — only for tests that do NOT exercise
    # ownership. Ownership-gated calls must use the make_*_headers builder
    # below with the actual entity's id.
    "instructor_headers": build_user_headers("test-instructor-fallback", "Instructor"),
    "ta_headers": build_user_headers("test-ta-fallback", "TeachingAssistant"),
    "student_headers": build_user_headers("test-student-fallback", "Student"),
}


# ──────────────────────────────────────────────────────────
# Per-instance builders — REQUIRED for every entity-backed role whenever the
# call is ownership-gated. Pass the actual entity's id as user_id so the
# server's ownership check resolves X-User-ID to the owning row.
# ──────────────────────────────────────────────────────────

def make_instructor_headers(instructor_id: str) -> Dict[str, str]:
    """Build Instructor headers where X-User-ID == Instructor.id.

    PRD §2.1: 'When X-User-Role is Instructor, X-User-ID is the id of the
    acting Instructor entity. Ownership checks ... compare the resource's
    foreign-key field to X-User-ID.'
    """
    return build_user_headers(instructor_id, "Instructor")


def make_ta_headers(instructor_id: str) -> Dict[str, str]:
    """Build TeachingAssistant headers where X-User-ID == Instructor.id.

    PRD §2.1: 'When X-User-Role is TeachingAssistant, X-User-ID is also the
    id of an Instructor entity — teaching assistants are physically stored
    as Instructor rows.'
    """
    return build_user_headers(instructor_id, "TeachingAssistant")


def make_student_headers(student_id: str) -> Dict[str, str]:
    """Build Student headers where X-User-ID == Student.id.

    PRD §2.1: 'When X-User-Role is Student, X-User-ID is the id of the
    acting Student entity.'
    """
    return build_user_headers(student_id, "Student")


def make_admin_headers(admin_id: str = "test-admin-1") -> Dict[str, str]:
    """Build AcademicAdmin headers. Per PRD §2.1 the id is opaque."""
    return build_user_headers(admin_id, "AcademicAdmin")
