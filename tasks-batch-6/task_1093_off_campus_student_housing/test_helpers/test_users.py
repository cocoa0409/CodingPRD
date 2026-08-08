"""Pre-built role headers for every role in the PRD (§2.1).

Three roles carry opaque identifiers (PlatformAdmin, PropertyManager,
UniversityPartner); Student's X-User-ID is the acting Student's id, so
ownership-gated Student calls MUST use make_student_headers(student_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque-identity roles use fixed operator ids that are recorded on entities
# but never compared to any entity id, plus second operators for the
# segregation-of-duties and cross-manager scenarios.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "admin2_headers": build_user_headers("admin-2", "PlatformAdmin"),
    "manager_headers": build_user_headers("mgr-1", "PropertyManager"),
    "manager2_headers": build_user_headers("mgr-2", "PropertyManager"),
    # partner admin for the canonical "SU" university fixture
    "partner_headers": build_user_headers("uni-admin-su", "UniversityPartner"),
    # A Student header not tied to any real student (for non-ownership tests only).
    "student_headers": build_user_headers("student-nobody", "Student"),
}


def make_admin_headers(user_id: str) -> dict:
    """PlatformAdmin (opaque). Pass any operator id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_manager_headers(user_id: str) -> dict:
    """PropertyManager (opaque). Pass the operator id recorded as
    Property.manager_user_id when the call is ownership-gated."""
    return build_user_headers(user_id, "PropertyManager")


def make_partner_headers(user_id: str) -> dict:
    """UniversityPartner (opaque). Pass the University.partner_admin_user_id
    when the call is ownership-gated."""
    return build_user_headers(user_id, "UniversityPartner")


def make_student_headers(student_id: str) -> dict:
    """Student (entity_backed:Student). Pass the actual Student.id whenever the
    call is ownership-gated (lease, membership, group-lead ownership checks)."""
    return build_user_headers(student_id, "Student")
