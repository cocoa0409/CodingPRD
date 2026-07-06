"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (OfficeAdmin, Caseworker, Anonymous),
# and for Constituent tests that do NOT exercise ownership.
TEST_USERS = {
    "office_admin_headers": build_user_headers("test-admin-1", "OfficeAdmin"),
    "caseworker_headers": build_user_headers("test-caseworker-1", "Caseworker"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Fallback for non-ownership Constituent tests only. Ownership-gated calls
    # MUST use make_constituent_headers(constituent_id) instead.
    "constituent_headers": build_user_headers("test-constituent-1", "Constituent"),
}


def make_constituent_headers(user_id: str) -> dict:
    """For the Constituent role (entity-backed on Constituent). Pass the actual
    Constituent.id as user_id whenever the call is ownership-gated (filing/withdrawing
    a case, constituent-reply, purge, PATCH, event registration create/cancel, own reads)."""
    return build_user_headers(user_id, "Constituent")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
