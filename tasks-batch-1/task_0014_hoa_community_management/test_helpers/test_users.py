"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
  * Five roles are opaque operator identifiers — PlatformAdmin, BoardPresident,
    BoardSecretary, Treasurer, ACCMember. For these, X-User-ID is opaque and
    the server does not compare it to any entity's id. A shared constant suffices.
  * HomeOwner is entity_backed:Owner. X-User-ID must equal the acting Owner's
    `id`. Ownership-gated owner-action calls (resubmit, withdraw, contest,
    pay-fine, vote, retract) require `make_homeowner_headers(owner_id)`.

The shared `TEST_USERS["home_owner_headers"]` constant is a fallback usable
only when the test deliberately exercises the opaque-id mismatch (e.g.,
ERR_UNAUTHORIZED on an owner-action against a different owner's resource).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS: dict = {
    # Five opaque roles — shared constants are safe for all calls.
    "platform_admin_headers": build_user_headers(
        "test-platform-admin-1", "PlatformAdmin",
    ),
    "board_president_headers": build_user_headers(
        "test-board-president-1", "BoardPresident",
    ),
    "board_secretary_headers": build_user_headers(
        "test-board-secretary-1", "BoardSecretary",
    ),
    "treasurer_headers": build_user_headers(
        "test-treasurer-1", "Treasurer",
    ),
    "acc_member_headers": build_user_headers(
        "test-acc-member-1", "ACCMember",
    ),
    # HomeOwner shared constant — ONLY for non-ownership / negative tests.
    "home_owner_headers": build_user_headers(
        "test-home-owner-1", "HomeOwner",
    ),
}


def make_platform_admin_headers(opaque_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(opaque_id, "PlatformAdmin")


def make_board_president_headers(opaque_id: str = "test-board-president-1") -> dict:
    return build_user_headers(opaque_id, "BoardPresident")


def make_board_secretary_headers(opaque_id: str = "test-board-secretary-1") -> dict:
    return build_user_headers(opaque_id, "BoardSecretary")


def make_treasurer_headers(opaque_id: str = "test-treasurer-1") -> dict:
    return build_user_headers(opaque_id, "Treasurer")


def make_acc_member_headers(opaque_id: str = "test-acc-member-1") -> dict:
    return build_user_headers(opaque_id, "ACCMember")


def make_homeowner_headers(owner_id: str) -> dict:
    """For HomeOwner (entity_backed:Owner). Pass the actual Owner.id as
    user_id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(owner_id, "HomeOwner")
