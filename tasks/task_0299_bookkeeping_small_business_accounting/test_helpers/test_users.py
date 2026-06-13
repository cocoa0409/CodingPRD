"""Pre-built role headers for every role in the PRD (§2.1).

All four roles carry an opaque X-User-ID that is not tied to any persisted entity
(PRD §2.1). The one place the recorded id matters is the maker-checker segregation
check on journal-entry posting (PRD §3.4): the posting caller's X-User-ID must
differ from the drafter's. Tests therefore use distinct ids per role, and the
make_*_headers builders let a test pin a specific X-User-ID where the maker-checker
comparison is under test.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical per-role headers (opaque identities).
TEST_USERS = {
    "owner_headers": build_user_headers("u_owner", "Owner"),
    "accountant_headers": build_user_headers("u_acct", "Accountant"),
    "bookkeeper_headers": build_user_headers("u_book", "Bookkeeper"),
    "auditor_headers": build_user_headers("u_aud", "Auditor"),
}


def make_owner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Owner")


def make_accountant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Accountant")


def make_bookkeeper_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Bookkeeper")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")


def make_headers(user_id: str, role: str) -> dict:
    """Generic builder for an arbitrary (possibly unknown) role string."""
    return build_user_headers(user_id, role)
