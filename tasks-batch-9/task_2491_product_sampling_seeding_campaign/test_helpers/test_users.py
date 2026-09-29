"""Caller identities and the header builders that carry them.

PRD §2.1 requires every request to declare both ``X-User-ID`` and
``X-User-Role``.  Most roles are opaque directory principals, so a fixed UUID
per role is enough.  The Panelist role is backed by a Panelist entity, so a
Panelist caller's ``X-User-ID`` must be the id of the panelist row it acts as;
``make_panelist_headers`` exists for exactly that.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque directory principals.  Two distinct ComplianceModerator identities are
# needed because the PRD forbids one moderator from both requesting changes and
# approving, and from both opening and substantiating a diversion case.
TEST_USERS = {
    "campaign_manager": {
        "user_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "role": UserRole.CAMPAIGN_MANAGER.value,
    },
    "moderator_a": {
        "user_id": "11111111-1111-4111-8111-111111111111",
        "role": UserRole.COMPLIANCE_MODERATOR.value,
    },
    "moderator_b": {
        "user_id": "22222222-2222-4222-8222-222222222222",
        "role": UserRole.COMPLIANCE_MODERATOR.value,
    },
    "fulfillment_ops": {
        "user_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "role": UserRole.FULFILLMENT_OPS.value,
    },
    "platform_admin": {
        "user_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "role": UserRole.PLATFORM_ADMIN.value,
    },
    "anonymous": {
        "user_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "role": UserRole.ANONYMOUS.value,
    },
}

MODERATOR_A_USER_ID = TEST_USERS["moderator_a"]["user_id"]
MODERATOR_B_USER_ID = TEST_USERS["moderator_b"]["user_id"]
CAMPAIGN_MANAGER_USER_ID = TEST_USERS["campaign_manager"]["user_id"]
FULFILLMENT_OPS_USER_ID = TEST_USERS["fulfillment_ops"]["user_id"]
PLATFORM_ADMIN_USER_ID = TEST_USERS["platform_admin"]["user_id"]
ANONYMOUS_USER_ID = TEST_USERS["anonymous"]["user_id"]

# A syntactically valid UUID that never belongs to any created panelist; useful
# for proving an ownership check rejects a stranger rather than 404-ing.
NOBODY_USER_ID = "99999999-9999-4999-8999-999999999999"


def _headers(key: str) -> Dict[str, str]:
    user = TEST_USERS[key]
    return build_user_headers(user["user_id"], user["role"])


def campaign_manager_headers() -> Dict[str, str]:
    return _headers("campaign_manager")


def moderator_a_headers() -> Dict[str, str]:
    return _headers("moderator_a")


def moderator_b_headers() -> Dict[str, str]:
    return _headers("moderator_b")


def fulfillment_ops_headers() -> Dict[str, str]:
    return _headers("fulfillment_ops")


def platform_admin_headers() -> Dict[str, str]:
    return _headers("platform_admin")


def anonymous_headers() -> Dict[str, str]:
    return _headers("anonymous")


def make_panelist_headers(user_id: str) -> Dict[str, str]:
    """Headers for a Panelist caller acting as the panelist row ``user_id``.

    Ownership-gated operations compare the caller's ``X-User-ID`` against the
    panelist behind the enrollment, so this must always receive a real
    panelist id.
    """
    return build_user_headers(user_id, UserRole.PANELIST.value)


def make_moderator_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary ComplianceModerator identity."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_MODERATOR.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary identity/role pair."""
    return build_user_headers(user_id, role)
