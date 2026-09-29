"""
Role headers for the five declared roles.

Two roles carry opaque identities (StateRegulator, RegistryAdministrator) and
can use shared constant identifiers. Three roles are entity-backed
(WarehouseOperator -> Warehouse.id, Depositor -> Party.id, Lender -> Party.id)
and MUST be built per row with the make_*_headers helpers so that ownership
checks resolve against the real entity id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DEPOSITOR,
    ROLE_LENDER,
    ROLE_REGISTRY_ADMINISTRATOR,
    ROLE_STATE_REGULATOR,
    ROLE_WAREHOUSE_OPERATOR,
)

# --- opaque identities ------------------------------------------------------
# The regulator who files and licenses a warehouse is recorded in
# licensed_by_user_id; a second regulator identity is needed to examine that
# warehouse's reports without violating segregation of duties.
REGULATOR_USER_ID = "reg-001"
SECOND_REGULATOR_USER_ID = "reg-002"
REGISTRY_ADMIN_USER_ID = "reg-admin-001"

REGULATOR_HEADERS = build_user_headers(REGULATOR_USER_ID, ROLE_STATE_REGULATOR)
SECOND_REGULATOR_HEADERS = build_user_headers(
    SECOND_REGULATOR_USER_ID, ROLE_STATE_REGULATOR
)
REGISTRY_ADMIN_HEADERS = build_user_headers(
    REGISTRY_ADMIN_USER_ID, ROLE_REGISTRY_ADMINISTRATOR
)

# --- header sets used by the unauthenticated / unauthorized probes ----------
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}


def make_regulator_headers(user_id: str = REGULATOR_USER_ID) -> Dict[str, str]:
    """StateRegulator headers for an arbitrary opaque regulator identity."""
    return build_user_headers(user_id, ROLE_STATE_REGULATOR)


def make_registry_admin_headers(
    user_id: str = REGISTRY_ADMIN_USER_ID,
) -> Dict[str, str]:
    """RegistryAdministrator headers for an arbitrary opaque registry identity."""
    return build_user_headers(user_id, ROLE_REGISTRY_ADMINISTRATOR)


def make_warehouse_operator_headers(warehouse_id: str) -> Dict[str, str]:
    """WarehouseOperator headers whose X-User-ID is the operated Warehouse.id."""
    return build_user_headers(warehouse_id, ROLE_WAREHOUSE_OPERATOR)


def make_depositor_headers(party_id: str) -> Dict[str, str]:
    """Depositor headers whose X-User-ID is the depositor's Party.id."""
    return build_user_headers(party_id, ROLE_DEPOSITOR)


def make_lender_headers(party_id: str) -> Dict[str, str]:
    """Lender headers whose X-User-ID is the lender's Party.id."""
    return build_user_headers(party_id, ROLE_LENDER)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary (role, user_id) pair."""
    return build_user_headers(user_id, role)


# Shared header set keyed by role, for role-matrix probes where the identity
# does not have to belong to any particular row (ERR_UNAUTHORIZED is decided at
# a strictly higher priority than ownership).
TEST_USERS = {
    ROLE_STATE_REGULATOR: REGULATOR_HEADERS,
    ROLE_REGISTRY_ADMINISTRATOR: REGISTRY_ADMIN_HEADERS,
    ROLE_WAREHOUSE_OPERATOR: build_user_headers("wh-user-001", ROLE_WAREHOUSE_OPERATOR),
    ROLE_DEPOSITOR: build_user_headers("dep-user-001", ROLE_DEPOSITOR),
    ROLE_LENDER: build_user_headers("len-user-001", ROLE_LENDER),
}
