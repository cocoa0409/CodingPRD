"""Pre-built role headers for every role in the PRD (Section 2.1).

Traveler and Approver are entity_backed: their X-User-ID must equal a real
entity id for ownership checks (PRD §2.1). FinanceAdmin is opaque: its
X-User-ID is never compared to any entity id, so the shared constant is the
canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the opaque FinanceAdmin role, and for tests that
# do not exercise ownership (e.g. 401/403/404 on missing/forbidden resources).
TEST_USERS = {
    "finance_admin_headers": build_user_headers("test-finance-admin-1", "FinanceAdmin"),
    # entity_backed fallbacks: ONLY for non-ownership tests (bad payload / unknown role).
    "traveler_headers": build_user_headers("test-traveler-1", "Traveler"),
    "approver_headers": build_user_headers("test-approver-1", "Approver"),
}


def make_finance_admin_headers(user_id: str = "test-finance-admin-1") -> dict:
    """FinanceAdmin (opaque). X-User-ID is an arbitrary operator id (PRD §2.1)."""
    return build_user_headers(user_id, "FinanceAdmin")


def make_traveler_headers(user_id: str) -> dict:
    """For a Traveler (entity_backed:Traveler). Pass the actual Traveler.id as user_id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Traveler")


def make_approver_headers(user_id: str) -> dict:
    """For an Approver (entity_backed:Approver). Pass the actual Approver.id as user_id
    whenever the call is ownership-gated — the approver must be the traveler's manager_id
    or the step's approver_id (PRD §2.1)."""
    return build_user_headers(user_id, "Approver")
