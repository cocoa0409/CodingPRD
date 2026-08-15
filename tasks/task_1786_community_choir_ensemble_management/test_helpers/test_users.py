"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Member-role tests that do
# not exercise ownership (e.g. 400-on-bad-payload or 404-on-missing-resource).
TEST_USERS = {
    "president_headers": build_user_headers("pres-1", "President"),
    "treasurer_headers": build_user_headers("treas-1", "Treasurer"),
    "director_headers": build_user_headers("dir-1", "ChoirDirector"),
    "librarian_headers": build_user_headers("lib-1", "Librarian"),
    # Member is entity-backed: this shared constant is a fallback for
    # non-ownership tests only; use make_member_headers(member_id) otherwise.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_president_headers(user_id: str) -> dict:
    """President with a specific operator id (used for segregation-of-duties)."""
    return build_user_headers(user_id, "President")


def make_treasurer_headers(user_id: str) -> dict:
    """Treasurer with a specific operator id (used for segregation-of-duties)."""
    return build_user_headers(user_id, "Treasurer")


def make_director_headers(user_id: str) -> dict:
    """ChoirDirector with a specific operator id."""
    return build_user_headers(user_id, "ChoirDirector")


def make_librarian_headers(user_id: str) -> dict:
    """Librarian with a specific operator id."""
    return build_user_headers(user_id, "Librarian")


def make_member_headers(user_id: str) -> dict:
    """Member is entity-backed: pass the actual Member.id as user_id whenever
    the call is ownership-gated (own record, invoices, payments, grants,
    attendance records, checkouts, registrations, resign)."""
    return build_user_headers(user_id, "Member")
