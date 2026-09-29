"""Identity headers for every caller the tests need.

Six of the eight roles carry an opaque operator identifier; the tests pin those
identifiers because the two-person rules compare them across requests.  A
``Candidate`` instead identifies itself with the id of its own talent community
member row, so its header builder takes that id.
"""
from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ------------------------------------------------------- pinned operator identities
BRAND_LEAD_USER_ID = "u-lead-1"
PERSONA_RESEARCHER_USER_ID = "u-res-1"
COMPLIANCE_REVIEWER_USER_ID = "u-comp-1"
#: A second compliance reviewer, needed whenever one reviewer is disqualified.
COMPLIANCE_REVIEWER_ALT_USER_ID = "u-comp-2"
COMMUNITY_MANAGER_USER_ID = "u-cm-1"
RECRUITING_OPS_USER_ID = "u-ops-1"
MEDIA_BUYER_USER_ID = "u-mb-1"
ANONYMOUS_USER_ID = "anon-1"

DEFAULT_USER_IDS = {
    UserRole.BRAND_PROGRAM_LEAD.value: BRAND_LEAD_USER_ID,
    UserRole.PERSONA_RESEARCHER.value: PERSONA_RESEARCHER_USER_ID,
    UserRole.COMPLIANCE_REVIEWER.value: COMPLIANCE_REVIEWER_USER_ID,
    UserRole.MEDIA_BUYER.value: MEDIA_BUYER_USER_ID,
    UserRole.COMMUNITY_MANAGER.value: COMMUNITY_MANAGER_USER_ID,
    UserRole.RECRUITING_OPS.value: RECRUITING_OPS_USER_ID,
    UserRole.ANONYMOUS.value: ANONYMOUS_USER_ID,
}


def headers_for_role(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Identity headers for any role name, including names the API does not know."""
    resolved = user_id or DEFAULT_USER_IDS.get(role, "u-unknown-1")
    return build_user_headers(resolved, role)


def brand_lead_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return headers_for_role(UserRole.BRAND_PROGRAM_LEAD.value, user_id)


def persona_researcher_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return headers_for_role(UserRole.PERSONA_RESEARCHER.value, user_id)


def compliance_reviewer_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return headers_for_role(UserRole.COMPLIANCE_REVIEWER.value, user_id)


def media_buyer_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return headers_for_role(UserRole.MEDIA_BUYER.value, user_id)


def community_manager_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return headers_for_role(UserRole.COMMUNITY_MANAGER.value, user_id)


def recruiting_ops_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return headers_for_role(UserRole.RECRUITING_OPS.value, user_id)


def anonymous_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return headers_for_role(UserRole.ANONYMOUS.value, user_id)


def candidate_headers(member_id: str) -> Dict[str, str]:
    """A candidate is identified by the id of its own talent community member row."""
    return build_user_headers(member_id, UserRole.CANDIDATE.value)


def no_identity_headers() -> Dict[str, str]:
    """Headers with neither role nor user identity, for unauthenticated calls."""
    return {"Content-Type": "application/json"}
