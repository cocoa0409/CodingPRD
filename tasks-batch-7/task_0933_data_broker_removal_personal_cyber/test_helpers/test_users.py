"""Pre-built role headers for every role in the PRD.

`PlatformAdmin`, `PrivacyAgent` and `Auditor` carry opaque identifiers that the
server never compares to any row's id, so the shared constants below are the
canonical form for them.  `AccountOwner` and `Member` carry the id of a real
member row, so ownership-gated calls MUST use the per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers

ADMIN_USER_ID = "admin-1"
AGENT_ALPHA_ID = "agent-alpha"
AGENT_BETA_ID = "agent-beta"
AUDITOR_USER_ID = "auditor-1"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "privacy_agent_headers": build_user_headers(AGENT_ALPHA_ID, "PrivacyAgent"),
    "privacy_agent_beta_headers": build_user_headers(AGENT_BETA_ID, "PrivacyAgent"),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, "Auditor"),
    # Entity-backed roles — fallback for tests that never reach an ownership
    # check (for example a 401/403 probe or an unknown-role probe).
    "account_owner_headers": build_user_headers("test-owner-1", "AccountOwner"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["privacy_agent_headers"]
AGENT_BETA = TEST_USERS["privacy_agent_beta_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def make_account_owner_headers(member_id: str) -> dict:
    """For AccountOwner. Pass the primary member's actual id."""
    return build_user_headers(member_id, "AccountOwner")


def make_member_headers(member_id: str) -> dict:
    """For Member. Pass the member row's actual id."""
    return build_user_headers(member_id, "Member")


def make_agent_headers(agent_id: str) -> dict:
    """For PrivacyAgent with a chosen opaque operator identifier — used by the
    segregation-of-duties tests, which need two distinct agent identities."""
    return build_user_headers(agent_id, "PrivacyAgent")
