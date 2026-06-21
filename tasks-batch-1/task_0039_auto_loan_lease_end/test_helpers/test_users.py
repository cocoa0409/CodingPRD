"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (FinanceManager, Auditor) and for
# tests that do not exercise Borrower ownership.
TEST_USERS = {
    # FinanceManager: identity is opaque — X-User-ID never compared to any entity id.
    "finance_manager_headers": build_user_headers("test-fm-1", "FinanceManager"),
    # Auditor: identity is opaque — read-only.
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # Borrower shared fallback — for ownership-independent tests only (e.g. RBAC 403
    # where the call is rejected before ownership is reached). Ownership-gated calls
    # MUST use make_borrower_headers(customer_id) instead.
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
}


def make_finance_manager_headers(user_id: str = "test-fm-1") -> dict:
    """FinanceManager (opaque identity). user_id is recorded but never ownership-checked."""
    return build_user_headers(user_id, "FinanceManager")


def make_auditor_headers(user_id: str = "test-auditor-1") -> dict:
    """Auditor (opaque identity)."""
    return build_user_headers(user_id, "Auditor")


def make_borrower_headers(customer_id: str) -> dict:
    """Borrower (entity_backed:Customer). Pass the acting Customer.id as X-User-ID
    whenever the call is ownership-gated (payments, payoff, lease-end settlements)."""
    return build_user_headers(customer_id, "Borrower")
