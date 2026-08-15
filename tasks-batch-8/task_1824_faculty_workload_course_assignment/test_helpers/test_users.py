"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "chair_headers": build_user_headers("chair-1", "DepartmentChair"),
    "chair2_headers": build_user_headers("chair-2", "DepartmentChair"),
    "dean_headers": build_user_headers("dean-1", "DeanOffice"),
    "registrar_headers": build_user_headers("registrar-1", "Registrar"),
    "admin_headers": build_user_headers("admin-1", "SystemAdmin"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "faculty_headers": build_user_headers("test-faculty-1", "FacultyMember"),
}


def make_chair_headers(user_id: str = "chair-1") -> dict:
    """DepartmentChair (opaque identity); pick distinct user ids for segregation-of-duties tests."""
    return build_user_headers(user_id, "DepartmentChair")


def make_faculty_headers(user_id: str) -> dict:
    """For FacultyMember (entity_backed:FacultyMember). Pass the actual FacultyMember.id
    as user_id whenever the call is ownership-gated (confirm/decline an assignment)."""
    return build_user_headers(user_id, "FacultyMember")


def make_dean_headers(user_id: str = "dean-1") -> dict:
    """DeanOffice (opaque identity). For DEAN_APPROVED the user id must differ from the
    endorsing chair's X-User-ID (segregation of duties)."""
    return build_user_headers(user_id, "DeanOffice")


def make_registrar_headers(user_id: str = "registrar-1") -> dict:
    """Registrar (opaque identity): enrollment syncs only."""
    return build_user_headers(user_id, "Registrar")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """SystemAdmin (opaque identity): logical clock control."""
    return build_user_headers(user_id, "SystemAdmin")
