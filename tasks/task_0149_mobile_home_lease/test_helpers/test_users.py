"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "ParkManager — When X-User-Role is ParkManager, X-User-ID is the
    id of the acting Park; ownership checks on any resource that
    references a Park (a Lot, a Home, or any descendant of those)
    compare the resource's park_id to X-User-ID."

    "Resident — When X-User-Role is Resident, X-User-ID is the id of
    the acting Resident; ownership checks on any resource that
    references a Resident compare the resource's resident_id (for a
    Lease) or owner_resident_id (for a Home) to X-User-ID."

    "PlatformAdmin — When X-User-Role is PlatformAdmin, X-User-ID is
    an opaque operator identifier not tied to any persisted entity."

The shared *_headers constants below are appropriate ONLY for tests
whose success does not depend on the caller owning the subject
resource — auth probes, role-forbidden probes, 404 probes — or for
PlatformAdmin calls (which is opaque by spec).

The mandatory builders are make_<role>_headers(entity_id). Fixtures
that create a Park or a Resident and then act as that principal MUST
mint headers with the actual entity id rather than reusing the shared
constant — otherwise the server's ownership check (Lot.park_id,
Lease.resident_id, Home.owner_resident_id == X-User-ID) would reject
the call.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Bootstrap identifiers — used for negative/auth probes that don't need
# a real entity, and for PlatformAdmin which is opaque per PRD §2.1.
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_ID: str = "platform-admin-bootstrap-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # ParkManager and Resident are entity-backed; these shared constants
    # are intended ONLY for non-ownership tests (auth probes, role-
    # forbidden probes, 404 probes that don't depend on ownership).
    "park_manager_headers": build_user_headers(
        "park-manager-shared-0001", "ParkManager",
    ),
    "resident_headers": build_user_headers(
        "resident-shared-0001", "Resident",
    ),
    # PlatformAdmin is opaque — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_ID, "PlatformAdmin",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for entity_backed roles whenever the
# downstream call is ownership-gated.
#
# PRD §2.1: ParkManager X-User-ID = Park.id; Resident X-User-ID = Resident.id.
# ---------------------------------------------------------------------------
def make_park_manager_headers(park_id: str) -> Dict[str, str]:
    """Headers for a ParkManager identified by a real Park.id.

    PRD §2.1: 'A ParkManager may only act on lots, leases, notices,
    evictions, transfers, and conversions whose park_id matches the
    header.'

    Use this whenever the call is gated on the resource's park_id
    matching the acting principal — i.e., essentially every
    ParkManager-exclusive mutation.
    """
    return build_user_headers(park_id, "ParkManager")


def make_resident_headers(resident_id: str) -> Dict[str, str]:
    """Headers for a Resident identified by a real Resident.id.

    PRD §2.1: 'Resident-only mutations (paying a lease, curing an
    eviction, accepting or rejecting a conversion offer) additionally
    require the acting Resident to match the resource owner.'
    """
    return build_user_headers(resident_id, "Resident")


def make_platform_admin_headers(operator_id: str = PLATFORM_ADMIN_ID) -> Dict[str, str]:
    """Headers for a PlatformAdmin.

    PRD §2.1: 'X-User-ID is an opaque operator identifier not tied
    to any persisted entity.'
    """
    return build_user_headers(operator_id, "PlatformAdmin")


__all__ = [
    "PLATFORM_ADMIN_ID",
    "TEST_USERS",
    "make_park_manager_headers",
    "make_resident_headers",
    "make_platform_admin_headers",
]
