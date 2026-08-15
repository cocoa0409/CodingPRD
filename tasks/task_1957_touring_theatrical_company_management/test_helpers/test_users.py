"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are opaque identifiers: the server never compares X-User-ID to
an entity id. Distinct user ids per call are still required wherever the
segregation-of-duties checks compare recorded audit fields (§2.11), so each
role also has a per-user builder.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "producer_headers": build_user_headers("prod-1", "Producer"),
    "tour_manager_headers": build_user_headers("tm-1", "TourManager"),
    "company_manager_headers": build_user_headers("cm-1", "CompanyManager"),
    "treasurer_headers": build_user_headers("trs-1", "Treasurer"),
}


def make_producer_headers(user_id: str) -> dict:
    """Producer headers for a specific X-User-ID (settlement custody chain)."""
    return build_user_headers(user_id, "Producer")


def make_tour_manager_headers(user_id: str) -> dict:
    """TourManager headers for a specific X-User-ID."""
    return build_user_headers(user_id, "TourManager")


def make_company_manager_headers(user_id: str) -> dict:
    """CompanyManager headers for a specific X-User-ID."""
    return build_user_headers(user_id, "CompanyManager")


def make_treasurer_headers(user_id: str) -> dict:
    """Treasurer headers for a specific X-User-ID (settlement custody chain)."""
    return build_user_headers(user_id, "Treasurer")
