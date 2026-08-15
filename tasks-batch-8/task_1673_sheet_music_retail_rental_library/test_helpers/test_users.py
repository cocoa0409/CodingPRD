"""Pre-built role headers for every role in the PRD (§2.1).

LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, and RightsAdvisor are
opaque identities: X-User-ID is not tied to any persisted entity (it is still
recorded, e.g. as a condition report's assessor or an invoice's issuer, which
matters for the segregation-of-duties rule). Customer is entity-backed by
CustomerAccount: X-User-ID must be the acting account's id, so ownership-gated
calls MUST use make_customer_headers(account["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "library_admin_headers": build_user_headers("test-admin-1", "LibraryAdmin"),
    "library_clerk_headers": build_user_headers("test-clerk-1", "LibraryClerk"),
    "returns_clerk_headers": build_user_headers("test-returns-1", "ReturnsClerk"),
    "billing_manager_headers": build_user_headers("test-billing-1", "BillingManager"),
    "rights_advisor_headers": build_user_headers("test-advisor-1", "RightsAdvisor"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_library_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "LibraryAdmin")


def make_library_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    return build_user_headers(user_id, "LibraryClerk")


def make_returns_clerk_headers(user_id: str = "test-returns-1") -> dict:
    """ReturnsClerk is opaque, but its X-User-ID is recorded as the condition
    report's assessor_user_id — pin it when a test exercises segregation of duties."""
    return build_user_headers(user_id, "ReturnsClerk")


def make_billing_manager_headers(user_id: str = "test-billing-1") -> dict:
    """BillingManager is opaque, but its X-User-ID is recorded as the invoice's
    issuer_user_id — pin it when a test exercises segregation of duties."""
    return build_user_headers(user_id, "BillingManager")


def make_rights_advisor_headers(user_id: str = "test-advisor-1") -> dict:
    return build_user_headers(user_id, "RightsAdvisor")


def make_customer_headers(account_id: str) -> dict:
    """For Customer (entity_backed:CustomerAccount). Pass the acting
    CustomerAccount.id whenever the call is ownership-gated (confirm-receipt,
    dispute, rights-case withdraw, own-account reads)."""
    return build_user_headers(account_id, "Customer")
