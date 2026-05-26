"""Pre-built role headers for every role in the PRD.

Owner and Sitter are entity_backed roles — their X-User-ID must equal the actual
entity's id for ownership-gated calls. Use the make_*_headers() builders below
when invoking such calls. The shared constants in TEST_USERS are only safe for
calls whose success does NOT depend on the caller owning the subject resource
(e.g., 400-on-bad-payload, 404-on-missing-resource, or calls by opaque roles).

PlatformAdmin and ClaimsAdjuster have opaque identity; the shared constants are
the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership (e.g., a forbidden-role test, a missing-required-field test).
TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "owner_headers": build_user_headers("test-owner-shared-id", "Owner"),
    "sitter_headers": build_user_headers("test-sitter-shared-id", "Sitter"),
    # opaque roles: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin", "PlatformAdmin"),
    "claims_adjuster_headers": build_user_headers("test-claims-adjuster", "ClaimsAdjuster"),
    # Anonymous role: registration only.
    "anonymous_headers": build_user_headers("test-anonymous", "Anonymous"),
}


# Per-instance builders — REQUIRED for every entity_backed role on ownership-
# gated calls. Pass the actual entity's id as user_id.

def make_owner_headers(owner_id: str) -> dict:
    """For Owner (entity_backed:Owner). Pass the actual Owner.id as owner_id
    whenever the call is ownership-gated (creating a pet for that owner,
    booking on behalf of that owner, etc.)."""
    return build_user_headers(owner_id, "Owner")


def make_sitter_headers(sitter_id: str) -> dict:
    """For Sitter (entity_backed:Sitter). Pass the actual Sitter.id as sitter_id
    whenever the call is ownership-gated (confirming/cancelling/starting/
    completing one's own bookings, posting GPS for one's own booking, etc.)."""
    return build_user_headers(sitter_id, "Sitter")


def make_anonymous_headers() -> dict:
    """For Anonymous registration calls. X-User-ID is opaque; the server does
    not associate it with any persisted entity."""
    return build_user_headers("test-anonymous", "Anonymous")
