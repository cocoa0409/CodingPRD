"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (OpsManager, BoxOffice, Actor) whose
# X-User-ID is an opaque operator id never compared to any entity. The "guest"
# shared constant is a fallback for non-ownership tests only (e.g. 401/403/404
# checks); ownership-gated Guest calls MUST use make_guest_headers(guest_id).
TEST_USERS = {
    "ops_headers": build_user_headers("test-ops-1", "OpsManager"),
    "box_office_headers": build_user_headers("test-box-1", "BoxOffice"),
    "actor_headers": build_user_headers("test-actor-1", "Actor"),
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
}


def make_guest_headers(user_id: str) -> dict:
    """For the Guest role (identity entity_backed:Guest). Pass the actual Guest.id
    as user_id whenever the call is ownership-gated (create/confirm/pay/cancel a
    reservation, sign/revoke a waiver, buy a pass, read own guest resources)."""
    return build_user_headers(user_id, "Guest")


def make_ops_headers(user_id: str = "test-ops-1") -> dict:
    """OpsManager is opaque; user_id is not compared to any entity."""
    return build_user_headers(user_id, "OpsManager")


def make_box_office_headers(user_id: str = "test-box-1") -> dict:
    """BoxOffice is opaque; user_id is not compared to any entity."""
    return build_user_headers(user_id, "BoxOffice")


def make_actor_headers(user_id: str = "test-actor-1") -> dict:
    """Actor is opaque; user_id may be recorded as actor_user_id but is not an
    ownership key."""
    return build_user_headers(user_id, "Actor")
