"""Pre-built role headers for every role in the PRD.

Roles (PRD 2.1):
  - Owner        : entity-backed by Plan; X-User-ID is the acting owner's Plan.id
  - Deputy       : entity-backed by Deputy; X-User-ID is the acting Deputy.id
  - PlatformAdmin: opaque operator identifier not tied to any persisted entity
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque PlatformAdmin role, and for tests that do
# not exercise ownership (400 bad-payload, 401 missing-auth, 403 unauthorized-role).
TEST_USERS = {
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
    "deputy_headers": build_user_headers("test-deputy-1", "Deputy"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}

# PlatformAdmin is opaque: the shared constant is the canonical form.
ADMIN_HEADERS = TEST_USERS["admin_headers"]


def make_owner_headers(plan_id: str) -> dict:
    """For the Owner role (entity_backed:Plan). Pass the acting owner's Plan.id
    as X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(plan_id, "Owner")


def make_deputy_headers(deputy_id: str) -> dict:
    """For the Deputy role (entity_backed:Deputy). Pass the acting Deputy.id
    as X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(deputy_id, "Deputy")
