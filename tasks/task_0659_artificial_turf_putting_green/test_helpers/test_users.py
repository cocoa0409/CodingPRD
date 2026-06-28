"""Pre-built role headers for every role in the PRD (§2.1).

Per PRD §2.1, OpsAdmin, SalesRep, and Scheduler carry opaque X-User-ID
operator identifiers the server records but never compares to any entity id;
the shared constants below are their canonical form. The Customer role is
entity-backed: X-User-ID is the id of the acting Customer, and ownership checks
compare a project's customer_id to X-User-ID. The make_customer_headers builder
threads the real Customer.id whenever a call is ownership-gated (quote accept,
record payment, open/cancel callback, read own project). Falling back to the
shared Customer constant for ownership-gated calls would always fail the
ownership check, so fixtures use the builder.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles use these as their canonical form; the
# entity-backed Customer constant is a fallback for non-ownership tests only.
TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "SalesRep"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual
    Customer.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "Customer")


def make_ops_admin_headers(user_id: str = "test-ops-admin-1") -> dict:
    return build_user_headers(user_id, "OpsAdmin")


def make_sales_rep_headers(user_id: str = "test-sales-rep-1") -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_scheduler_headers(user_id: str = "test-scheduler-1") -> dict:
    return build_user_headers(user_id, "Scheduler")
