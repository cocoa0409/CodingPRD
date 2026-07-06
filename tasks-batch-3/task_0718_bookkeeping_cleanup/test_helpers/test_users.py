"""Pre-built role headers for every role in the PRD.

All four roles use an opaque X-User-ID that the server never matches against any
entity id (PRD 2.1). The server does, however, remember the opaque identifier
that categorized an account to enforce segregation of duties on sign-off, so
tests that exercise that rule must control X-User-ID explicitly via the builders.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for every role since X-User-ID is opaque.
TEST_USERS = {
    "engagement_manager_headers": build_user_headers("em-1", "EngagementManager"),
    "bookkeeper_headers": build_user_headers("bk-1", "Bookkeeper"),
    "reviewer_headers": build_user_headers("rv-1", "Reviewer"),
    "tax_preparer_headers": build_user_headers("tp-1", "TaxPreparer"),
}


def make_engagement_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EngagementManager")


def make_bookkeeper_headers(user_id: str) -> dict:
    """For the Bookkeeper role. Pass a controlled X-User-ID when a test needs the
    categorizing identity to be compared by the segregation-of-duties check."""
    return build_user_headers(user_id, "Bookkeeper")


def make_reviewer_headers(user_id: str) -> dict:
    """For the Reviewer role. Pass a controlled X-User-ID when a test needs the
    signing-off identity to differ from (or match) the categorizer."""
    return build_user_headers(user_id, "Reviewer")


def make_tax_preparer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TaxPreparer")
