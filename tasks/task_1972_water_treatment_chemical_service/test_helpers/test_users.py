"""Pre-built role headers for every role in the PRD.

PlatformAdmin, AccountManager, and WaterChemist are opaque roles: X-User-ID is
not tied to any persisted entity, so shared constants are canonical.
CustomerContact is entity-backed: X-User-ID must be the id of the acting
CustomerAccount, so ownership-gated calls MUST use make_customer_contact_headers
with the real account id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    "chemist_headers": build_user_headers("test-water-chemist-1", "WaterChemist"),
    # CustomerContact fallback for non-ownership tests only; ownership-gated
    # calls must use make_customer_contact_headers(account_id).
    "contact_headers": build_user_headers("test-customer-contact-1", "CustomerContact"),
}


def make_customer_contact_headers(account_id: str) -> dict:
    """CustomerContact headers for the given CustomerAccount id (entity-backed)."""
    return build_user_headers(account_id, "CustomerContact")


def make_chemist_headers(user_id: str) -> dict:
    """WaterChemist headers with a specific opaque user id (segregation of duties)."""
    return build_user_headers(user_id, "WaterChemist")


def make_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AccountManager")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
