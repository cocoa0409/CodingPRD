"""Header builders for the six roles the PRD defines.

`Reseller` and `Distributor` are entity-backed: the PRD requires the caller's
`X-User-ID` to equal the `id` of the row being acted on, so tests must build
those headers per entity with `make_reseller_headers` / `make_distributor_headers`
rather than reusing a shared constant.  The four brand-staff roles are opaque.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identities.  Two counsel identities exist because the PRD
# requires the issuer of a termination notice to differ from the issuer of the
# governing suspension notice.
BCM_1 = "bcm-1"
BCM_2 = "bcm-2"
COUNSEL_1 = "counsel-1"
COUNSEL_2 = "counsel-2"
ANALYST_1 = "analyst-1"
ANALYST_2 = "analyst-2"
ADMIN_1 = "admin-1"

TEST_USERS = {
    "brand_channel_manager": build_user_headers(BCM_1, UserRole.BRAND_CHANNEL_MANAGER.value),
    "brand_channel_manager_2": build_user_headers(BCM_2, UserRole.BRAND_CHANNEL_MANAGER.value),
    "brand_legal_counsel": build_user_headers(COUNSEL_1, UserRole.BRAND_LEGAL_COUNSEL.value),
    "brand_legal_counsel_2": build_user_headers(COUNSEL_2, UserRole.BRAND_LEGAL_COUNSEL.value),
    "monitoring_analyst": build_user_headers(ANALYST_1, UserRole.MONITORING_ANALYST.value),
    "monitoring_analyst_2": build_user_headers(ANALYST_2, UserRole.MONITORING_ANALYST.value),
    "platform_admin": build_user_headers(ADMIN_1, UserRole.PLATFORM_ADMIN.value),
}

BCM_HEADERS = TEST_USERS["brand_channel_manager"]
BCM_2_HEADERS = TEST_USERS["brand_channel_manager_2"]
COUNSEL_HEADERS = TEST_USERS["brand_legal_counsel"]
COUNSEL_2_HEADERS = TEST_USERS["brand_legal_counsel_2"]
ANALYST_HEADERS = TEST_USERS["monitoring_analyst"]
ANALYST_2_HEADERS = TEST_USERS["monitoring_analyst_2"]
ADMIN_HEADERS = TEST_USERS["platform_admin"]


def make_reseller_headers(reseller_id):
    """Headers for the Reseller role, identified by the reseller row's own id."""
    return build_user_headers(reseller_id, UserRole.RESELLER.value)


def make_distributor_headers(distributor_id):
    """Headers for the Distributor role, identified by the distributor's own id."""
    return build_user_headers(distributor_id, UserRole.DISTRIBUTOR.value)


def make_headers(user_id, role):
    """Headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


def headers_for_role(role, entity_id=None):
    """Headers for any role; entity-backed roles need the owning row's id."""
    if role == UserRole.RESELLER.value:
        return make_reseller_headers(entity_id)
    if role == UserRole.DISTRIBUTOR.value:
        return make_distributor_headers(entity_id)
    return build_user_headers(f"user-{role.lower()}", role)


# Headers whose role value is not one of the six the PRD recognises.
UNKNOWN_ROLE_HEADERS = build_user_headers("stranger-1", "NotARole")
MISSING_ROLE_HEADERS = {"X-User-ID": "stranger-1", "Content-Type": "application/json"}
MISSING_USER_HEADERS = {
    "X-User-Role": UserRole.BRAND_CHANNEL_MANAGER.value,
    "Content-Type": "application/json",
}
