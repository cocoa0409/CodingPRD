"""Pre-built role headers for every role in the PRD.

PublisherAdmin, CopyrightSpecialist, RoyaltyAnalyst, FinanceManager and Auditor
are opaque identities: X-User-ID is not tied to any persisted entity. Writer is
entity-backed by Writer (X-User-ID is the acting writer's id); ownership-gated
calls (split-line confirm/reject, own earnings summary) MUST use
make_writer_headers() with the real writer id — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "publisher_admin_headers": build_user_headers("test-admin-1", "PublisherAdmin"),
    "copyright_specialist_headers": build_user_headers("test-copyright-1",
                                                       "CopyrightSpecialist"),
    "royalty_analyst_headers": build_user_headers("test-analyst-1",
                                                  "RoyaltyAnalyst"),
    "finance_manager_headers": build_user_headers("test-finance-1",
                                                  "FinanceManager"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only (e.g. Writer role denied on a PublisherAdmin endpoint).
    "writer_headers": build_user_headers("test-writer-1", "Writer"),
}


def make_publisher_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PublisherAdmin")


def make_copyright_specialist_headers(user_id: str = "test-copyright-1") -> dict:
    return build_user_headers(user_id, "CopyrightSpecialist")


def make_royalty_analyst_headers(user_id: str = "test-analyst-1") -> dict:
    return build_user_headers(user_id, "RoyaltyAnalyst")


def make_finance_manager_headers(user_id: str = "test-finance-1") -> dict:
    return build_user_headers(user_id, "FinanceManager")


def make_auditor_headers(user_id: str = "test-auditor-1") -> dict:
    return build_user_headers(user_id, "Auditor")


def make_writer_headers(writer_id: str) -> dict:
    """For Writer (entity_backed:Writer). Pass the acting Writer.id whenever
    the call is ownership-gated (split-line confirm/reject, earnings summary)."""
    return build_user_headers(writer_id, "Writer")
