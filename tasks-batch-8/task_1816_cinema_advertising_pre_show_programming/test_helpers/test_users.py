"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, listing reads).
# For the entity_backed TheaterOps role, prefer make_theater_ops_headers(theater_id)
# whenever the call is ownership-gated.
TEST_USERS = {
    "network_ops_headers": build_user_headers("no-1", "NetworkOps"),
    "sales_manager_headers": build_user_headers("sm-1", "SalesManager"),
    "sales_manager_2_headers": build_user_headers("sm-2", "SalesManager"),
    "theater_ops_headers": build_user_headers("test-theater-1", "TheaterOps"),
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
    "auditor_2_headers": build_user_headers("aud-2", "Auditor"),
}


def make_network_ops_headers(user_id: str = "no-1") -> dict:
    """NetworkOps is an opaque role; user_id is any operator identifier."""
    return build_user_headers(user_id, "NetworkOps")


def make_sales_manager_headers(user_id: str) -> dict:
    """SalesManager is an opaque role; distinct user ids feed SoD comparisons."""
    return build_user_headers(user_id, "SalesManager")


def make_theater_ops_headers(user_id: str) -> dict:
    """TheaterOps is entity_backed:Theater. Pass the actual Theater.id as user_id
    whenever the call is ownership-gated (acknowledge-delivery, playlogs,
    attendance-reports, resubmit)."""
    return build_user_headers(user_id, "TheaterOps")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor is an opaque role; distinct user ids feed SoD comparisons."""
    return build_user_headers(user_id, "Auditor")
