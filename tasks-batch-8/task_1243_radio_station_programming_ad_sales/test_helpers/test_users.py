"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use the opaque identity model (PRD §2.1: `X-User-ID` is an
opaque operator identifier not tied to any persisted entity), so shared
constants are the canonical form. Per-user builders exist for ownership and
segregation-of-duties scenarios, where a specific operator identity must
create vs submit vs approve vs reconcile vs issue.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "program_director_headers": build_user_headers("pd-1", "ProgramDirector"),
    "traffic_director_headers": build_user_headers("td-1", "TrafficDirector"),
    "sales_rep_headers": build_user_headers("rep-1", "SalesRep"),
    "sales_manager_headers": build_user_headers("mgr-1", "SalesManager"),
    "billing_admin_headers": build_user_headers("ba-1", "BillingAdmin"),
}


def make_program_director_headers(user_id: str) -> dict:
    """ProgramDirector headers for a specific operator id."""
    return build_user_headers(user_id, "ProgramDirector")


def make_traffic_director_headers(user_id: str) -> dict:
    """TrafficDirector headers for a specific operator id (reconciler identity)."""
    return build_user_headers(user_id, "TrafficDirector")


def make_sales_rep_headers(user_id: str) -> dict:
    """SalesRep headers for a specific operator id (order ownership checks)."""
    return build_user_headers(user_id, "SalesRep")


def make_sales_manager_headers(user_id: str) -> dict:
    """SalesManager headers for a specific operator id (approver SoD checks)."""
    return build_user_headers(user_id, "SalesManager")


def make_billing_admin_headers(user_id: str) -> dict:
    """BillingAdmin headers for a specific operator id (affidavit SoD checks)."""
    return build_user_headers(user_id, "BillingAdmin")


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder for any (role, user_id) pair."""
    return build_user_headers(user_id, role)
