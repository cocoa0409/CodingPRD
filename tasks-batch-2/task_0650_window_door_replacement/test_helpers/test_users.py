"""Pre-built role headers for every role in the PRD.

The Homeowner role is entity_backed: its X-User-ID must equal the acting
Homeowner record's id whenever an ownership-gated call is made (quote
accept/reject, service-ticket reopen). For those calls use
make_homeowner_headers(homeowner["id"]). The shared TEST_USERS constant is a
fallback for tests that do NOT exercise ownership.

The other four roles are opaque operator identifiers; their shared constants
are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    # opaque roles: shared constant is the canonical form.
    "sales_consultant_headers": build_user_headers("test-sales-1", "SalesConsultant"),
    "operations_coordinator_headers": build_user_headers("test-ops-1", "OperationsCoordinator"),
    "service_tech_headers": build_user_headers("test-svc-1", "ServiceTech"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_homeowner_headers(user_id: str) -> dict:
    """For Homeowner (entity_backed:Homeowner). Pass the actual Homeowner.id as
    user_id whenever the call is ownership-gated (accept/reject quote, reopen
    ticket, open ticket)."""
    return build_user_headers(user_id, "Homeowner")


def make_sales_consultant_headers(user_id: str = "test-sales-1") -> dict:
    return build_user_headers(user_id, "SalesConsultant")


def make_operations_coordinator_headers(user_id: str = "test-ops-1") -> dict:
    return build_user_headers(user_id, "OperationsCoordinator")


def make_service_tech_headers(user_id: str = "test-svc-1") -> dict:
    return build_user_headers(user_id, "ServiceTech")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
