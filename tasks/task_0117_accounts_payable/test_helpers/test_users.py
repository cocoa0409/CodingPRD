"""Pre-built role headers for every role in the PRD (§2.1).

Every role uses an opaque identity model: X-User-ID is an opaque operator
identifier never compared to any entity id. Shared constants are therefore the
canonical form for ordinary calls. Segregation-of-duties checks compare recorded
operator identifiers (coded_by/approved_by) to the current actor's X-User-ID, so
tests that exercise those checks must control the specific X-User-ID — use the
per-id builders below to do so.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "manager_headers": build_user_headers("mgr-1", "APManager"),
    "clerk_headers": build_user_headers("clerk-1", "APClerk"),
    "approver_headers": build_user_headers("approver-1", "Approver"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
}


def make_manager_headers(user_id: str) -> dict:
    """APManager headers for a specific operator id (segregation-of-duties tests)."""
    return build_user_headers(user_id, "APManager")


def make_clerk_headers(user_id: str) -> dict:
    """APClerk headers for a specific operator id (segregation-of-duties tests)."""
    return build_user_headers(user_id, "APClerk")


def make_approver_headers(user_id: str) -> dict:
    """Approver headers for a specific operator id."""
    return build_user_headers(user_id, "Approver")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor headers for a specific operator id."""
    return build_user_headers(user_id, "Auditor")
