"""Pre-built role headers for every role in the PRD (§2.1).

All four roles carry an opaque identity: the server never compares X-User-ID to
any entity id and never infers ownership from the caller. Authorization is purely
role-based, so a single shared constant per role is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "account_manager_headers": build_user_headers("test-manager-1", "AccountManager"),
    "route_driver_headers": build_user_headers("test-driver-1", "RouteDriver"),
    "cleanroom_tech_headers": build_user_headers("test-tech-1", "CleanroomTech"),
}
