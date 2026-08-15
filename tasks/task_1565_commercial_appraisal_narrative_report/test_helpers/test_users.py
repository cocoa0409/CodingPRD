"""Pre-built role headers for every role in PRD §2.1.

Client, StaffAppraiser, ReviewAppraiser, and MAISigner are entity-backed roles:
their X-User-ID must be the id of the acting Client or Appraiser resource.
Fixtures MUST use the make_* builders with the real entity id for any
ownership-gated call. The shared constants for those roles exist only for
tests that do not exercise ownership (e.g., 400/404 probes).

EngagementManager, RecordsManager, and LegalCounsel are opaque operator roles:
the shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "client_headers": build_user_headers("test-client-1", "Client"),
    "staff_appraiser_headers": build_user_headers("test-author-1", "StaffAppraiser"),
    "review_appraiser_headers": build_user_headers("test-reviewer-1", "ReviewAppraiser"),
    "mai_signer_headers": build_user_headers("test-signer-1", "MAISigner"),
    # Opaque roles — canonical form.
    "engagement_manager_headers": build_user_headers("test-em-1", "EngagementManager"),
    "records_manager_headers": build_user_headers("test-rm-1", "RecordsManager"),
    "legal_counsel_headers": build_user_headers("test-lc-1", "LegalCounsel"),
}


def make_client_headers(user_id: str) -> dict:
    """Client is entity-backed: pass the actual Client.id for ownership-gated calls."""
    return build_user_headers(user_id, "Client")


def make_staff_appraiser_headers(user_id: str) -> dict:
    """StaffAppraiser is entity-backed: pass the author Appraiser.id."""
    return build_user_headers(user_id, "StaffAppraiser")


def make_review_appraiser_headers(user_id: str) -> dict:
    """ReviewAppraiser is entity-backed: pass the reviewer Appraiser.id."""
    return build_user_headers(user_id, "ReviewAppraiser")


def make_mai_signer_headers(user_id: str) -> dict:
    """MAISigner is entity-backed: pass the signing Appraiser.id."""
    return build_user_headers(user_id, "MAISigner")
