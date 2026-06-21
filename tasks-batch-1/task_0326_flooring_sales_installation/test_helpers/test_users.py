"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed: Customer (X-User-ID == Customer.id) and SalesRep
(X-User-ID == SalesRep.id). For ownership-gated calls, use the per-instance
builders below with the real entity id. The remaining roles (Admin, Estimator,
Scheduler) are opaque operator identities; their shared constants are canonical.
Anonymous denotes no auth headers at all (registration endpoints only).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity-backed ownership (e.g. 400/404/forbidden checks).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    # entity_backed fallbacks — only valid for non-ownership tests.
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "SalesRep"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}

# Anonymous: registration endpoints accept no user-context headers at all.
ANONYMOUS_HEADERS: dict = {}


# Per-instance builders — REQUIRED for every entity_backed role on ownership-gated calls.
def make_sales_rep_headers(user_id: str) -> dict:
    """For SalesRep (entity_backed:SalesRep). Pass the actual SalesRep.id."""
    return build_user_headers(user_id, "SalesRep")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id.
    Ownership checks compare X-User-ID to the job's customer_id."""
    return build_user_headers(user_id, "Customer")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "Admin")


def make_estimator_headers(user_id: str = "test-estimator-1") -> dict:
    return build_user_headers(user_id, "Estimator")


def make_scheduler_headers(user_id: str = "test-scheduler-1") -> dict:
    return build_user_headers(user_id, "Scheduler")
