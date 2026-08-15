"""Pre-built role headers for every role in the PRD (§2.1).

`ADMIN` is an opaque role: the server never compares its X-User-ID to any
persisted entity, so the shared constant is canonical. Every other role is
backed by a `SystemUser` record — for those, fixtures MUST build headers from
the actual SystemUser's `id` via the per-role `make_*_headers` builders, both
because reviewer/actor foreign keys must resolve to real records and because
segregation-of-duties checks compare recorded actor ids against X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "ADMIN"),
    # SystemUser-backed roles: fallback constants for tests whose outcome does
    # not depend on the caller owning or referencing the subject resource.
    "regulatory_affairs_headers": build_user_headers("test-ra-1", "REGULATORY_AFFAIRS"),
    "qa_manager_headers": build_user_headers("test-qm-1", "QA_MANAGER"),
    "quality_analyst_headers": build_user_headers("test-qa-1", "QUALITY_ANALYST"),
    "production_supervisor_headers": build_user_headers("test-ps-1", "PRODUCTION_SUPERVISOR"),
    "supply_chain_planner_headers": build_user_headers("test-scp-1", "SUPPLY_CHAIN_PLANNER"),
    "complaint_handler_headers": build_user_headers("test-ch-1", "COMPLAINT_HANDLER"),
}


def make_regulatory_affairs_headers(user_id: str) -> dict:
    """REGULATORY_AFFAIRS headers bound to a real SystemUser id."""
    return build_user_headers(user_id, "REGULATORY_AFFAIRS")


def make_qa_manager_headers(user_id: str) -> dict:
    """QA_MANAGER headers bound to a real SystemUser id."""
    return build_user_headers(user_id, "QA_MANAGER")


def make_quality_analyst_headers(user_id: str) -> dict:
    """QUALITY_ANALYST headers bound to a real SystemUser id."""
    return build_user_headers(user_id, "QUALITY_ANALYST")


def make_production_supervisor_headers(user_id: str) -> dict:
    """PRODUCTION_SUPERVISOR headers bound to a real SystemUser id."""
    return build_user_headers(user_id, "PRODUCTION_SUPERVISOR")


def make_supply_chain_planner_headers(user_id: str) -> dict:
    """SUPPLY_CHAIN_PLANNER headers bound to a real SystemUser id."""
    return build_user_headers(user_id, "SUPPLY_CHAIN_PLANNER")


def make_complaint_handler_headers(user_id: str) -> dict:
    """COMPLAINT_HANDLER headers bound to a real SystemUser id."""
    return build_user_headers(user_id, "COMPLAINT_HANDLER")
