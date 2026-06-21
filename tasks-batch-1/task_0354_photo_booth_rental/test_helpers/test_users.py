"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin, OperationsManager, FinanceClerk, and Anonymous carry an OPAQUE
identity: X-User-ID is an operator identifier not tied to any persisted entity,
so a shared constant is the canonical form for them.

Customer is ENTITY-BACKED (X-User-ID is the acting Customer.id). Any ownership-gated
Customer call MUST use make_customer_headers(customer_id) with the real Customer.id;
the shared constant is only a fallback for non-ownership tests.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "operations_manager_headers": build_user_headers("test-operations-manager-1", "OperationsManager"),
    "finance_clerk_headers": build_user_headers("test-finance-clerk-1", "FinanceClerk"),
    # Fallback only — non-ownership Customer tests (e.g. 404/422 on bad payload).
    "customer_headers": build_user_headers("test-customer-fallback-1", "Customer"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    """PlatformAdmin is opaque; X-User-ID is an operator identifier (PRD §2.1)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_operations_manager_headers(user_id: str = "test-operations-manager-1") -> dict:
    """OperationsManager is opaque; X-User-ID is an operator identifier (PRD §2.1)."""
    return build_user_headers(user_id, "OperationsManager")


def make_finance_clerk_headers(user_id: str = "test-finance-clerk-1") -> dict:
    """FinanceClerk is opaque; X-User-ID is an operator identifier (PRD §2.1)."""
    return build_user_headers(user_id, "FinanceClerk")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity-backed). Pass the actual Customer.id as user_id whenever
    the call is ownership-gated — create booking, add add-on, cancel, read own
    booking (PRD §2.1)."""
    return build_user_headers(user_id, "Customer")
