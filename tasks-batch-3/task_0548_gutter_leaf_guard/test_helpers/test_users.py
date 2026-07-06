"""Pre-built role headers for every role in the PRD.

Two access forms are provided:
- TEST_USERS shared constants — for opaque roles, and for tests that do not
  exercise SalesRep resource ownership (e.g. 400/401/403/404 checks).
- make_sales_rep_headers(user_id) — the per-instance builder for the SalesRep
  role, whose identity is the acting rep's own SalesRep id. Ownership-gated
  calls MUST pass the actual rep entity id here so X-User-ID equals the lead's
  sales_rep_id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and non-ownership tests.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    # SalesRep is entity_backed; this shared constant is a fallback only for
    # tests that do not depend on the caller owning the subject lead.
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "SalesRep"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "warranty_agent_headers": build_user_headers("test-warranty-1", "WarrantyAgent"),
}

# A request that carries no X-User-Role header at all (PRD Section 2.1: absent
# role -> ERR_UNAUTHENTICATED). X-User-ID is present but the role is missing.
NO_ROLE_HEADERS = {"X-User-ID": "anon-user"}


def make_sales_rep_headers(user_id: str) -> dict:
    """Headers for the SalesRep role (identity == the acting SalesRep.id).

    Pass the real SalesRep entity id whenever the call is ownership-gated so
    that X-User-ID equals the target lead's sales_rep_id.
    """
    return build_user_headers(user_id, "SalesRep")
