"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PlatformAdmin and DisputeOps are OPAQUE. PRD §2.1: "When X-User-Role
  is PlatformAdmin, X-User-ID is an opaque operator identifier that is
  not tied to any persisted entity. The platform may log it for audit
  but does not compare it to any entity's id. When X-User-Role is
  DisputeOps, X-User-ID is likewise an opaque operator identifier not
  tied to any persisted entity; the platform records it for
  dispute-resolution audit but performs no entity ownership comparison."
  Shared constants are canonical.

- Rider is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Rider, X-User-ID
  is the id of the acting Rider entity; ownership checks on a ride
  compare the resource's rider_id field to X-User-ID, and ownership
  checks on a dispute compare the dispute's rider_id field to X-User-ID."

- Driver is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Driver,
  X-User-ID is the id of the acting Driver entity; ownership checks on
  driver-only endpoints compare the path's driver id to X-User-ID, and
  ownership checks on a ride compare the resource's driver_id field to
  X-User-ID."

Falling back to a shared constant for the entity-backed Rider or Driver
roles reproduces the canonical bug: the literal RIDER_FALLBACK_ID /
DRIVER_FALLBACK_ID never equals any real entity's id, so every
ownership-gated call would be rejected as ERR_NOT_OWNER irrespective of
implementation.

The fallback constants below are ONLY safe for tests that do not
exercise ownership: header-missing/malformed tests, role-not-permitted
tests, and 404-on-non-existent-resource tests. EVERY other entity-backed
call must mint headers via make_rider_headers(rider["id"]) or
make_driver_headers(driver["id"]).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_ID = "platform-admin-001"
PLATFORM_ADMIN_ID_ALT = "platform-admin-002"

DISPUTE_OPS_ID = "dispute-ops-001"
DISPUTE_OPS_ID_ALT = "dispute-ops-002"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
RIDER_FALLBACK_ID = "fallback-rider-1"
DRIVER_FALLBACK_ID = "fallback-driver-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque PlatformAdmin — shared constant is canonical.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_ID, "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        PLATFORM_ADMIN_ID_ALT, "PlatformAdmin",
    ),
    # Opaque DisputeOps — shared constant is canonical.
    "dispute_ops_headers": build_user_headers(
        DISPUTE_OPS_ID, "DisputeOps",
    ),
    "dispute_ops_headers_alt": build_user_headers(
        DISPUTE_OPS_ID_ALT, "DisputeOps",
    ),
    # Entity-backed fallbacks — DO NOT use for ownership-gated calls.
    "rider_fallback_headers": build_user_headers(
        RIDER_FALLBACK_ID, "Rider",
    ),
    "driver_fallback_headers": build_user_headers(
        DRIVER_FALLBACK_ID, "Driver",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Rider and Driver roles.
# ---------------------------------------------------------------------------
def make_rider_headers(rider_id: str) -> Dict[str, str]:
    """For Rider (entity_backed:Rider). PRD §2.1: "When X-User-Role is
    Rider, X-User-ID is the id of the acting Rider entity; ownership
    checks on a ride compare the resource's rider_id field to X-User-ID,
    and ownership checks on a dispute compare the dispute's rider_id
    field to X-User-ID."

    Every Rider call whose success depends on owning the targeted
    resource (POST /rides, POST /rides/{id}/cancel, POST /disputes,
    GET /disputes/{id} when restricted to own disputes) MUST use this
    builder with the real Rider.id minted by POST /riders — NOT the
    shared RIDER_FALLBACK_ID.
    """
    return build_user_headers(rider_id, "Rider")


def make_driver_headers(driver_id: str) -> Dict[str, str]:
    """For Driver (entity_backed:Driver). PRD §2.1: "When X-User-Role is
    Driver, X-User-ID is the id of the acting Driver entity; ownership
    checks on driver-only endpoints compare the path's driver id to
    X-User-ID, and ownership checks on a ride compare the resource's
    driver_id field to X-User-ID."

    Every Driver call whose success depends on owning the targeted
    resource (POST /rides/{id}/start, /complete; POST /drivers/{id}/*;
    POST /airport-queue/*; PATCH /drivers/{id}/quest) MUST use this
    builder with the real Driver.id minted by POST /drivers — NOT the
    shared DRIVER_FALLBACK_ID.
    """
    return build_user_headers(driver_id, "Driver")


def make_platform_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlatformAdmin (opaque). Any non-empty operator id is fine."""
    return build_user_headers(admin_id, "PlatformAdmin")


def make_dispute_ops_headers(ops_id: str) -> Dict[str, str]:
    """For DisputeOps (opaque). Any non-empty operator id is fine."""
    return build_user_headers(ops_id, "DisputeOps")


__all__ = [
    "DISPUTE_OPS_ID",
    "DISPUTE_OPS_ID_ALT",
    "DRIVER_FALLBACK_ID",
    "PLATFORM_ADMIN_ID",
    "PLATFORM_ADMIN_ID_ALT",
    "RIDER_FALLBACK_ID",
    "TEST_USERS",
    "make_dispute_ops_headers",
    "make_driver_headers",
    "make_platform_admin_headers",
    "make_rider_headers",
]
