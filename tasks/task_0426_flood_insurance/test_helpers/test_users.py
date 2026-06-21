"""Pre-built role headers for every role in the PRD.

All four roles are opaque operator identities (PRD §2.1): the server never compares
X-User-ID to any persisted entity's id. The PolicyHolder role is also opaque, but its
X-User-ID carries ownership meaning — it is the identifier recorded as owner_id /
holder_id / claimant_id on the resources that holder creates. There are therefore no
entity_backed roles here: ownership is threaded by passing the SAME opaque X-User-ID at
registration time and at the ownership-gated call. Use make_policy_holder_headers(user_id)
to build a holder identity bound to a specific owner id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise ownership.
TEST_USERS = {
    "policy_holder_headers": build_user_headers("test-holder-1", "PolicyHolder"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "adjuster_headers": build_user_headers("test-adjuster-1", "Adjuster"),
    "fema_admin_headers": build_user_headers("test-fema-admin-1", "FemaAdmin"),
}


def make_policy_holder_headers(user_id: str) -> dict:
    """For PolicyHolder. Pass the opaque X-User-ID that was recorded as the resource's
    owner_id / holder_id / claimant_id so ownership checks (§2.1) pass."""
    return build_user_headers(user_id, "PolicyHolder")


def make_underwriter_headers(user_id: str = "test-underwriter-1") -> dict:
    return build_user_headers(user_id, "Underwriter")


def make_adjuster_headers(user_id: str = "test-adjuster-1") -> dict:
    return build_user_headers(user_id, "Adjuster")


def make_fema_admin_headers(user_id: str = "test-fema-admin-1") -> dict:
    return build_user_headers(user_id, "FemaAdmin")
