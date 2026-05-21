"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- CrewScheduler and UnionSteward are OPAQUE. PRD §2.1: "When X-User-Role
  is CrewScheduler or UnionSteward, X-User-ID is an opaque operator
  identifier not tied to any persisted entity. The server may record it
  (for example as part of an audit trail) but does not compare it to any
  entity's id." Shared constants are canonical.

- Pilot and FlightAttendant are ENTITY-BACKED. PRD §2.1: "When
  X-User-Role is Pilot or FlightAttendant, X-User-ID is the id of the
  acting CrewMember; ownership checks on any resource that references a
  CrewMember (a Bid, a SickCall, an Assignment, a TradeRequest) compare
  the resource's foreign-key field — crew_member_id, initiator_id, or
  counterparty_id — to X-User-ID."

Falling back to a shared constant for the entity-backed Pilot /
FlightAttendant roles reproduces the canonical bug: a literal string id
never equals any real CrewMember.id, so every ownership-gated call would
be rejected irrespective of implementation correctness.

The FALLBACK ids below are ONLY safe for tests that do not exercise
ownership: header-missing/malformed tests and role-not-permitted tests.
EVERY other Pilot or FlightAttendant call must mint headers via
make_pilot_headers(crew_member["id"]) / make_flight_attendant_headers().
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
CREW_SCHEDULER_ID = "scheduler-001"
CREW_SCHEDULER_ID_ALT = "scheduler-002"

UNION_STEWARD_ID = "steward-001"
UNION_STEWARD_ID_ALT = "steward-002"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
PILOT_FALLBACK_ID = "fallback-pilot-1"
FLIGHT_ATTENDANT_FALLBACK_ID = "fallback-fa-1"

# Default union local id used in fixtures.
DEFAULT_UNION_LOCAL_ID = "L-100"
ALT_UNION_LOCAL_ID = "L-200"


def _steward_headers(operator_id: str, local_id: str) -> Dict[str, str]:
    h = build_user_headers(operator_id, "UnionSteward")
    h["X-Union-Local-Id"] = local_id
    return h


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque CrewScheduler — shared constant is canonical.
    "crew_scheduler_headers": build_user_headers(
        CREW_SCHEDULER_ID, "CrewScheduler",
    ),
    "crew_scheduler_headers_alt": build_user_headers(
        CREW_SCHEDULER_ID_ALT, "CrewScheduler",
    ),
    # Opaque UnionSteward — shared constant is canonical; X-Union-Local-Id
    # supplied separately per PRD §2.1.
    "union_steward_headers": _steward_headers(
        UNION_STEWARD_ID, DEFAULT_UNION_LOCAL_ID,
    ),
    "union_steward_headers_alt": _steward_headers(
        UNION_STEWARD_ID_ALT, ALT_UNION_LOCAL_ID,
    ),
    # Entity-backed Pilot / FA fallbacks — DO NOT use for ownership-gated
    # calls.
    "pilot_fallback_headers": build_user_headers(
        PILOT_FALLBACK_ID, "Pilot",
    ),
    "flight_attendant_fallback_headers": build_user_headers(
        FLIGHT_ATTENDANT_FALLBACK_ID, "FlightAttendant",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Pilot / FlightAttendant
# roles.
# ---------------------------------------------------------------------------
def make_pilot_headers(crew_member_id: str) -> Dict[str, str]:
    """For Pilot (entity_backed:CrewMember). PRD §2.1: "When X-User-Role
    is Pilot or FlightAttendant, X-User-ID is the id of the acting
    CrewMember; ownership checks on any resource that references a
    CrewMember (a Bid, a SickCall, an Assignment, a TradeRequest) compare
    the resource's foreign-key field — crew_member_id, initiator_id, or
    counterparty_id — to X-User-ID."

    Every Pilot call whose success depends on owning the targeted
    resource (bids, sick-calls, trade-requests, assignment reads, etc.)
    MUST use this builder with the real CrewMember.id minted by POST
    /crew-members — NOT the shared PILOT_FALLBACK_ID.
    """
    return build_user_headers(crew_member_id, "Pilot")


def make_flight_attendant_headers(crew_member_id: str) -> Dict[str, str]:
    """For FlightAttendant (entity_backed:CrewMember). Same ownership
    rule as Pilot — pass the actual CrewMember.id whenever an
    ownership-gated call is in flight."""
    return build_user_headers(crew_member_id, "FlightAttendant")


def make_crew_scheduler_headers(operator_id: str) -> Dict[str, str]:
    """For CrewScheduler (opaque). Any non-empty operator id is fine."""
    return build_user_headers(operator_id, "CrewScheduler")


def make_union_steward_headers(operator_id: str,
                                  union_local_id: str = DEFAULT_UNION_LOCAL_ID,
                                  ) -> Dict[str, str]:
    """For UnionSteward (opaque). PRD §2.1: "The UnionSteward role
    additionally identifies its acting union local through an
    X-Union-Local-Id header, used when blessing a cross-local trade."
    """
    h = build_user_headers(operator_id, "UnionSteward")
    h["X-Union-Local-Id"] = union_local_id
    return h


__all__ = [
    "ALT_UNION_LOCAL_ID",
    "CREW_SCHEDULER_ID",
    "CREW_SCHEDULER_ID_ALT",
    "DEFAULT_UNION_LOCAL_ID",
    "FLIGHT_ATTENDANT_FALLBACK_ID",
    "PILOT_FALLBACK_ID",
    "TEST_USERS",
    "UNION_STEWARD_ID",
    "UNION_STEWARD_ID_ALT",
    "make_crew_scheduler_headers",
    "make_flight_attendant_headers",
    "make_pilot_headers",
    "make_union_steward_headers",
]
