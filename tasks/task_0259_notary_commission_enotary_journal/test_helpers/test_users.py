"""Pre-built role headers for every role in the PRD.

Three roles exist: CommissionAuthority (opaque operator id), Notary
(X-User-ID is the acting Notary.id — entity_backed), and Anonymous (opaque,
used only for self-registration). Ownership-gated Notary calls MUST use
make_notary_headers(notary_id) with the real notary id, never the shared
constant; otherwise X-User-ID never equals any real notary id and every
ownership check rejects the request.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# notary ownership (e.g. CommissionAuthority operations, Anonymous registration).
TEST_USERS = {
    "commission_authority_headers": build_user_headers("auditor-shared", "CommissionAuthority"),
    "notary_headers": build_user_headers("test-notary-shared", "Notary"),
    "anonymous_headers": build_user_headers("applicant-shared", "Anonymous"),
}


def make_commission_authority_headers(user_id: str = "auditor-shared") -> dict:
    """CommissionAuthority headers with a chosen opaque operator id.

    Used for segregation-of-duties tests where the acting operator id must equal
    (or differ from) a specific notary's id.
    """
    return build_user_headers(user_id, "CommissionAuthority")


def make_notary_headers(notary_id: str) -> dict:
    """Headers for the Notary role. Pass the actual Notary.id as user_id for any
    ownership-gated call (sessions, documents, journal entries)."""
    return build_user_headers(notary_id, "Notary")


def make_anonymous_headers(user_id: str = "applicant-shared") -> dict:
    """Anonymous applicant headers (notary self-registration only)."""
    return build_user_headers(user_id, "Anonymous")
