"""Pre-built role headers for every role in PRD §2.1.

All four roles use opaque operator identifiers (PRD §2.1): X-User-ID is never
compared to any entity's id, so the shared constants are the canonical form.
The per-role make_* builders exist for segregation-of-duties probes, where the
caller must control the operator id (e.g., a Controller presenting the same
X-User-ID as the disposal requester).
"""
from prd_bench_local_runner.testing import build_user_headers

ACCT_USER_ID = "u_acct_1"
CTRL_USER_ID = "u_ctrl_1"
CLERK_USER_ID = "u_clerk_1"
TAX_USER_ID = "u_tax_1"

TEST_USERS = {
    "asset_accountant_headers": build_user_headers(ACCT_USER_ID, "AssetAccountant"),
    "controller_headers": build_user_headers(CTRL_USER_ID, "Controller"),
    "inventory_clerk_headers": build_user_headers(CLERK_USER_ID, "InventoryClerk"),
    "tax_analyst_headers": build_user_headers(TAX_USER_ID, "TaxAnalyst"),
}

# Headers carrying no X-User-ID / X-User-Role at all (PRD §2.1 auth probes).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_asset_accountant_headers(user_id: str) -> dict:
    """AssetAccountant with a caller-chosen operator id (SoD probes)."""
    return build_user_headers(user_id, "AssetAccountant")


def make_controller_headers(user_id: str) -> dict:
    """Controller with a caller-chosen operator id (SoD probes)."""
    return build_user_headers(user_id, "Controller")


def make_inventory_clerk_headers(user_id: str) -> dict:
    """InventoryClerk with a caller-chosen operator id."""
    return build_user_headers(user_id, "InventoryClerk")


def make_tax_analyst_headers(user_id: str) -> dict:
    """TaxAnalyst with a caller-chosen operator id."""
    return build_user_headers(user_id, "TaxAnalyst")
