"""Pre-built auth headers for every role, plus builders for entity-backed roles.

PRD 2.1 splits the six roles in two. `PlatformAdmin`, `ComplianceOfficer` and
`SecretShopperAuditor` are opaque operator identities, so a fixed identifier is
enough for the whole suite. `Customer`, `PartnerManager` and `Courier` are
entity-backed: `X-User-ID` is the primary key of a persisted row, so headers for
those roles must be built per entity with the identifier the API minted.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_COURIER,
    ROLE_CUSTOMER,
    ROLE_PARTNER_MANAGER,
    ROLE_PLATFORM_ADMIN,
    ROLE_SECRET_SHOPPER_AUDITOR,
)

# Opaque operator identifiers (PRD 2.1). The two officer identities exist
# separately because the segregation-of-duties rule of PRD 2.1 compares them.
ADMIN_USER_ID = "admin_1"
OFFICER_A_USER_ID = "officer_a"
OFFICER_B_USER_ID = "officer_b"
AUDITOR_USER_ID = "auditor_1"

ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, ROLE_PLATFORM_ADMIN)
OFFICER_A_HEADERS = build_user_headers(OFFICER_A_USER_ID, ROLE_COMPLIANCE_OFFICER)
OFFICER_B_HEADERS = build_user_headers(OFFICER_B_USER_ID, ROLE_COMPLIANCE_OFFICER)
AUDITOR_HEADERS = build_user_headers(AUDITOR_USER_ID, ROLE_SECRET_SHOPPER_AUDITOR)

# Convenience alias: most officer-driven setup runs as officer_a.
OFFICER_HEADERS = OFFICER_A_HEADERS

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_PLATFORM_ADMIN: ADMIN_HEADERS,
    ROLE_COMPLIANCE_OFFICER: OFFICER_A_HEADERS,
    ROLE_SECRET_SHOPPER_AUDITOR: AUDITOR_HEADERS,
}


def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """Headers for a `Customer` caller whose `X-User-ID` is that customer's `id`."""
    return build_user_headers(customer_id, ROLE_CUSTOMER)


def make_partner_manager_headers(delivery_partner_id: str) -> Dict[str, str]:
    """Headers for a `PartnerManager` whose `X-User-ID` is the partner's `id`."""
    return build_user_headers(delivery_partner_id, ROLE_PARTNER_MANAGER)


def make_courier_headers(courier_id: str) -> Dict[str, str]:
    """Headers for a `Courier` caller whose `X-User-ID` is that courier's `id`."""
    return build_user_headers(courier_id, ROLE_COURIER)


def make_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `ComplianceOfficer` acting under an explicit operator id."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for a `PlatformAdmin` acting under an explicit operator id."""
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_auditor_headers(user_id: str = AUDITOR_USER_ID) -> Dict[str, str]:
    """Headers for a `SecretShopperAuditor` acting under an explicit operator id."""
    return build_user_headers(user_id, ROLE_SECRET_SHOPPER_AUDITOR)


def headers_without_auth() -> Dict[str, str]:
    """A request that carries neither `X-User-ID` nor `X-User-Role`."""
    return {"Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """A request whose `X-User-ID` is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """A request whose `X-User-Role` is present but empty."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }
