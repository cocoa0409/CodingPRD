"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Member is ENTITY-BACKED.
  "When X-User-Role is Member, X-User-ID is the id of the acting
  Member ... any ownership filter ... compares the relevant
  foreign-key field on the target resource ... to X-User-ID."
  Every ownership-gated Member call MUST use
  make_member_headers(member['id']) — passing a shared fallback
  constant guarantees the ownership check fails for every real
  member and cascades 'Setup failed' into every downstream test.

- StationOperator is ENTITY-BACKED on Station.
  "When X-User-Role is StationOperator, X-User-ID is the id of the
  acting Station; operations the operator performs ... are scoped
  to resources whose station_id equals X-User-ID."
  Every operator call routed against a station MUST use
  make_operator_headers(station['id']).

- PlatformAdmin is OPAQUE.
  "When X-User-Role is PlatformAdmin, X-User-ID is an opaque
  operator identifier not tied to any persisted entity."
  Shared constants are canonical for this role.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants — safe for opaque roles, for tests that do NOT exercise
# ownership (missing-auth, wrong-role, missing-resource).
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # PlatformAdmin (opaque) — shared constant is canonical.
    "platform_admin_headers": build_user_headers(
        "platform-admin-001", "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        "platform-admin-002", "PlatformAdmin",
    ),

    # Member fallback — use ONLY for tests that do not exercise ownership.
    # PRD §2.1: real X-User-ID must equal Member.id for ownership-gated
    # calls; use make_member_headers below in fixtures.
    "member_headers": build_user_headers(
        "member-fallback", "Member",
    ),

    # StationOperator fallback — use ONLY for tests that do not exercise
    # ownership (e.g., missing-auth, wrong-role). PRD §2.1: real X-User-ID
    # must equal Station.id; use make_operator_headers below in fixtures.
    "operator_headers": build_user_headers(
        "operator-fallback", "StationOperator",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for every entity_backed role.
# ---------------------------------------------------------------------------
def make_member_headers(member_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Member, X-User-ID is the id of the
    acting Member.' Pass the actual Member.id returned by POST /members
    whenever the downstream call is ownership-gated (create reservation,
    cancel own reservation, pay billing, GET self).
    """
    return build_user_headers(member_id, "Member")


def make_operator_headers(station_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is StationOperator, X-User-ID is the id
    of the acting Station; operations the operator performs ... are scoped
    to resources whose station_id equals X-User-ID.' Pass the actual
    Station.id whenever the downstream call is operator-gated (start/finish
    charging, check-in, inspect, uninstall, install, complete, abort, walk-in,
    report-fault, clear-fault).
    """
    return build_user_headers(station_id, "StationOperator")


def make_admin_headers(actor_id: str) -> Dict[str, str]:
    """PRD §2.1: PlatformAdmin X-User-ID is opaque. Useful when a test
    needs a distinct admin id (e.g., audit_log actor_id comparison).
    """
    return build_user_headers(actor_id, "PlatformAdmin")


__all__ = [
    "TEST_USERS",
    "make_member_headers",
    "make_operator_headers",
    "make_admin_headers",
]
