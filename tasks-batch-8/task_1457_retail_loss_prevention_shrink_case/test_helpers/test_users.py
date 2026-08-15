"""Pre-built role headers for every role in the PRD (§2.1).

Every role's X-User-ID is an opaque operator identifier, never tied to any
persisted entity's id. Ownership checks compare X-User-ID against recorded
actor fields (created_by, assigned_analyst_id, interviewer_id, ...), so tests
that exercise ownership must thread the SAME user id string through headers
and payload fields — use the make_* builders with the chosen actor id.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_1,
    ANALYST_1,
    ANALYST_2,
    AUDITOR_1,
    HR_PARTNER_1,
    MANAGER_1,
    MANAGER_2,
    POS_FEED_1,
)

# Shared constants — canonical caller identities used across the suite.
TEST_USERS = {
    "analyst_headers": build_user_headers(ANALYST_1, "LPAnalyst"),
    "analyst_2_headers": build_user_headers(ANALYST_2, "LPAnalyst"),
    "manager_headers": build_user_headers(MANAGER_1, "LPManager"),
    "manager_2_headers": build_user_headers(MANAGER_2, "LPManager"),
    "hr_partner_headers": build_user_headers(HR_PARTNER_1, "HRPartner"),
    "admin_headers": build_user_headers(ADMIN_1, "LPAdmin"),
    "auditor_headers": build_user_headers(AUDITOR_1, "Auditor"),
    "pos_feed_headers": build_user_headers(POS_FEED_1, "PosFeed"),
}


def make_analyst_headers(user_id: str) -> dict:
    """LPAnalyst headers for an arbitrary opaque user id (assignee/interviewer)."""
    return build_user_headers(user_id, "LPAnalyst")


def make_manager_headers(user_id: str) -> dict:
    """LPManager headers for an arbitrary opaque user id."""
    return build_user_headers(user_id, "LPManager")


def make_hr_partner_headers(user_id: str) -> dict:
    """HRPartner headers for an arbitrary opaque user id."""
    return build_user_headers(user_id, "HRPartner")


def make_admin_headers(user_id: str) -> dict:
    """LPAdmin headers for an arbitrary opaque user id."""
    return build_user_headers(user_id, "LPAdmin")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor headers for an arbitrary opaque user id."""
    return build_user_headers(user_id, "Auditor")


def make_pos_feed_headers(user_id: str) -> dict:
    """PosFeed headers for an arbitrary opaque user id."""
    return build_user_headers(user_id, "PosFeed")
