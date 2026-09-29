"""Pre-built role headers for every governance role in the PRD.

The governance office operator and the auditor are identified only by their
role, so a shared constant is the canonical form for them. A data owner, a
data steward and a consumer representative are identified by an id that must
equal a real row's id, so ownership-gated calls MUST use the per-instance
builders below with the actual entity id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the two role-only identities, and for tests
# that never exercise an ownership check (bad payloads, unknown path ids).
TEST_USERS: Dict[str, Dict[str, str]] = {
    "governance_admin_headers": build_user_headers(
        "test-governance-admin-1", "GovernanceAdmin"
    ),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # Fallbacks for non-ownership tests only.
    "data_owner_headers": build_user_headers("test-data-owner-1", "DataOwner"),
    "data_steward_headers": build_user_headers("test-data-steward-1", "DataSteward"),
    "consumer_rep_headers": build_user_headers("test-consumer-rep-1", "ConsumerRep"),
}

GOVERNANCE_ADMIN_HEADERS = TEST_USERS["governance_admin_headers"]
AUDITOR_HEADERS = TEST_USERS["auditor_headers"]


def make_data_owner_headers(steward_id: str) -> Dict[str, str]:
    """Headers for a data owner. Pass the accountable steward's id."""
    return build_user_headers(steward_id, "DataOwner")


def make_data_steward_headers(steward_id: str) -> Dict[str, str]:
    """Headers for a data steward. Pass the acting steward's id."""
    return build_user_headers(steward_id, "DataSteward")


def make_consumer_rep_headers(subscription_id: str) -> Dict[str, str]:
    """Headers for a consumer representative. Pass the subscription's id."""
    return build_user_headers(subscription_id, "ConsumerRep")


def make_governance_admin_headers(user_id: str = "test-governance-admin-1") -> Dict[str, str]:
    return build_user_headers(user_id, "GovernanceAdmin")


def make_auditor_headers(user_id: str = "test-auditor-1") -> Dict[str, str]:
    return build_user_headers(user_id, "Auditor")


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying only the role, with no acting identity."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = "test-user-1") -> Dict[str, str]:
    """Headers carrying only an identity, with no role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
