"""Acting identities and request headers.

PRD §2.1: every request must carry `X-User-ID` and `X-User-Role`. The four
staff roles are operator identities whose `X-User-ID` is opaque and never
compared to an entity `id`. The two counterparty roles are entity-backed: a
`Composer`'s `X-User-ID` is the id of the acting composer and a `Licensee`'s
`X-User-ID` is the id of the acting licensee, so ownership-gated calls must
thread the real row id through the header rather than use a shared constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CATALOG_ADMIN,
    ROLE_COMPOSER,
    ROLE_LICENSEE,
    ROLE_LICENSING_AGENT,
    ROLE_RIGHTS_MANAGER,
    ROLE_ROYALTY_ACCOUNTANT,
)

# Opaque operator identifiers for the four staff roles. Two distinct accountant
# identifiers exist because paying a statement requires an `X-User-ID` that
# differs from the recorded `finalized_by_user_id`.
CATALOG_ADMIN_USER_ID = "catalog-admin-1"
RIGHTS_MANAGER_USER_ID = "rights-manager-1"
LICENSING_AGENT_USER_ID = "licensing-agent-1"
ACCOUNTANT_ONE_USER_ID = "acct-1"
ACCOUNTANT_TWO_USER_ID = "acct-2"

# Placeholder identities for the entity-backed roles. These are only correct
# for negative tests where no ownership check may pass; every ownership-gated
# call must use make_composer_headers / make_licensee_headers instead.
UNKNOWN_COMPOSER_USER_ID = "00000000-0000-4000-8000-000000000901"
UNKNOWN_LICENSEE_USER_ID = "00000000-0000-4000-8000-000000000902"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "catalog_admin": {"user_id": CATALOG_ADMIN_USER_ID, "role": ROLE_CATALOG_ADMIN},
    "rights_manager": {"user_id": RIGHTS_MANAGER_USER_ID, "role": ROLE_RIGHTS_MANAGER},
    "licensing_agent": {"user_id": LICENSING_AGENT_USER_ID, "role": ROLE_LICENSING_AGENT},
    "accountant_one": {"user_id": ACCOUNTANT_ONE_USER_ID, "role": ROLE_ROYALTY_ACCOUNTANT},
    "accountant_two": {"user_id": ACCOUNTANT_TWO_USER_ID, "role": ROLE_ROYALTY_ACCOUNTANT},
    "composer": {"user_id": UNKNOWN_COMPOSER_USER_ID, "role": ROLE_COMPOSER},
    "licensee": {"user_id": UNKNOWN_LICENSEE_USER_ID, "role": ROLE_LICENSEE},
}

CATALOG_ADMIN = build_user_headers(CATALOG_ADMIN_USER_ID, ROLE_CATALOG_ADMIN)
RIGHTS_MANAGER = build_user_headers(RIGHTS_MANAGER_USER_ID, ROLE_RIGHTS_MANAGER)
LICENSING_AGENT = build_user_headers(LICENSING_AGENT_USER_ID, ROLE_LICENSING_AGENT)
ACCOUNTANT_ONE = build_user_headers(ACCOUNTANT_ONE_USER_ID, ROLE_ROYALTY_ACCOUNTANT)
ACCOUNTANT_TWO = build_user_headers(ACCOUNTANT_TWO_USER_ID, ROLE_ROYALTY_ACCOUNTANT)

HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    ROLE_CATALOG_ADMIN: CATALOG_ADMIN,
    ROLE_RIGHTS_MANAGER: RIGHTS_MANAGER,
    ROLE_LICENSING_AGENT: LICENSING_AGENT,
    ROLE_ROYALTY_ACCOUNTANT: ACCOUNTANT_ONE,
}


def make_composer_headers(composer_id: str) -> Dict[str, str]:
    """Headers for the `Composer` role acting as the composer row `composer_id`."""
    return build_user_headers(composer_id, ROLE_COMPOSER)


def make_licensee_headers(licensee_id: str) -> Dict[str, str]:
    """Headers for the `Licensee` role acting as the licensee row `licensee_id`."""
    return build_user_headers(licensee_id, ROLE_LICENSEE)


def make_accountant_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `RoyaltyAccountant` with an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_ROYALTY_ACCOUNTANT)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = CATALOG_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers carrying only `X-User-ID`, so `X-User-Role` is absent."""
    return {"X-User-ID": user_id}


def headers_for_role(role: str, entity_id: str = "") -> Dict[str, str]:
    """Headers for any of the six roles.

    Staff roles use their shared operator identifier; the two entity-backed
    roles need `entity_id` to be the id of the row they act as.
    """
    if role in HEADERS_BY_ROLE:
        return HEADERS_BY_ROLE[role]
    if role == ROLE_COMPOSER:
        return make_composer_headers(entity_id or UNKNOWN_COMPOSER_USER_ID)
    if role == ROLE_LICENSEE:
        return make_licensee_headers(entity_id or UNKNOWN_LICENSEE_USER_ID)
    raise ValueError(f"unknown role {role!r}")
