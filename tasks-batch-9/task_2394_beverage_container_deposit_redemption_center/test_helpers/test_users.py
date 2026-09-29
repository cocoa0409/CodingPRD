"""Auth headers for the six roles.

Two roles are opaque: a ``ProgramAdmin`` and a ``PlantCounter`` carry an
operator identifier that is never compared to any stored row, so a fixed
constant header is correct for them.

The other four roles are entity-backed — ``X-User-ID`` *is* the id of the
acting ``Distributor``, ``RedemptionCenter``, ``RedeemerAccount`` or
``Retailer`` — so ownership-gated calls must use the ``make_*_headers``
builders with the real entity id rather than a shared constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_DISTRIBUTOR_AGENT = "DistributorAgent"
ROLE_CENTER_OPERATOR = "CenterOperator"
ROLE_PLANT_COUNTER = "PlantCounter"
ROLE_ACCOUNT_HOLDER = "AccountHolder"
ROLE_RETAIL_CLERK = "RetailClerk"

ALL_ROLES = [
    ROLE_PROGRAM_ADMIN,
    ROLE_DISTRIBUTOR_AGENT,
    ROLE_CENTER_OPERATOR,
    ROLE_PLANT_COUNTER,
    ROLE_ACCOUNT_HOLDER,
    ROLE_RETAIL_CLERK,
]

ENTITY_BACKED_ROLES = [
    ROLE_DISTRIBUTOR_AGENT,
    ROLE_CENTER_OPERATOR,
    ROLE_ACCOUNT_HOLDER,
    ROLE_RETAIL_CLERK,
]

OPAQUE_ROLES = [ROLE_PROGRAM_ADMIN, ROLE_PLANT_COUNTER]

ADMIN_USER_ID = "admin-1"
PLANT_COUNTER_USER_ID = "plant-1"

# Placeholder identifiers for the entity-backed roles. These are only correct
# for calls where no ownership comparison happens (for example a role-gate
# rejection that is decided before any row is addressed). Ownership-gated calls
# must use make_distributor_headers / make_center_headers /
# make_account_headers / make_retailer_headers.
PLACEHOLDER_DISTRIBUTOR_ID = "00000000-0000-4000-8000-0000000000d1"
PLACEHOLDER_CENTER_ID = "00000000-0000-4000-8000-0000000000c1"
PLACEHOLDER_ACCOUNT_ID = "00000000-0000-4000-8000-0000000000a1"
PLACEHOLDER_RETAILER_ID = "00000000-0000-4000-8000-0000000000e1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_PROGRAM_ADMIN: build_user_headers(ADMIN_USER_ID, ROLE_PROGRAM_ADMIN),
    ROLE_PLANT_COUNTER: build_user_headers(PLANT_COUNTER_USER_ID, ROLE_PLANT_COUNTER),
    ROLE_DISTRIBUTOR_AGENT: build_user_headers(
        PLACEHOLDER_DISTRIBUTOR_ID, ROLE_DISTRIBUTOR_AGENT
    ),
    ROLE_CENTER_OPERATOR: build_user_headers(
        PLACEHOLDER_CENTER_ID, ROLE_CENTER_OPERATOR
    ),
    ROLE_ACCOUNT_HOLDER: build_user_headers(
        PLACEHOLDER_ACCOUNT_ID, ROLE_ACCOUNT_HOLDER
    ),
    ROLE_RETAIL_CLERK: build_user_headers(PLACEHOLDER_RETAILER_ID, ROLE_RETAIL_CLERK),
}

ADMIN_HEADERS = TEST_USERS[ROLE_PROGRAM_ADMIN]
PLANT_COUNTER_HEADERS = TEST_USERS[ROLE_PLANT_COUNTER]


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Programme staff headers; the identifier is opaque and never matched."""
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


def make_plant_counter_headers(
    user_id: str = PLANT_COUNTER_USER_ID,
) -> Dict[str, str]:
    """Central plant staff headers; the identifier is opaque and never matched."""
    return build_user_headers(user_id, ROLE_PLANT_COUNTER)


def make_distributor_headers(distributor_id: str) -> Dict[str, str]:
    """Headers for the agent of the distributor whose id is given."""
    return build_user_headers(distributor_id, ROLE_DISTRIBUTOR_AGENT)


def make_center_headers(center_id: str) -> Dict[str, str]:
    """Headers for the operator of the redemption centre whose id is given."""
    return build_user_headers(center_id, ROLE_CENTER_OPERATOR)


def make_account_headers(account_id: str) -> Dict[str, str]:
    """Headers for the holder of the redeemer account whose id is given."""
    return build_user_headers(account_id, ROLE_ACCOUNT_HOLDER)


def make_retailer_headers(retailer_id: str) -> Dict[str, str]:
    """Headers for the clerk of the retail store whose id is given."""
    return build_user_headers(retailer_id, ROLE_RETAIL_CLERK)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identifier/role pair, for role-gate and bad-role probes."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that name a role but omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that name a principal but omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
