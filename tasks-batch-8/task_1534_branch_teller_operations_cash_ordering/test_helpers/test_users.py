"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that never exercise
# ownership gating. The Teller constant is a fallback for non-ownership calls
# only; ownership-gated calls MUST use make_teller_headers(<Teller.id>).
TEST_USERS = {
    "manager_headers": build_user_headers("mgr-1", "BranchManager"),
    "manager2_headers": build_user_headers("mgr-2", "BranchManager"),
    "head_teller_headers": build_user_headers("ht-1", "HeadTeller"),
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
    "teller_headers": build_user_headers("teller-placeholder", "Teller"),
}


def make_teller_headers(user_id: str) -> dict:
    """Teller is entity-backed: X-User-ID must be the acting Teller's id
    whenever the call is ownership-gated (transactions, buy/sell, count,
    teller requests)."""
    return build_user_headers(user_id, "Teller")
