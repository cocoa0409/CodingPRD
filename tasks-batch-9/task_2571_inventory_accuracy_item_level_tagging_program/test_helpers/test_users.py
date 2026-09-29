"""
Acting identities.

The PRD authenticates every request with `X-User-Role` plus `X-User-ID`.
Four of the seven roles carry an opaque operator id; the remaining three are
entity-backed, meaning the `X-User-ID` must be the id of the Store, Vendor or
CounterFirm the caller is acting for.  Those three therefore have *builders*
rather than constants: the entity id only exists once the fixture has created
the row.
"""

from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Role names
# ---------------------------------------------------------------------------
ROLE_SYSTEM_ADMIN = "SystemAdmin"
ROLE_INVENTORY_ANALYST = "InventoryAnalyst"
ROLE_INVENTORY_SUPERVISOR = "InventorySupervisor"
ROLE_SHRINK_CONTROLLER = "ShrinkController"
ROLE_STORE_OPS = "StoreOps"
ROLE_VENDOR_REP = "VendorRep"
ROLE_THIRD_PARTY_COUNTER = "ThirdPartyCounter"

ALL_ROLES = (
    ROLE_SYSTEM_ADMIN,
    ROLE_INVENTORY_ANALYST,
    ROLE_INVENTORY_SUPERVISOR,
    ROLE_SHRINK_CONTROLLER,
    ROLE_STORE_OPS,
    ROLE_VENDOR_REP,
    ROLE_THIRD_PARTY_COUNTER,
)

# ---------------------------------------------------------------------------
# Opaque operator ids
# ---------------------------------------------------------------------------
USER_ADMIN_1 = "u_admin_1"
USER_ANALYST_1 = "u_analyst_1"
USER_ANALYST_2 = "u_analyst_2"
USER_SUPERVISOR_1 = "u_super_1"
USER_SUPERVISOR_2 = "u_super_2"
USER_CONTROLLER_1 = "u_ctrl_1"
USER_CONTROLLER_2 = "u_ctrl_2"

# ---------------------------------------------------------------------------
# Ready-made header dicts for the opaque-identity roles
# ---------------------------------------------------------------------------
ADMIN = build_user_headers(USER_ADMIN_1, ROLE_SYSTEM_ADMIN)
ANALYST = build_user_headers(USER_ANALYST_1, ROLE_INVENTORY_ANALYST)
ANALYST_2 = build_user_headers(USER_ANALYST_2, ROLE_INVENTORY_ANALYST)
SUPERVISOR = build_user_headers(USER_SUPERVISOR_1, ROLE_INVENTORY_SUPERVISOR)
SUPERVISOR_2 = build_user_headers(USER_SUPERVISOR_2, ROLE_INVENTORY_SUPERVISOR)
CONTROLLER = build_user_headers(USER_CONTROLLER_1, ROLE_SHRINK_CONTROLLER)
CONTROLLER_2 = build_user_headers(USER_CONTROLLER_2, ROLE_SHRINK_CONTROLLER)

TEST_USERS = {
    ROLE_SYSTEM_ADMIN: ADMIN,
    ROLE_INVENTORY_ANALYST: ANALYST,
    ROLE_INVENTORY_SUPERVISOR: SUPERVISOR,
    ROLE_SHRINK_CONTROLLER: CONTROLLER,
}


# ---------------------------------------------------------------------------
# Entity-backed identity builders
# ---------------------------------------------------------------------------
def make_store_ops_headers(store_id: str) -> dict:
    """StoreOps acts for exactly one Store; X-User-ID is that Store's id."""
    return build_user_headers(store_id, ROLE_STORE_OPS)


def make_vendor_rep_headers(vendor_id: str) -> dict:
    """VendorRep acts for exactly one Vendor; X-User-ID is that Vendor's id."""
    return build_user_headers(vendor_id, ROLE_VENDOR_REP)


def make_counter_headers(counter_firm_id: str) -> dict:
    """ThirdPartyCounter acts for one CounterFirm; X-User-ID is that firm's id."""
    return build_user_headers(counter_firm_id, ROLE_THIRD_PARTY_COUNTER)


def headers_for(role: str, user_id: str) -> dict:
    """Free-form identity, for tests that must pin an unusual role/id pairing."""
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def headers_without_role(user_id: str = USER_ANALYST_1) -> dict:
    """Authentication headers with the role omitted."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_INVENTORY_ANALYST) -> dict:
    """Authentication headers with the user id omitted."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
