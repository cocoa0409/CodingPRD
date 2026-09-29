"""
Caller identities for the five roles the PRD declares.

PRD §2.1: `X-User-Role` names the operational capacity and `X-User-ID` identifies
the acting principal. Two roles are entity-backed and therefore CANNOT use a
shared constant identity:

- `DataCoordinator` — `X-User-ID` is the `id` of the acting `Department`, so use
  `make_data_coordinator_headers(department_id)` with the department the test
  actually created.
- `CommunityMember` — `X-User-ID` is the `id` of the acting `CommunityMember`, so
  use `make_community_member_headers(member_id)`.

`PortalAdmin` and `PrivacyReviewer` identities are opaque operator identifiers the
server never resolves against any entity, so fixed constants are correct for them.
Privacy work needs two distinct reviewer identities because a reviewer whose
`X-User-ID` equals the assessment's `assessor_user_id` may not decide it.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ANONYMOUS,
    ROLE_COMMUNITY_MEMBER,
    ROLE_DATA_COORDINATOR,
    ROLE_PORTAL_ADMIN,
    ROLE_PRIVACY_REVIEWER,
)

# ─── Opaque operator identifiers ──────────────────────────────────────

PORTAL_ADMIN_USER_ID = "portal-admin-1"
PRIVACY_ASSESSOR_USER_ID = "pr-analyst-1"
PRIVACY_DECIDER_USER_ID = "pr-chief-1"

PORTAL_ADMIN_HEADERS = build_user_headers(PORTAL_ADMIN_USER_ID, ROLE_PORTAL_ADMIN)
PRIVACY_ASSESSOR_HEADERS = build_user_headers(PRIVACY_ASSESSOR_USER_ID, ROLE_PRIVACY_REVIEWER)
PRIVACY_DECIDER_HEADERS = build_user_headers(PRIVACY_DECIDER_USER_ID, ROLE_PRIVACY_REVIEWER)

# `Anonymous` is the sole role that requires no `X-User-ID`.
ANONYMOUS_HEADERS: Dict[str, str] = {
    "X-User-Role": ROLE_ANONYMOUS,
    "Content-Type": "application/json",
}


# ─── Per-instance identity builders for entity-backed roles ───────────


def make_data_coordinator_headers(department_id: str) -> Dict[str, str]:
    """Headers for the coordinator acting as the department with `department_id`."""
    return build_user_headers(department_id, ROLE_DATA_COORDINATOR)


def make_community_member_headers(member_id: str) -> Dict[str, str]:
    """Headers for the community member with `member_id`."""
    return build_user_headers(member_id, ROLE_COMMUNITY_MEMBER)


def make_privacy_reviewer_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary privacy reviewer operator identifier."""
    return build_user_headers(user_id, ROLE_PRIVACY_REVIEWER)


def make_portal_admin_headers(user_id: str = PORTAL_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for an arbitrary programme-office operator identifier."""
    return build_user_headers(user_id, ROLE_PORTAL_ADMIN)


TEST_USERS: Dict[str, Dict[str, str]] = {
    "portal_admin_headers": PORTAL_ADMIN_HEADERS,
    "privacy_assessor_headers": PRIVACY_ASSESSOR_HEADERS,
    "privacy_decider_headers": PRIVACY_DECIDER_HEADERS,
    "anonymous_headers": ANONYMOUS_HEADERS,
}
