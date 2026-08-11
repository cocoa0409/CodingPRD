"""Pre-built role headers for every role named in PRD 2.1.

`Homeowner`, `HouseholdMember` and `EstateExecutor` carry the acting `Member`'s
id in `X-User-ID`; `Appraiser` carries the acting `Appraiser` row's id.  Those
four roles therefore need per-instance builders — the shared constants below are
only safe for calls whose success does not depend on the caller owning the
subject resource.  `Anonymous`, `InsuranceAgent`, `ClaimsAdjuster` and
`PlatformAdmin` carry opaque identities that are never compared to any row.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque identities — the shared constant is the canonical form.
    "anonymous_headers": build_user_headers("anon-caller-1", "Anonymous"),
    "insurance_agent_headers": build_user_headers("agent-op-1", "InsuranceAgent"),
    "claims_adjuster_headers": build_user_headers("adjuster-op-1", "ClaimsAdjuster"),
    "platform_admin_headers": build_user_headers("admin-op-1", "PlatformAdmin"),
    # Entity-backed identities — fallbacks for non-ownership tests only.
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    "household_member_headers": build_user_headers("test-member-1", "HouseholdMember"),
    "estate_executor_headers": build_user_headers("test-executor-1", "EstateExecutor"),
    "appraiser_headers": build_user_headers("test-appraiser-1", "Appraiser"),
}


def make_homeowner_headers(member_id: str) -> Dict[str, str]:
    """For Homeowner. Pass the acting Member's id."""
    return build_user_headers(member_id, "Homeowner")


def make_household_member_headers(member_id: str) -> Dict[str, str]:
    """For HouseholdMember. Pass the acting Member's id."""
    return build_user_headers(member_id, "HouseholdMember")


def make_estate_executor_headers(member_id: str) -> Dict[str, str]:
    """For EstateExecutor. Pass the acting Member's id."""
    return build_user_headers(member_id, "EstateExecutor")


def make_appraiser_headers(appraiser_id: str) -> Dict[str, str]:
    """For Appraiser. Pass the acting Appraiser row's id."""
    return build_user_headers(appraiser_id, "Appraiser")


def make_anonymous_headers(user_id: str = "anon-caller-1") -> Dict[str, str]:
    return build_user_headers(user_id, "Anonymous")


def make_insurance_agent_headers(user_id: str = "agent-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "InsuranceAgent")


def make_claims_adjuster_headers(user_id: str = "adjuster-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_platform_admin_headers(user_id: str = "admin-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "PlatformAdmin")


# Headers carrying neither X-User-ID nor X-User-Role — used to exercise the
# authentication rung directly.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
