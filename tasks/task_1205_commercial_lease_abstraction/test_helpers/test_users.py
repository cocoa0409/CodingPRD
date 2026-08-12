"""Pre-built role headers for every role in the PRD (§2.1, §4).

All six roles use opaque operator identifiers: `X-User-ID` is never compared
against any entity's `id` (PRD §2.1), so the shared constants below are the
canonical form. Per-instance builders exist for tests that must control the
operator id explicitly (segregation-of-duties scenarios, PRD §2.9).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for every role (all identities are opaque).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "portfolio_manager_headers": build_user_headers("test-portfolio-manager-1", "PortfolioManager"),
    "property_manager_headers": build_user_headers("test-property-manager-1", "PropertyManager"),
    "lease_accountant_headers": build_user_headers("test-lease-accountant-1", "LeaseAccountant"),
    "abstractor_headers": build_user_headers("test-abstractor-1", "Abstractor"),
    "certifier_headers": build_user_headers("test-certifier-1", "Certifier"),
}

# Default distinct operator ids used by fixtures for segregation-controlled
# transitions: the certifier must differ from the abstractor (PRD §2.9).
DEFAULT_ABSTRACTOR_USER_ID = "test-abstractor-1"
DEFAULT_CERTIFIER_USER_ID = "test-certifier-1"
DEFAULT_POSTER_USER_ID = "test-lease-accountant-1"
DEFAULT_APPROVER_USER_ID = "test-portfolio-manager-1"


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_portfolio_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PortfolioManager")


def make_property_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PropertyManager")


def make_lease_accountant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LeaseAccountant")


def make_abstractor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Abstractor")


def make_certifier_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Certifier")
