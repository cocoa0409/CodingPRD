"""Pre-built role headers for every role in the PRD.

PlatformAdmin is an opaque operator id (not tied to any entity), so its shared
constant is the canonical form. AccountOwner and Receptionist are entity-backed:
their X-User-ID must equal the acting entity's id on ownership-gated calls, so
those roles also expose per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests
    # (e.g. 401/403/404 and bad-payload checks) only.
    "account_owner_headers": build_user_headers("test-account-owner-1", "AccountOwner"),
    "receptionist_headers": build_user_headers("test-receptionist-1", "Receptionist"),
}


def make_platform_admin_headers(user_id="test-admin-1") -> dict:
    """For PlatformAdmin (opaque). The id is not compared to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_account_owner_headers(account_id: str) -> dict:
    """For AccountOwner (entity_backed:ClientAccount).

    Pass the actual ClientAccount.id as user_id; ownership-gated calls compare
    the resource's account_id to this X-User-ID.
    """
    return build_user_headers(account_id, "AccountOwner")


def make_receptionist_headers(receptionist_id: str) -> dict:
    """For Receptionist (entity_backed:Receptionist).

    Pass the actual Receptionist.id as user_id; ownership-gated call operations
    compare the call's answered_by_receptionist_id to this X-User-ID.
    """
    return build_user_headers(receptionist_id, "Receptionist")
