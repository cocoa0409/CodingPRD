"""Auth header builders for every role.

Creator identity is entity backed: the caller identifier must be the id of an
existing creator record, so creator headers are always built from a live id via
``make_creator_headers``. The other four roles carry opaque operator
identifiers, which are fixed here so that separation-of-duties comparisons
between two distinct reviewers are expressible.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AUDITOR,
    ROLE_CREATOR,
    ROLE_FINANCE_OPERATOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_POLICY_REVIEWER,
)

REVIEWER_ONE_ID = "reviewer-r1"
REVIEWER_TWO_ID = "reviewer-r2"
FINANCE_ONE_ID = "finance-f1"
FINANCE_TWO_ID = "finance-f2"
ADMIN_ONE_ID = "admin-a1"
AUDITOR_ONE_ID = "auditor-x1"

ADMIN = build_user_headers(ADMIN_ONE_ID, ROLE_PLATFORM_ADMIN)
FINANCE = build_user_headers(FINANCE_ONE_ID, ROLE_FINANCE_OPERATOR)
FINANCE_ALT = build_user_headers(FINANCE_TWO_ID, ROLE_FINANCE_OPERATOR)
REVIEWER = build_user_headers(REVIEWER_ONE_ID, ROLE_POLICY_REVIEWER)
REVIEWER_ALT = build_user_headers(REVIEWER_TWO_ID, ROLE_POLICY_REVIEWER)
AUDITOR = build_user_headers(AUDITOR_ONE_ID, ROLE_AUDITOR)

TEST_USERS = {
    ROLE_PLATFORM_ADMIN: ADMIN,
    ROLE_FINANCE_OPERATOR: FINANCE,
    ROLE_POLICY_REVIEWER: REVIEWER,
    ROLE_AUDITOR: AUDITOR,
}

# Roles whose identifier is opaque, i.e. never compared against a record id.
OPAQUE_ROLES = [
    ROLE_PLATFORM_ADMIN,
    ROLE_FINANCE_OPERATOR,
    ROLE_POLICY_REVIEWER,
    ROLE_AUDITOR,
]


def make_creator_headers(creator_id):
    """Headers for a creator acting on its own subtree."""
    return build_user_headers(str(creator_id), ROLE_CREATOR)


def make_reviewer_headers(user_id):
    """Headers for an arbitrary policy reviewer identifier."""
    return build_user_headers(str(user_id), ROLE_POLICY_REVIEWER)


def make_headers(role, user_id):
    """Headers for an arbitrary role/identifier pair."""
    return build_user_headers(str(user_id), str(role))


BLANK_AUTH_HEADERS = {"Content-Type": "application/json"}
UNKNOWN_ROLE_HEADERS = build_user_headers("moderator-m1", "Moderator")
