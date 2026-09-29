"""Pre-built role headers for every role in the PRD (§2.1).

All five roles are opaque operator identities: `X-User-ID` is never compared to
any entity's `id` and there is no resource-ownership check anywhere in this API.
What the identifiers *are* used for is segregation of duties, so the helpers
below let a test choose a distinct operator per step.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque operator identifiers reused across fixtures.
STORE_ADMIN_USER_ID = "admin-01"
MEAT_CUTTER_USER_ID = "cutter-01"
SECOND_MEAT_CUTTER_USER_ID = "cutter-02"
MEAT_MANAGER_USER_ID = "mgr-01"
SECOND_MEAT_MANAGER_USER_ID = "mgr-02"
PRICING_ANALYST_USER_ID = "analyst-01"
SERVICE_CLERK_USER_ID = "clerk-01"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "store_admin_headers": build_user_headers(STORE_ADMIN_USER_ID, "StoreAdmin"),
    "meat_cutter_headers": build_user_headers(MEAT_CUTTER_USER_ID, "MeatCutter"),
    "second_meat_cutter_headers": build_user_headers(
        SECOND_MEAT_CUTTER_USER_ID, "MeatCutter"
    ),
    "meat_manager_headers": build_user_headers(MEAT_MANAGER_USER_ID, "MeatManager"),
    "second_meat_manager_headers": build_user_headers(
        SECOND_MEAT_MANAGER_USER_ID, "MeatManager"
    ),
    "pricing_analyst_headers": build_user_headers(PRICING_ANALYST_USER_ID, "PricingAnalyst"),
    "service_clerk_headers": build_user_headers(SERVICE_CLERK_USER_ID, "ServiceClerk"),
}


def make_store_admin_headers(user_id: str = STORE_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "StoreAdmin")


def make_meat_cutter_headers(user_id: str = MEAT_CUTTER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "MeatCutter")


def make_meat_manager_headers(user_id: str = MEAT_MANAGER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "MeatManager")


def make_pricing_analyst_headers(user_id: str = PRICING_ANALYST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "PricingAnalyst")


def make_service_clerk_headers(user_id: str = SERVICE_CLERK_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "ServiceClerk")


def make_role_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary role/operator pair — used for authorization probes and for
    segregation-of-duties paths that need a specific `X-User-ID`."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying only `X-User-Role`, with `X-User-ID` absent."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers carrying only `X-User-ID`, with `X-User-Role` absent."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_auth() -> Dict[str, str]:
    """Headers carrying neither `X-User-ID` nor `X-User-Role`."""
    return {"Content-Type": "application/json"}
