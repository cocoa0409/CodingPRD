"""Pre-built role headers for the three roles the PRD recognises (Section 2.1).

``CommunityAdmin`` and ``SecurityOfficer`` treat ``X-User-ID`` as an opaque
operator identifier that the server never compares to any entity id, so the
shared constants below are the canonical form for those roles. ``SecurityOfficer``
is pinned to id ``off-1`` because issued violations record ``issued_by_user_id``
from ``X-User-ID`` and the segregation-of-duties rule compares against it.

``Resident`` is entity-backed: ``X-User-ID`` must be the acting resident's ``id``
and ownership checks compare a resource's ``resident_id`` / ``sponsor_resident_id``
to it. Any resident-role call whose success depends on owning the resource MUST
use ``make_resident_headers(resident_id)`` with the real resident id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque-identity roles — shared constants are the canonical form.
    "community_admin_headers": build_user_headers("admin-test-1", "CommunityAdmin"),
    "security_officer_headers": build_user_headers("off-1", "SecurityOfficer"),
    # Resident fallback — used only for non-ownership tests (forbidden-role or
    # not-found rejections) where the literal X-User-ID need not match a real id.
    "resident_headers": build_user_headers("resident-test-fallback", "Resident"),
}

# Headers with no role — used to exercise the ERR_UNAUTHENTICATED gate.
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_admin_headers(user_id: str) -> dict:
    """CommunityAdmin headers with a specific opaque X-User-ID. Needed to drive
    the segregation-of-duties check, where a resolver whose id equals the
    violation's issued_by_user_id must be refused."""
    return build_user_headers(user_id, "CommunityAdmin")


def make_officer_headers(user_id: str) -> dict:
    """SecurityOfficer headers with a specific opaque X-User-ID (recorded as
    issued_by_user_id when the officer issues a violation)."""
    return build_user_headers(user_id, "SecurityOfficer")


def make_resident_headers(user_id: str) -> dict:
    """For Resident-role calls (entity-backed, PRD Section 2.1): pass the acting
    resident's id so ownership checks pass."""
    return build_user_headers(user_id, "Resident")
