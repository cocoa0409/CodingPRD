"""Acting identities and their request headers.

Identity is opaque: the server does not resolve ``X-User-ID`` to a stored
principal, it only compares it against ids it previously recorded. Distinct
ids therefore matter for the segregation-of-duties comparisons, and one id
(``u-dual-1``) is deliberately reused across two roles.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import Role

# Distinct acting operators.
ADMIN_USER_ID = "u-admin-1"
MANAGER_USER_ID = "u-mgr-1"
MANAGER_ALT_USER_ID = "u-mgr-7"
OWNER_USER_ID = "u-owner-1"
OWNER_ALT_USER_ID = "u-owner-2"
ASSET_USER_ID = "u-asset-1"
# One human acting in two capacities; used to collide with a recorded actor id.
DUAL_USER_ID = "u-dual-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin": {"user_id": ADMIN_USER_ID, "role": Role.PLATFORM_ADMIN},
    "manager": {"user_id": MANAGER_USER_ID, "role": Role.HOTEL_MANAGER_OPS},
    "manager_alt": {"user_id": MANAGER_ALT_USER_ID, "role": Role.HOTEL_MANAGER_OPS},
    "owner": {"user_id": OWNER_USER_ID, "role": Role.OWNER_REP},
    "owner_alt": {"user_id": OWNER_ALT_USER_ID, "role": Role.OWNER_REP},
    "asset": {"user_id": ASSET_USER_ID, "role": Role.ASSET_MANAGER},
    "dual_manager": {"user_id": DUAL_USER_ID, "role": Role.HOTEL_MANAGER_OPS},
    "dual_owner": {"user_id": DUAL_USER_ID, "role": Role.OWNER_REP},
}


def headers_for(key: str) -> Dict[str, str]:
    """Headers for one of the named identities above."""
    user = TEST_USERS[key]
    return build_user_headers(user["user_id"], user["role"])


ADMIN_HEADERS = headers_for("admin")
MANAGER_HEADERS = headers_for("manager")
MANAGER_ALT_HEADERS = headers_for("manager_alt")
OWNER_HEADERS = headers_for("owner")
OWNER_ALT_HEADERS = headers_for("owner_alt")
ASSET_HEADERS = headers_for("asset")
DUAL_MANAGER_HEADERS = headers_for("dual_manager")
DUAL_OWNER_HEADERS = headers_for("dual_owner")

HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    Role.PLATFORM_ADMIN: ADMIN_HEADERS,
    Role.HOTEL_MANAGER_OPS: MANAGER_HEADERS,
    Role.ASSET_MANAGER: ASSET_HEADERS,
    Role.OWNER_REP: OWNER_HEADERS,
}


def headers_with_role(user_id: str, role: str) -> Dict[str, str]:
    """An arbitrary id/role pairing, for role-boundary probes."""
    return build_user_headers(user_id, role)


NO_HEADERS: Dict[str, str] = {}
ONLY_USER_ID_HEADERS = {"X-User-ID": MANAGER_USER_ID, "Content-Type": "application/json"}
ONLY_ROLE_HEADERS = {
    "X-User-Role": Role.HOTEL_MANAGER_OPS,
    "Content-Type": "application/json",
}

__all__ = [
    "ADMIN_HEADERS",
    "ADMIN_USER_ID",
    "ASSET_HEADERS",
    "ASSET_USER_ID",
    "DUAL_MANAGER_HEADERS",
    "DUAL_OWNER_HEADERS",
    "DUAL_USER_ID",
    "HEADERS_BY_ROLE",
    "MANAGER_ALT_HEADERS",
    "MANAGER_ALT_USER_ID",
    "MANAGER_HEADERS",
    "MANAGER_USER_ID",
    "NO_HEADERS",
    "ONLY_ROLE_HEADERS",
    "ONLY_USER_ID_HEADERS",
    "OWNER_ALT_HEADERS",
    "OWNER_ALT_USER_ID",
    "OWNER_HEADERS",
    "OWNER_USER_ID",
    "TEST_USERS",
    "headers_for",
    "headers_with_role",
]
