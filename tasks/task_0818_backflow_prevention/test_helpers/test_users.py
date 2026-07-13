"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - UtilityAdmin and PremisesOwner have `opaque` identity: X-User-ID is not compared
#    to any entity id. For PremisesOwner, ownership is enforced by VALUE against the
#    connection's owner_user_id string, so tests pass the same string used at creation.
#  - Tester has `entity_backed:Tester` identity: ownership-gated writes require
#    X-User-ID == Tester.id, so use make_tester_headers(tester["id"]) for those.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "UtilityAdmin"),
    "owner_headers": build_user_headers("owner-1", "PremisesOwner"),
    # Fallback constant only for non-ownership tester tests (e.g. RBAC denials).
    "tester_headers": build_user_headers("tester-shared-1", "Tester"),
}

# Empty headers — no X-User-ID / X-User-Role (anonymous caller -> ERR_UNAUTHENTICATED).
NO_AUTH_HEADERS: dict = {}


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """UtilityAdmin (opaque). X-User-ID is never compared to a record id."""
    return build_user_headers(user_id, "UtilityAdmin")


def make_owner_headers(user_id: str) -> dict:
    """PremisesOwner (opaque, value-ownership). Pass the connection's owner_user_id
    string as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "PremisesOwner")


def make_tester_headers(user_id: str) -> dict:
    """Tester (entity_backed:Tester). Pass the actual Tester.id as user_id whenever
    the call is ownership-gated (book/cancel appointment, submit report)."""
    return build_user_headers(user_id, "Tester")
