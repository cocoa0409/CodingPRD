"""Caller identities for every declared role.

"Every request carries the caller's identity in two headers: X-User-ID and
X-User-Role."  Six of the seven roles are plain identity strings.  StoreManager
is entity backed: "a StoreManager's X-User-ID is the id of the RetailStore they
manage", so its headers must be built from a real store id.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_FRAUD_ANALYST,
    ROLE_LIABILITY_ACCOUNTANT,
    ROLE_PLATFORM_ADMIN,
    ROLE_POS_ASSOCIATE,
    ROLE_RESELLER_PARTNER,
    ROLE_RISK_MANAGER,
    ROLE_STORE_MANAGER,
)

# Default user ids used whenever a test does not care about the specific actor.
DEFAULT_USER_IDS = {
    ROLE_POS_ASSOCIATE: "pos-default",
    ROLE_FRAUD_ANALYST: "analyst-default",
    ROLE_RISK_MANAGER: "risk-default",
    ROLE_LIABILITY_ACCOUNTANT: "acct-default",
    ROLE_RESELLER_PARTNER: "partner-default",
    ROLE_PLATFORM_ADMIN: "admin-default",
}


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/user-id pair."""
    return build_user_headers(user_id, role)


def make_pos_associate_headers(user_id: str = None) -> dict:
    return build_user_headers(user_id or DEFAULT_USER_IDS[ROLE_POS_ASSOCIATE], ROLE_POS_ASSOCIATE)


def make_fraud_analyst_headers(user_id: str = None) -> dict:
    return build_user_headers(user_id or DEFAULT_USER_IDS[ROLE_FRAUD_ANALYST], ROLE_FRAUD_ANALYST)


def make_risk_manager_headers(user_id: str = None) -> dict:
    return build_user_headers(user_id or DEFAULT_USER_IDS[ROLE_RISK_MANAGER], ROLE_RISK_MANAGER)


def make_liability_accountant_headers(user_id: str = None) -> dict:
    return build_user_headers(
        user_id or DEFAULT_USER_IDS[ROLE_LIABILITY_ACCOUNTANT], ROLE_LIABILITY_ACCOUNTANT
    )


def make_reseller_partner_headers(user_id: str = None) -> dict:
    return build_user_headers(
        user_id or DEFAULT_USER_IDS[ROLE_RESELLER_PARTNER], ROLE_RESELLER_PARTNER
    )


def make_platform_admin_headers(user_id: str = None) -> dict:
    return build_user_headers(user_id or DEFAULT_USER_IDS[ROLE_PLATFORM_ADMIN], ROLE_PLATFORM_ADMIN)


def make_store_manager_headers(store_id: str) -> dict:
    """StoreManager identity: X-User-ID must be the managed store's id."""
    return build_user_headers(store_id, ROLE_STORE_MANAGER)


def make_anonymous_headers(role: str = ROLE_PLATFORM_ADMIN) -> dict:
    """An empty X-User-ID, which the PRD treats as an absent identity."""
    return build_user_headers("", role)


# Ready-made header dicts for the six non-entity-backed roles.
ADMIN = make_platform_admin_headers()
POS = make_pos_associate_headers()
ANALYST = make_fraud_analyst_headers()
RISK = make_risk_manager_headers()
ACCOUNTANT = make_liability_accountant_headers()
PARTNER = make_reseller_partner_headers()

TEST_USERS = {
    ROLE_POS_ASSOCIATE: POS,
    ROLE_FRAUD_ANALYST: ANALYST,
    ROLE_RISK_MANAGER: RISK,
    ROLE_LIABILITY_ACCOUNTANT: ACCOUNTANT,
    ROLE_RESELLER_PARTNER: PARTNER,
    ROLE_PLATFORM_ADMIN: ADMIN,
}

# Every role that may read the ordinary collections.
READ_ALL_ROLES = [
    ROLE_POS_ASSOCIATE,
    ROLE_FRAUD_ANALYST,
    ROLE_RISK_MANAGER,
    ROLE_LIABILITY_ACCOUNTANT,
    ROLE_RESELLER_PARTNER,
    ROLE_PLATFORM_ADMIN,
]
