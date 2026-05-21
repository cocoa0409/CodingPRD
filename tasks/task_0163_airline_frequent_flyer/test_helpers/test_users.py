"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- BookingAgent and ProgramAdmin are OPAQUE. PRD §2.1: "When X-User-Role
  is BookingAgent or ProgramAdmin, X-User-ID is an opaque operator
  identifier that is not tied to any persisted entity. The server may
  record it for audit purposes but does not compare it to any entity's
  id." Shared constants are canonical.

- Member is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Member, the
  value of X-User-ID is the id of the acting Member entity. Ownership
  checks on any resource that references a Member compare the
  resource's foreign-key field (for example member_id on FlightSegment,
  AwardBooking, UpgradeRequest, CompanionCertificate, PointsTransaction,
  StatusMatchRequest, or MembershipYear) to the value of X-User-ID. A
  Member who acts on a resource owned by a different member is rejected
  with ERR_OWNERSHIP_MISMATCH."

Falling back to a shared constant for the entity-backed Member role
reproduces the canonical bug: the literal MEMBER_FALLBACK_ID never
equals any real Member.id, so every ownership-gated call would be
rejected as ERR_OWNERSHIP_MISMATCH irrespective of implementation.

The MEMBER_FALLBACK_ID below is ONLY safe for tests that do not
exercise ownership: header-missing/malformed tests, role-not-permitted
tests, and 404-on-non-existent-resource tests. EVERY other Member-role
call must mint headers via make_member_headers(member["id"]).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PROGRAM_ADMIN_ID = "program-admin-001"
PROGRAM_ADMIN_ID_ALT = "program-admin-002"

BOOKING_AGENT_ID = "booking-agent-001"
BOOKING_AGENT_ID_ALT = "booking-agent-002"

# Entity-backed fallback id — DO NOT use for ownership-gated calls.
MEMBER_FALLBACK_ID = "fallback-member-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque ProgramAdmin — shared constant is canonical.
    "program_admin_headers": build_user_headers(
        PROGRAM_ADMIN_ID, "ProgramAdmin",
    ),
    "program_admin_headers_alt": build_user_headers(
        PROGRAM_ADMIN_ID_ALT, "ProgramAdmin",
    ),
    # Opaque BookingAgent — shared constant is canonical.
    "booking_agent_headers": build_user_headers(
        BOOKING_AGENT_ID, "BookingAgent",
    ),
    "booking_agent_headers_alt": build_user_headers(
        BOOKING_AGENT_ID_ALT, "BookingAgent",
    ),
    # Entity-backed Member fallback — DO NOT use for ownership-gated
    # calls.
    "member_fallback_headers": build_user_headers(
        MEMBER_FALLBACK_ID, "Member",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for the entity-backed Member role.
# ---------------------------------------------------------------------------
def make_member_headers(member_id: str) -> Dict[str, str]:
    """For Member (entity_backed:Member). PRD §2.1: "When X-User-Role is
    Member, the value of X-User-ID is the id of the acting Member
    entity. Ownership checks on any resource that references a Member
    compare the resource's foreign-key field ... to the value of
    X-User-ID. A Member who acts on a resource owned by a different
    member is rejected with ERR_OWNERSHIP_MISMATCH."

    Every Member call whose success depends on owning the targeted
    resource (segments, award-bookings, upgrade-requests, certificates,
    status-match-requests, gifts, points-transactions, membership-years)
    MUST use this builder with the real Member.id minted by POST
    /members — NOT the shared MEMBER_FALLBACK_ID.
    """
    return build_user_headers(member_id, "Member")


def make_program_admin_headers(admin_id: str) -> Dict[str, str]:
    """For ProgramAdmin (opaque). Any non-empty operator id is fine."""
    return build_user_headers(admin_id, "ProgramAdmin")


def make_booking_agent_headers(agent_id: str) -> Dict[str, str]:
    """For BookingAgent (opaque). Any non-empty operator id is fine."""
    return build_user_headers(agent_id, "BookingAgent")


__all__ = [
    "BOOKING_AGENT_ID",
    "BOOKING_AGENT_ID_ALT",
    "MEMBER_FALLBACK_ID",
    "PROGRAM_ADMIN_ID",
    "PROGRAM_ADMIN_ID_ALT",
    "TEST_USERS",
    "make_booking_agent_headers",
    "make_member_headers",
    "make_program_admin_headers",
]
