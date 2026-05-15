"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Housekeeper is ENTITY-BACKED.
  "When X-User-Role is Housekeeper, X-User-ID is the id of the acting
  Housekeeper entity; ownership checks on any resource that references a
  Housekeeper (in particular, CleaningTask.assigned_housekeeper_id for
  accept, start, and submit, and Housekeeper.id itself for a self-toggle
  of shift status) compare the resource's foreign-key field to
  X-User-ID."

  Every ownership-gated Housekeeper call MUST use
  make_housekeeper_headers(housekeeper['id']) — passing a shared
  fallback constant guarantees the ownership check fails for every
  real housekeeper and cascades "Setup failed" into every downstream
  test.

- Supervisor, FrontDesk, Engineer, SystemIntegration are OPAQUE.
  "When X-User-Role is Supervisor, X-User-ID is an opaque operator
  identifier not tied to any persisted entity ... The same applies to
  FrontDesk ... Engineer is also opaque ... SystemIntegration is
  likewise opaque." Shared constants are canonical for these four
  roles.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and a non-binding Housekeeper fallback.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Supervisor (opaque) — multiple alts for concurrency-style tests
    # where two distinct supervisor X-User-IDs must drive simultaneous
    # operations on the same resource.
    "supervisor_headers": build_user_headers(
        "supervisor-001", "Supervisor",
    ),
    "supervisor_headers_alt": build_user_headers(
        "supervisor-002", "Supervisor",
    ),
    "supervisor_headers_alt2": build_user_headers(
        "supervisor-003", "Supervisor",
    ),

    # FrontDesk (opaque)
    "frontdesk_headers": build_user_headers(
        "frontdesk-001", "FrontDesk",
    ),
    "frontdesk_headers_alt": build_user_headers(
        "frontdesk-002", "FrontDesk",
    ),

    # Engineer (opaque, primarily read-only)
    "engineer_headers": build_user_headers(
        "engineer-001", "Engineer",
    ),

    # SystemIntegration (opaque) — inbound-event channel for PMS,
    # engineering, laundry, and the test clock.
    "system_integration_headers": build_user_headers(
        "system-integration-001", "SystemIntegration",
    ),

    # Housekeeper fallback — use ONLY for tests that do not exercise
    # ownership (missing-auth, wrong-role, missing-resource).
    # PRD §2.1: a real Housekeeper X-User-ID must equal the
    # Housekeeper.id minted by POST /housekeepers; this constant matches
    # no real housekeeper, so any ownership-gated call with it must fail.
    "housekeeper_headers": build_user_headers(
        "housekeeper-fallback", "Housekeeper",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — REQUIRED for the entity_backed Housekeeper role.
# ---------------------------------------------------------------------------
def make_housekeeper_headers(housekeeper_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Housekeeper, X-User-ID is the id
    of the acting Housekeeper entity'. Pass the actual Housekeeper.id
    returned by POST /housekeepers whenever the downstream call is
    ownership-gated (accept, start, submit, self-shift-toggle)."""
    return build_user_headers(housekeeper_id, "Housekeeper")


def make_supervisor_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: Supervisor X-User-ID is opaque. Useful when a test
    requires a distinct supervisor id (e.g., concurrency tests in which
    two simultaneous /inspect operations must carry different X-User-IDs
    to make their winner-vs-loser identity observable)."""
    return build_user_headers(user_id, "Supervisor")


def make_frontdesk_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: FrontDesk X-User-ID is opaque."""
    return build_user_headers(user_id, "FrontDesk")


def make_system_integration_headers(user_id: str = "system-integration-001") -> Dict[str, str]:
    """PRD §2.1: SystemIntegration X-User-ID is opaque; the server
    records it as the actor identifier on audit entries created from
    inbound events."""
    return build_user_headers(user_id, "SystemIntegration")


__all__ = [
    "TEST_USERS",
    "make_housekeeper_headers",
    "make_supervisor_headers",
    "make_frontdesk_headers",
    "make_system_integration_headers",
]
