"""Identity headers for the four recognised roles.

``Owner`` and ``Renter`` are entity-backed: the ``X-User-ID`` must equal the
identifier of the Owner or Renter row that owns the resource being touched, so
tests build those headers per-entity with :func:`make_owner_headers` and
:func:`make_renter_headers`. ``PlatformAdmin`` and ``ClaimsAdjuster`` are
opaque operator identities and can use the shared constants.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

TEST_USERS = {
    "owner_headers": build_user_headers("test-owner-1", Role.OWNER),
    "renter_headers": build_user_headers("test-renter-1", Role.RENTER),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", Role.PLATFORM_ADMIN),
    "claims_adjuster_headers": build_user_headers("test-claims-adjuster-1", Role.CLAIMS_ADJUSTER),
}

# Operator identities are opaque, so a module-level constant is enough.
PLATFORM_ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
CLAIMS_ADJUSTER_HEADERS = TEST_USERS["claims_adjuster_headers"]


def make_owner_headers(owner_id: str) -> dict:
    """Headers whose X-User-ID is the given Owner row, for ownership checks."""
    return build_user_headers(owner_id, Role.OWNER)


def make_renter_headers(renter_id: str) -> dict:
    """Headers whose X-User-ID is the given Renter row, for ownership checks."""
    return build_user_headers(renter_id, Role.RENTER)


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, Role.PLATFORM_ADMIN)


def make_claims_adjuster_headers(user_id: str = "test-claims-adjuster-1") -> dict:
    return build_user_headers(user_id, Role.CLAIMS_ADJUSTER)
