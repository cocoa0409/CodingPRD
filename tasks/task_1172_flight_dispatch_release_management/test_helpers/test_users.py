"""Pre-built role headers for the three PRD roles (PRD §2.1).

Dispatcher and Captain identities are entity-backed: ownership checks compare
X-User-ID to the entity's id, so any ownership-gated call MUST use
make_dispatcher_headers(dispatcher_id) / make_captain_headers(captain_id) with
the real entity id. DispatchSupervisor is opaque; its shared constant is the
canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: shared constant is canonical (never entity-compared).
    "supervisor_headers": build_user_headers("test-supervisor-1", "DispatchSupervisor"),
    # Entity-backed roles: shared constants only for tests that never exercise
    # ownership (bad-payload / not-found / role-list rejections).
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "captain_headers": build_user_headers("test-captain-1", "Captain"),
}


def make_dispatcher_headers(dispatcher_id: str) -> dict:
    """Dispatcher is entity-backed: pass the real Dispatcher.id for any
    ownership-gated call (legs, plans, manifests, releases, monitoring)."""
    return build_user_headers(dispatcher_id, "Dispatcher")


def make_captain_headers(captain_id: str) -> dict:
    """Captain is entity-backed: pass the real Captain.id for any
    ownership-gated call (release signing, diversion)."""
    return build_user_headers(captain_id, "Captain")


def make_supervisor_headers(user_id: str = "test-supervisor-1") -> dict:
    """DispatchSupervisor is opaque; any identifier is acceptable."""
    return build_user_headers(user_id, "DispatchSupervisor")
