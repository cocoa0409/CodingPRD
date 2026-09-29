"""Identity headers for the five roles the PRD declares.

PRD §2.1: "`X-User-ID` identifies the acting user and `X-User-Role` declares the
capacity in which they act."  Two of the five roles are entity-backed, so their
`X-User-ID` is not an opaque handle:

* `BusinessUnitOwner` — the id **is** the BusinessUnit's `id`, so headers for
  this role can only be built once the unit exists.  Use
  :func:`make_business_unit_owner_headers`.
* `ResourceOwner` — the id is compared against the `owner_user_id` string
  recorded on the CloudResource, so headers must carry the exact string that
  was supplied at provisioning time.  Use :func:`make_resource_owner_headers`.

The remaining three roles (`FinOpsAnalyst`, `FinOpsController`,
`PlatformAdmin`) carry opaque user ids, and a *pair* of distinct ids is exposed
for the controller because segregation of duties compares two actors.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ANALYST,
    ROLE_BU_OWNER,
    ROLE_CONTROLLER,
    ROLE_PLATFORM_ADMIN,
    ROLE_RESOURCE_OWNER,
)

# ─── Opaque actor identities ──────────────────────────────────────────────
ANALYST_ID = "analyst-1"
ANALYST_ALT_ID = "analyst-7"
CONTROLLER_ID = "controller-1"
CONTROLLER_ALT_ID = "controller-2"
ADMIN_ID = "admin-1"

# ─── Resource-owner identities (literal owner_user_id strings) ────────────
OWNER_1 = "owner-1"
OWNER_2 = "owner-2"
OWNER_3 = "owner-3"
OWNER_4 = "owner-4"
OWNER_5 = "owner-5"
OWNER_6 = "owner-6"
OWNER_7 = "owner-7"
OWNER_9 = "owner-9"

ANALYST_HEADERS = build_user_headers(ANALYST_ID, ROLE_ANALYST)
ANALYST_ALT_HEADERS = build_user_headers(ANALYST_ALT_ID, ROLE_ANALYST)
CONTROLLER_HEADERS = build_user_headers(CONTROLLER_ID, ROLE_CONTROLLER)
CONTROLLER_ALT_HEADERS = build_user_headers(CONTROLLER_ALT_ID, ROLE_CONTROLLER)
ADMIN_HEADERS = build_user_headers(ADMIN_ID, ROLE_PLATFORM_ADMIN)

# A request with neither X-User-ID nor X-User-Role.  PRD §2.1: absent headers
# are rejected with ERR_UNAUTHENTICATED.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

# A request whose X-User-ID is present but empty.
EMPTY_USER_ID_HEADERS = build_user_headers("", ROLE_ANALYST)


def make_business_unit_owner_headers(business_unit_id: str) -> Dict[str, str]:
    """Headers for the owner of ``business_unit_id``.

    The acting id is the business unit's own id, so a mismatch between this id
    and the unit that owns the target entity is what produces
    ERR_NOT_RESOURCE_OWNER.
    """
    return build_user_headers(business_unit_id, ROLE_BU_OWNER)


def make_resource_owner_headers(owner_user_id: str) -> Dict[str, str]:
    """Headers for the resource owner whose id is ``owner_user_id``.

    This must be the literal string handed to the provisioning request as
    ``owner_user_id``; anything else is a different person.
    """
    return build_user_headers(owner_user_id, ROLE_RESOURCE_OWNER)


def make_analyst_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_ANALYST)


def make_controller_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CONTROLLER)


def make_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


TEST_USERS: Dict[str, Dict[str, str]] = {
    "analyst_headers": ANALYST_HEADERS,
    "analyst_alt_headers": ANALYST_ALT_HEADERS,
    "controller_headers": CONTROLLER_HEADERS,
    "controller_alt_headers": CONTROLLER_ALT_HEADERS,
    "admin_headers": ADMIN_HEADERS,
    "no_auth_headers": NO_AUTH_HEADERS,
    "empty_user_id_headers": EMPTY_USER_ID_HEADERS,
}
