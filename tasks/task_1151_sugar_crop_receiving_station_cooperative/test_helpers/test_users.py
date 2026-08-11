"""Pre-built role headers for every role in the PRD (§2.1).

The MEMBER role is entity-backed: when X-User-Role is MEMBER, X-User-ID must be
the id of the acting Member for ownership-gated calls. Use make_member_headers()
with the real Member.id for any call that exercises ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# member ownership of a specific resource.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "COOP_ADMIN"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "SCHEDULER"),
    "station_operator_headers": build_user_headers("test-operator-1", "STATION_OPERATOR"),
    "quality_tech_headers": build_user_headers("test-quality-1", "QUALITY_TECH"),
    "pool_accountant_headers": build_user_headers("test-accountant-1", "POOL_ACCOUNTANT"),
    # entity-backed role: fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "MEMBER"),
}


def make_member_headers(user_id: str) -> dict:
    """For MEMBER (entity-backed by Member). Pass the actual Member.id whenever
    the call is ownership-gated (booking create/reschedule/cancel, own reads,
    settlement dispute/acknowledge)."""
    return build_user_headers(user_id, "MEMBER")


def make_quality_tech_headers(user_id: str) -> dict:
    """For QUALITY_TECH (opaque identity). The verifier's X-User-ID must differ
    from the recorder's (segregation of duties)."""
    return build_user_headers(user_id, "QUALITY_TECH")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "COOP_ADMIN")


def make_scheduler_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SCHEDULER")


def make_station_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "STATION_OPERATOR")


def make_pool_accountant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "POOL_ACCOUNTANT")
