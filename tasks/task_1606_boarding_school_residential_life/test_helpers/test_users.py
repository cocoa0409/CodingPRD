"""Pre-built role headers for every role in the PRD (§2.1).

Identity rules (PRD §2.1): SchoolAdmin's X-User-ID is opaque; every other role
is entity-backed — Student X-User-ID is the Student.id, Parent the Parent.id,
Guardian the Guardian.id, and DormParent/Nurse/Dean/FrontDesk the StaffMember.id
whose staff_role matches. Ownership-gated calls MUST use the per-instance
builders below with the actual entity id; the shared constants exist only for
tests whose outcome does not depend on the caller owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "SchoolAdmin"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership
    # tests only (e.g., role-presence checks, 400/404 paths).
    "student_headers": build_user_headers("test-student-nonowner", "Student"),
    "parent_headers": build_user_headers("test-parent-nonowner", "Parent"),
    "guardian_headers": build_user_headers("test-guardian-nonowner", "Guardian"),
    "dorm_parent_headers": build_user_headers("test-dp-nonowner", "DormParent"),
    "nurse_headers": build_user_headers("test-nurse-nonowner", "Nurse"),
    "dean_headers": build_user_headers("test-dean-nonowner", "Dean"),
    "front_desk_headers": build_user_headers("test-fd-nonowner", "FrontDesk"),
}


def make_student_headers(user_id: str) -> dict:
    """Student is entity-backed: pass the actual Student.id for ownership-gated calls."""
    return build_user_headers(user_id, "Student")


def make_parent_headers(user_id: str) -> dict:
    """Parent is entity-backed: pass the actual Parent.id for family decisions."""
    return build_user_headers(user_id, "Parent")


def make_guardian_headers(user_id: str) -> dict:
    """Guardian is entity-backed: pass the actual Guardian.id for family decisions."""
    return build_user_headers(user_id, "Guardian")


def make_dorm_parent_headers(user_id: str) -> dict:
    """DormParent maps to a StaffMember with staff_role DORM_PARENT; pass its id."""
    return build_user_headers(user_id, "DormParent")


def make_nurse_headers(user_id: str) -> dict:
    """Nurse maps to a StaffMember with staff_role NURSE; pass its id."""
    return build_user_headers(user_id, "Nurse")


def make_dean_headers(user_id: str) -> dict:
    """Dean maps to a StaffMember with staff_role DEAN; pass its id."""
    return build_user_headers(user_id, "Dean")


def make_front_desk_headers(user_id: str) -> dict:
    """FrontDesk maps to a StaffMember with staff_role FRONT_DESK; pass its id."""
    return build_user_headers(user_id, "FrontDesk")
