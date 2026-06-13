"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin is opaque (X-User-ID not tied to any entity) — the shared constant is canonical.
Creator and Backer are entity_backed — ownership-gated calls MUST use the per-instance builders
make_creator_headers(creator_id) / make_backer_headers(backer_id) with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the opaque admin role, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("admin-operator-1", "PlatformAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only
    # (e.g. 403 role-forbidden checks where ownership is never reached).
    "creator_headers": build_user_headers("test-creator-1", "Creator"),
    "backer_headers": build_user_headers("test-backer-1", "Backer"),
}


def make_admin_headers(user_id: str = "admin-operator-1") -> dict:
    """For PlatformAdmin (opaque). Any operator id is accepted; not compared to entity ids."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_creator_headers(user_id: str) -> dict:
    """For Creator (entity_backed:Creator). Pass the actual Creator.id as user_id whenever
    the call is ownership-gated (launch, cancel, create tier/stretch/add-on, ship)."""
    return build_user_headers(user_id, "Creator")


def make_backer_headers(user_id: str) -> dict:
    """For Backer (entity_backed:Backer). Pass the actual Backer.id as user_id whenever the
    call is ownership-gated (pledge cancel, survey completion)."""
    return build_user_headers(user_id, "Backer")
