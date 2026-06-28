"""Pre-built role headers for every role in the PRD (§2.1).

Four roles: Client, Tasker (entity_backed), Dispatcher, TrustSafetyOfficer (opaque).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "trust_safety_headers": build_user_headers("tso-1", "TrustSafetyOfficer"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only
    # (e.g. forbidden-role / not-found checks that fail before any ownership compare).
    "client_headers": build_user_headers("client-fallback-1", "Client"),
    "tasker_headers": build_user_headers("tasker-fallback-1", "Tasker"),
}


# Per-instance builders — required for every entity_backed role. Pass the actual
# entity id so ownership checks (PRD §2.1) compare X-User-ID to the resource FK.
def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed). Pass the actual Client.id as X-User-ID
    whenever the call is ownership-gated (booking/series/review actions)."""
    return build_user_headers(client_id, "Client")


def make_tasker_headers(tasker_id: str) -> dict:
    """For Tasker (entity_backed). Pass the actual Tasker.id as X-User-ID
    whenever the call is ownership-gated (depart/start/complete/cancel/chat)."""
    return build_user_headers(tasker_id, "Tasker")


def dispatcher_headers() -> dict:
    return TEST_USERS["dispatcher_headers"]


def trust_safety_headers() -> dict:
    return TEST_USERS["trust_safety_headers"]
