"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics (PRD §2.1):
- Trustee / Clerk / Court: X-User-ID is an opaque operator identifier. Trustee-bound
  mutations compare it against the case's stored trustee_user_id, so the shared
  constant below uses the same id our case factory assigns by default.
- Creditor: X-User-ID is the id of the acting Creditor entity — always build
  per-instance headers with make_creditor_headers(creditor["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TRUSTEE_USER_ID = "trust-0001"

TEST_USERS = {
    "trustee_headers": build_user_headers(TRUSTEE_USER_ID, "Trustee"),
    "clerk_headers": build_user_headers("test-clerk-1", "Clerk"),
    "court_headers": build_user_headers("test-court-1", "Court"),
    # Fallback for non-ownership calls only; ownership-gated creditor calls
    # (claim filing as self, withdrawal) MUST use make_creditor_headers().
    "creditor_headers": build_user_headers("test-creditor-1", "Creditor"),
}


def make_trustee_headers(user_id: str = TRUSTEE_USER_ID) -> dict:
    """Trustee headers bound to a specific operator id (the case's trustee_user_id)."""
    return build_user_headers(user_id, "Trustee")


def make_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    return build_user_headers(user_id, "Clerk")


def make_court_headers(user_id: str = "test-court-1") -> dict:
    return build_user_headers(user_id, "Court")


def make_creditor_headers(creditor_id: str) -> dict:
    """Creditor is entity-backed: X-User-ID must be the Creditor's id whenever
    the call is ownership-gated (filing own claim, withdrawing own claim)."""
    return build_user_headers(creditor_id, "Creditor")
