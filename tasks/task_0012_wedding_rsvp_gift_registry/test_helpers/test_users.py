"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
  - `Couple` identity is opaque: `X-User-ID` is treated as `couple_user_id`.
    Tests must pass the same string as the wedding's `couple_user_id` when an
    ownership check applies — use `make_couple_headers(couple_user_id)`.
  - `GuestSelf` identity is entity-backed by `Guest`: `X-User-ID` must equal
    the acting Guest's `id`, and `X-Invitation-Token` must match
    `Guest.invitation_token`. Use `make_guest_self_headers(guest_id, token)`.
  - `PlatformIntegration` identity is opaque.
  - `PlatformAdmin` identity is opaque.

Shared constants under `TEST_USERS` are safe only for tests where the call is
not ownership-gated; for ownership-gated paths use the per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests not exercising ownership.
TEST_USERS = {
    # Couple identity is opaque-but-matched-to-couple_user_id; the shared constant
    # is only useful for negative tests (ERR_FORBIDDEN / cross-couple) or when
    # the test itself constructs a wedding with this same string as
    # couple_user_id.
    "couple_headers": build_user_headers("test-couple-shared", "Couple"),
    "platform_integration_headers": build_user_headers(
        "test-platform-integration-1", "PlatformIntegration",
    ),
    "platform_admin_headers": build_user_headers(
        "test-platform-admin-1", "PlatformAdmin",
    ),
}


def make_couple_headers(couple_user_id: str) -> dict:
    """For Couple role; `X-User-ID` must equal the wedding's `couple_user_id`
    for ownership-gated writes. Pass the same string used when creating the
    wedding."""
    return build_user_headers(couple_user_id, "Couple")


def make_guest_self_headers(guest_id: str, invitation_token: str) -> dict:
    """For GuestSelf role (entity_backed:Guest). Pass the actual Guest.id as
    user_id and the server-minted invitation_token. The framework's
    build_user_headers accepts an optional invitation_token argument."""
    headers = build_user_headers(guest_id, "GuestSelf")
    headers["X-Invitation-Token"] = invitation_token
    return headers


def make_platform_integration_headers(opaque_id: str = "test-platform-integration-1") -> dict:
    """For PlatformIntegration role (identity: opaque)."""
    return build_user_headers(opaque_id, "PlatformIntegration")


def make_platform_admin_headers(opaque_id: str = "test-platform-admin-1") -> dict:
    """For PlatformAdmin role (identity: opaque)."""
    return build_user_headers(opaque_id, "PlatformAdmin")
