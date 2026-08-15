"""Pre-built role headers for every role named in PRD 2.1.

`Teacher` and `SchoolCoordinator` carry the acting `StaffMember`'s id in
`X-User-ID`; `Substitute` carries the acting `Substitute` row's id. Those
three roles therefore need per-instance builders — the shared constants below
are only safe for calls whose success does not depend on the caller owning
the subject resource. `DistrictAdmin` and `PayrollClerk` carry opaque
identities that the server never compares to any entity's `id`.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque identities — the shared constant is the canonical form.
    "district_admin_headers": build_user_headers("admin-op-1", "DistrictAdmin"),
    "payroll_clerk_headers": build_user_headers("payroll-op-1", "PayrollClerk"),
    # Entity-backed identities — fallbacks for non-ownership tests only.
    "school_coordinator_headers": build_user_headers("test-coordinator-1", "SchoolCoordinator"),
    "teacher_headers": build_user_headers("test-teacher-1", "Teacher"),
    "substitute_headers": build_user_headers("test-substitute-1", "Substitute"),
}

# No auth headers at all — for the priority-1 auth-context check (PRD 2.8).
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}


def make_district_admin_headers(user_id: str = "admin-op-1") -> Dict[str, str]:
    """For DistrictAdmin (opaque identity)."""
    return build_user_headers(user_id, "DistrictAdmin")


def make_payroll_clerk_headers(user_id: str = "payroll-op-1") -> Dict[str, str]:
    """For PayrollClerk (opaque identity)."""
    return build_user_headers(user_id, "PayrollClerk")


def make_coordinator_headers(staff_member_id: str) -> Dict[str, str]:
    """For SchoolCoordinator. Pass the acting StaffMember's id (whose
    `is_coordinator` flag must be true) whenever the call is scoped to a
    school — the server compares the record's `school_id` to the target."""
    return build_user_headers(staff_member_id, "SchoolCoordinator")


def make_teacher_headers(staff_member_id: str) -> Dict[str, str]:
    """For Teacher. Pass the acting StaffMember's id whenever the call is
    ownership-gated (reporting or cancelling that teacher's own absence)."""
    return build_user_headers(staff_member_id, "Teacher")


def make_substitute_headers(substitute_id: str) -> Dict[str, str]:
    """For Substitute. Pass the acting Substitute's id whenever the call is
    ownership-gated (respond / cancel / timesheet submission / resubmit)."""
    return build_user_headers(substitute_id, "Substitute")
