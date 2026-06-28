"""Pre-built role headers for every role in the PRD.

The only entity_backed role is Customer (X-User-ID is the acting Customer's id,
used by project-ownership checks). SalesRep, Scheduler, InstallCrew, and
PlatformAdmin are opaque operator identifiers not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# Customer ownership (e.g. 401/403/404 on bad payload or missing resource).
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles: shared constant is the canonical form.
    "sales_rep_headers": build_user_headers("test-salesrep-1", "SalesRep"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "install_crew_headers": build_user_headers("test-installcrew-1", "InstallCrew"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


# Per-instance builder — required for the entity_backed Customer role.
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (approve/decline/accept/reject/
    financing/warranty on the customer's own project)."""
    return build_user_headers(user_id, "Customer")


def make_sales_rep_headers(user_id: str = "test-salesrep-1") -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_scheduler_headers(user_id: str = "test-scheduler-1") -> dict:
    return build_user_headers(user_id, "Scheduler")


def make_install_crew_headers(user_id: str = "test-installcrew-1") -> dict:
    return build_user_headers(user_id, "InstallCrew")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
