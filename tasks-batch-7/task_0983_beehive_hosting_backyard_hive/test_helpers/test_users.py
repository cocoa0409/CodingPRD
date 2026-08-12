"""Pre-built role headers for every role in the PRD (§2.1).

The Host role is entity-backed: when a call is ownership-gated, callers MUST
build headers with the actual Host id via ``make_host_headers``. The shared
``host_headers`` constant is only a fallback for tests that never exercise
ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import BEEKEEPER_1, BEEKEEPER_2, MANAGER_1

TEST_USERS = {
    # Anonymous callers may only self-register as a host.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # Fallback Host identity (entity-backed in reality; safe only for tests
    # that do not exercise ownership checks).
    "host_headers": build_user_headers("test-host-1", "Host"),
    # Opaque operator roles.
    "beekeeper_headers": build_user_headers(BEEKEEPER_1, "Beekeeper"),
    "beekeeper2_headers": build_user_headers(BEEKEEPER_2, "Beekeeper"),
    "manager_headers": build_user_headers(MANAGER_1, "ApiaryManager"),
    "ops_headers": build_user_headers("ops-1", "PlatformOps"),
}


def make_host_headers(user_id: str) -> dict:
    """Host is entity-backed: pass the actual Host.id as user_id whenever the
    call is ownership-gated (sites, agreements, subscriptions, invoices,
    enrollments, removal jobs, swarm reports)."""
    return build_user_headers(user_id, "Host")


def make_beekeeper_headers(user_id: str) -> dict:
    """Beekeeper identity is an opaque operator id."""
    return build_user_headers(user_id, "Beekeeper")


def make_manager_headers(user_id: str) -> dict:
    """ApiaryManager identity is an opaque operator id."""
    return build_user_headers(user_id, "ApiaryManager")


def make_ops_headers(user_id: str) -> dict:
    """PlatformOps identity is an opaque operator id."""
    return build_user_headers(user_id, "PlatformOps")
