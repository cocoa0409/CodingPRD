"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin and Guest are opaque identities (their X-User-ID is not compared
to any entity id), so their shared constants are the canonical form. FuneralHome
and Operator are entity-backed: their X-User-ID must equal the acting entity's
own id for ownership checks to pass, so use the per-instance builders below with
the real entity id whenever a call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "guest_headers": build_user_headers("guest-visitor-1", "Guest"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests
    # only (e.g. a role-denial 403 that fires before any ownership check).
    "funeral_home_headers": build_user_headers("test-home-1", "FuneralHome"),
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
}


def make_funeral_home_headers(user_id: str) -> dict:
    """For FuneralHome (entity_backed:FuneralHome). Pass the acting FuneralHome.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "FuneralHome")


def make_operator_headers(user_id: str) -> dict:
    """For Operator (entity_backed:Operator). Pass the acting Operator.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Operator")
