"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- VenueAdmin, VenueOps, ServiceProvider, GateOperator, TestHarness are
  OPAQUE — X-User-ID is an opaque operator identifier not tied to any
  persisted entity row. The server may record it (for example as
  inspector_id on a SafetyInspection, or as actor_id on an
  AuditLogEntry) but does not compare it to any entity's id. Shared
  TEST_USERS constants are canonical for these roles.

- Exhibitor is ENTITY-BACKED against ExhibitorApplication — PRD §2.1:
  "When X-User-Role is Exhibitor, X-User-ID is the opaque exhibitor
  identifier carried as the exhibitor_id foreign key on
  ExhibitorApplication, BoothAllocation, DockSlot, WorkOrder, and
  SponsorEntitlement. Ownership checks on any of these resources
  compare the resource's exhibitor_id field to X-User-ID." Therefore
  every Exhibitor call whose success depends on owning the targeted
  resource (object an allocation, confirm an allocation, book a dock
  slot, cancel a dock slot, create/submit/dispute/cancel a work order,
  accept a make-good, waive an entitlement, submit/withdraw an
  application) MUST mint headers via
  make_exhibitor_headers(exhibitor_id) — never via the
  EXHIBITOR_FALLBACK_ID shared constant.

  The EXHIBITOR_FALLBACK_ID shared constant below is ONLY safe for
  tests that DO NOT exercise ownership (header-missing, role-mismatch,
  ERR_NOT_FOUND paths, calls by other roles).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — shared constants safe wherever
# the test is NOT exercising ownership matching.
# ---------------------------------------------------------------------------
VENUE_ADMIN_ID = "venue-admin-001"
VENUE_ADMIN_ID_ALT = "venue-admin-002"

VENUE_OPS_ID = "venue-ops-001"
VENUE_OPS_ID_ALT = "venue-ops-002"

SERVICE_PROVIDER_ID = "service-provider-001"
SERVICE_PROVIDER_ID_ALT = "service-provider-002"

GATE_OPERATOR_ID = "gate-operator-001"
GATE_OPERATOR_ID_ALT = "gate-operator-002"

TEST_HARNESS_ID = "test-harness-001"

# Exhibitor fallback — ONLY for tests that do not exercise ownership
# (e.g. header-missing, role-mismatch, ERR_NOT_FOUND paths).
# Ownership-gated calls MUST instead mint headers via
# make_exhibitor_headers(exhibitor_id).
EXHIBITOR_FALLBACK_ID = "fallback-exhibitor-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque operator roles — shared constants are canonical.
    "venue_admin_headers": build_user_headers(VENUE_ADMIN_ID, "VenueAdmin"),
    "venue_admin_headers_alt": build_user_headers(
        VENUE_ADMIN_ID_ALT, "VenueAdmin",
    ),
    "venue_ops_headers": build_user_headers(VENUE_OPS_ID, "VenueOps"),
    "venue_ops_headers_alt": build_user_headers(
        VENUE_OPS_ID_ALT, "VenueOps",
    ),
    "service_provider_headers": build_user_headers(
        SERVICE_PROVIDER_ID, "ServiceProvider",
    ),
    "service_provider_headers_alt": build_user_headers(
        SERVICE_PROVIDER_ID_ALT, "ServiceProvider",
    ),
    "gate_operator_headers": build_user_headers(
        GATE_OPERATOR_ID, "GateOperator",
    ),
    "gate_operator_headers_alt": build_user_headers(
        GATE_OPERATOR_ID_ALT, "GateOperator",
    ),
    "test_harness_headers": build_user_headers(
        TEST_HARNESS_ID, "TestHarness",
    ),
    # Entity-backed Exhibitor fallback — DO NOT use for ownership-gated
    # calls. Use make_exhibitor_headers(exhibitor_id).
    "exhibitor_headers": build_user_headers(
        EXHIBITOR_FALLBACK_ID, "Exhibitor",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for every Exhibitor ownership-gated
# call (PRD §2.1: Exhibitor is entity_backed:ExhibitorApplication).
# ---------------------------------------------------------------------------
def make_exhibitor_headers(exhibitor_id: str) -> Dict[str, str]:
    """For Exhibitor (entity_backed:ExhibitorApplication).

    Pass the opaque exhibitor identifier that will be stored on the
    resource's exhibitor_id field — equal to the X-User-ID supplied
    when the very first ExhibitorApplication was created under that
    identity. Every ownership-gated Exhibitor call (POST
    /allocations/{id}/object, POST /allocations/{id}/confirm, POST
    /exhibitions/{id}/dock-slots, POST /dock-slots/{id}/cancel, POST
    /work-orders, POST /work-orders/{id}/submit, POST
    /work-orders/{id}/dispute, POST /work-orders/{id}/cancel, POST
    /entitlements/{id}/accept-make-good, POST /entitlements/{id}/waive,
    POST /applications/{id}/submit, POST /applications/{id}/withdraw)
    MUST use this builder, not the EXHIBITOR_FALLBACK_ID shared
    constant.
    """
    return build_user_headers(exhibitor_id, "Exhibitor")


def make_venue_admin_headers(actor_id: str) -> Dict[str, str]:
    return build_user_headers(actor_id, "VenueAdmin")


def make_venue_ops_headers(actor_id: str) -> Dict[str, str]:
    return build_user_headers(actor_id, "VenueOps")


def make_gate_operator_headers(actor_id: str) -> Dict[str, str]:
    return build_user_headers(actor_id, "GateOperator")


def make_service_provider_headers(actor_id: str) -> Dict[str, str]:
    return build_user_headers(actor_id, "ServiceProvider")


def make_test_harness_headers(actor_id: str = TEST_HARNESS_ID) -> Dict[str, str]:
    return build_user_headers(actor_id, "TestHarness")


__all__ = [
    "VENUE_ADMIN_ID",
    "VENUE_ADMIN_ID_ALT",
    "VENUE_OPS_ID",
    "VENUE_OPS_ID_ALT",
    "SERVICE_PROVIDER_ID",
    "SERVICE_PROVIDER_ID_ALT",
    "GATE_OPERATOR_ID",
    "GATE_OPERATOR_ID_ALT",
    "TEST_HARNESS_ID",
    "EXHIBITOR_FALLBACK_ID",
    "TEST_USERS",
    "make_exhibitor_headers",
    "make_venue_admin_headers",
    "make_venue_ops_headers",
    "make_gate_operator_headers",
    "make_service_provider_headers",
    "make_test_harness_headers",
]
