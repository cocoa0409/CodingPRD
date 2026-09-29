"""Identity headers for the five roles.

Three of the five roles are entity-backed: the ``X-User-ID`` a BuyerAdmin or
BuyerTreasury presents must be the buyer's own row id, a Supplier presents its
own supplier id and a Funder presents its own funder id, because the resource
scope check compares the header against the foreign key reachable from the
addressed row. PlatformOps is opaque: any non-empty identifier is accepted.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_BUYER_ADMIN = "BuyerAdmin"
ROLE_BUYER_TREASURY = "BuyerTreasury"
ROLE_SUPPLIER = "Supplier"
ROLE_FUNDER = "Funder"
ROLE_PLATFORM_OPS = "PlatformOps"

# Opaque operator identity; PlatformOps is not scoped to any row.
PLATFORM_OPS_USER_ID = "ops-operator-1"

TEST_USERS = {
    ROLE_PLATFORM_OPS: PLATFORM_OPS_USER_ID,
}

# Ready-made headers for the one role that needs no entity id.
PLATFORM_OPS_HEADERS: Dict[str, str] = build_user_headers(
    PLATFORM_OPS_USER_ID, ROLE_PLATFORM_OPS
)


def make_platform_ops_headers(user_id: str = PLATFORM_OPS_USER_ID) -> Dict[str, str]:
    """Headers for a platform operator (opaque identity)."""
    return build_user_headers(user_id, ROLE_PLATFORM_OPS)


def make_buyer_admin_headers(buyer_id: str) -> Dict[str, str]:
    """Headers for a programme owner acting for the buyer row ``buyer_id``."""
    return build_user_headers(buyer_id, ROLE_BUYER_ADMIN)


def make_buyer_treasury_headers(buyer_id: str) -> Dict[str, str]:
    """Headers for a treasury officer acting for the buyer row ``buyer_id``."""
    return build_user_headers(buyer_id, ROLE_BUYER_TREASURY)


def make_supplier_headers(supplier_id: str) -> Dict[str, str]:
    """Headers for the supplier that owns the supplier row ``supplier_id``."""
    return build_user_headers(supplier_id, ROLE_SUPPLIER)


def make_funder_headers(funder_id: str) -> Dict[str, str]:
    """Headers for the funder that owns the funder row ``funder_id``."""
    return build_user_headers(funder_id, ROLE_FUNDER)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary (role, identity) pair."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers carrying X-User-ID but no X-User-Role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying X-User-Role but no X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
