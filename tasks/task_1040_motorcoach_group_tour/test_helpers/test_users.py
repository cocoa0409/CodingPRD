"""Pre-built role headers for every role in the PRD.

All four roles carry an opaque X-User-ID (PRD §2.1): the server never compares
X-User-ID to any persisted entity id, so a shared constant per role is correct
for every call — ownership is never determined by matching identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ops_headers": build_user_headers("ops-user-1", "OpsManager"),
    "sales_headers": build_user_headers("sales-user-1", "SalesAgent"),
    "finance_headers": build_user_headers("finance-user-1", "Finance"),
    "auditor_headers": build_user_headers("auditor-user-1", "Auditor"),
}

# Headers with no authentication at all (negative test for ERR_UNAUTHENTICATED).
NO_AUTH_HEADERS: dict = {}
