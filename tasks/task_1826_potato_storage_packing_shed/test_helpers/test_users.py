"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ShedAdmin"),
    "intake_headers": build_user_headers("test-intake-1", "IntakeClerk"),
    "storage_headers": build_user_headers("test-storage-1", "StorageManager"),
    "qa_headers": build_user_headers("test-qa-1", "QualityAssuranceManager"),
    "sales_headers": build_user_headers("test-sales-1", "SalesManager"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "PackLineSupervisor"),
    "clerk_headers": build_user_headers("clerk_one", "SettlementClerk"),
    # Grower is entity_backed: shared constant is a fallback for non-ownership tests only.
    "grower_headers": build_user_headers("test-grower-1", "Grower"),
}


# Per-instance builders — required for roles whose identity is entity-backed.


def make_grower_headers(user_id: str) -> dict:
    """For the Grower role: X-User-ID must equal the acting Grower resource's id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Grower")


def make_clerk_headers(user_id: str) -> dict:
    """For SettlementClerk calls whose recorded clerk id matters (settlement finalize /
    segregation-of-duties re-finalize, PRD §3.9)."""
    return build_user_headers(user_id, "SettlementClerk")


def make_role_headers(user_id: str, role: str) -> dict:
    """Generic builder for any role spelled exactly as in PRD §2.1."""
    return build_user_headers(user_id, role)
