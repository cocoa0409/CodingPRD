"""Pre-built role headers for every role in the PRD (§2.1).

GangForeman is entity-backed: when X-User-Role is GangForeman, X-User-ID is
the id of the acting Worker. Fixtures MUST use make_foreman_headers(worker_id)
with the real worker id for foreman calls. The shared "foreman_headers"
constant is only a fallback for tests where the foreman identity is irrelevant
to the rule under test.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "StevedoreAdmin"),
    "superintendent_headers": build_user_headers("test-supt-1", "StevedoreSuperintendent"),
    "dispatcher_headers": build_user_headers("test-disp-1", "LaborHallDispatcher"),
    "adjuster_headers": build_user_headers("adj-1", "ClaimsAdjuster"),
    "payroll_headers": build_user_headers("pay-1", "PayrollClerk"),
    "billing_headers": build_user_headers("test-bill-1", "BillingClerk"),
    # Entity-backed role: fallback ONLY for calls whose outcome cannot depend
    # on the foreman's identity (no resource creation that records it).
    "foreman_headers": build_user_headers("test-foreman-1", "GangForeman"),
}


def make_foreman_headers(worker_id: str) -> dict:
    """GangForeman headers bound to a real Worker's id. Required whenever the
    call records the foreman (move records, damage claims, timesheet submit)
    or when segregation-of-duties compares identities."""
    return build_user_headers(worker_id, "GangForeman")


def make_adjuster_headers(user_id: str) -> dict:
    """ClaimsAdjuster headers with a specific X-User-ID (segregation tests)."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_payroll_headers(user_id: str) -> dict:
    """PayrollClerk headers with a specific X-User-ID (segregation tests)."""
    return build_user_headers(user_id, "PayrollClerk")
