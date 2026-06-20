"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use an OPAQUE X-User-ID: the PRD states the X-User-ID value is
"an opaque operator identifier that is not tied to any persisted entity ...
never compares it to any entity's id". Access control is governed entirely by
X-User-Role. Therefore shared constants are the canonical form for every role
and no entity-backed per-instance header builders are required.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "herd_manager_headers": build_user_headers("test-herd-manager-1", "HerdManager"),
    "veterinarian_headers": build_user_headers("test-veterinarian-1", "Veterinarian"),
    "sale_clerk_headers": build_user_headers("test-sale-clerk-1", "SaleClerk"),
    "feedlot_operator_headers": build_user_headers(
        "test-feedlot-operator-1", "FeedlotOperator"
    ),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
}
