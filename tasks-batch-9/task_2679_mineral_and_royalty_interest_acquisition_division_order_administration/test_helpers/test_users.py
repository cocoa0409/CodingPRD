"""Canonical acting users and pre-built auth headers.

Every role except RoyaltyOwner carries an opaque staff identifier, so a fixed
header dict per role is enough. A RoyaltyOwner's X-User-ID must be the actual
RoyaltyOwner id, so its headers are built per instance.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ACQUISITION_MANAGER,
    ROLE_DIVISION_ORDER_ADMIN,
    ROLE_OPERATOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_ROYALTY_OWNER,
    ROLE_TITLE_ANALYST,
)

# --- Opaque staff identifiers ---------------------------------------------
ANALYST_USER_ID = "ta-user-001"
ANALYST_USER_ID_ALT = "ta-user-002"

MANAGER_USER_ID = "am-user-001"
MANAGER_USER_ID_ALT = "am-user-002"

ADMIN_USER_ID = "do-user-001"
ADMIN_USER_ID_ALT = "do-user-002"

OPERATOR_USER_ID = "op-user-001"
OPERATOR_USER_ID_ALT = "op-user-002"

PLATFORM_ADMIN_USER_ID = "pa-user-001"

# --- Pre-built headers ----------------------------------------------------
ANALYST_HEADERS = build_user_headers(ANALYST_USER_ID, ROLE_TITLE_ANALYST)
ANALYST_ALT_HEADERS = build_user_headers(ANALYST_USER_ID_ALT, ROLE_TITLE_ANALYST)

MANAGER_HEADERS = build_user_headers(MANAGER_USER_ID, ROLE_ACQUISITION_MANAGER)
MANAGER_ALT_HEADERS = build_user_headers(
    MANAGER_USER_ID_ALT, ROLE_ACQUISITION_MANAGER
)

ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, ROLE_DIVISION_ORDER_ADMIN)
ADMIN_ALT_HEADERS = build_user_headers(ADMIN_USER_ID_ALT, ROLE_DIVISION_ORDER_ADMIN)

OPERATOR_HEADERS = build_user_headers(OPERATOR_USER_ID, ROLE_OPERATOR)
OPERATOR_ALT_HEADERS = build_user_headers(OPERATOR_USER_ID_ALT, ROLE_OPERATOR)

PLATFORM_ADMIN_HEADERS = build_user_headers(
    PLATFORM_ADMIN_USER_ID, ROLE_PLATFORM_ADMIN
)


def make_royalty_owner_headers(owner_id: str) -> dict:
    """Headers for the RoyaltyOwner whose entity id is owner_id."""
    return build_user_headers(owner_id, ROLE_ROYALTY_OWNER)


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> dict:
    """Headers carrying a role but no X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> dict:
    """Headers carrying an X-User-ID but no role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


TEST_USERS = {
    "analyst_headers": ANALYST_HEADERS,
    "analyst_alt_headers": ANALYST_ALT_HEADERS,
    "manager_headers": MANAGER_HEADERS,
    "manager_alt_headers": MANAGER_ALT_HEADERS,
    "admin_headers": ADMIN_HEADERS,
    "admin_alt_headers": ADMIN_ALT_HEADERS,
    "operator_headers": OPERATOR_HEADERS,
    "operator_alt_headers": OPERATOR_ALT_HEADERS,
    "platform_admin_headers": PLATFORM_ADMIN_HEADERS,
}
