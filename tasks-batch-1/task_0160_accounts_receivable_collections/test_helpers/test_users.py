"""Pre-built role headers for every role in the PRD.

All four roles (AR_MANAGER, AR_CLERK, COLLECTIONS_AGENT, AUDITOR) use an opaque
X-User-ID that is never compared to any entity id for ownership (PRD §2.1). The
shared constants below are therefore the canonical form for every test.

The one place X-User-ID identity matters is the segregation-of-duties rule on
write-off approval (PRD §2.8): the approving X-User-ID must differ from the
creating one. The make_*_headers(user_id) builders let a test pin a specific
operator id on each side of that check.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ar_manager_headers": build_user_headers("test-ar-manager-1", "AR_MANAGER"),
    "ar_clerk_headers": build_user_headers("test-ar-clerk-1", "AR_CLERK"),
    "collections_agent_headers": build_user_headers(
        "test-collections-agent-1", "COLLECTIONS_AGENT"
    ),
    "auditor_headers": build_user_headers("test-auditor-1", "AUDITOR"),
}


def make_ar_manager_headers(user_id: str) -> dict:
    """AR_MANAGER headers bound to a specific operator id (for the SoD check)."""
    return build_user_headers(user_id, "AR_MANAGER")


def make_ar_clerk_headers(user_id: str) -> dict:
    """AR_CLERK headers bound to a specific operator id."""
    return build_user_headers(user_id, "AR_CLERK")


def make_collections_agent_headers(user_id: str) -> dict:
    """COLLECTIONS_AGENT headers bound to a specific operator id (for the SoD check)."""
    return build_user_headers(user_id, "COLLECTIONS_AGENT")


def make_auditor_headers(user_id: str) -> dict:
    """AUDITOR headers bound to a specific operator id."""
    return build_user_headers(user_id, "AUDITOR")
