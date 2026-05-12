"""Pre-built role headers for every role in the PRD.

PRD §2.1 sorts roles into two identity families:

  - **Opaque** identity: PlatformAdmin, ContentModerator, PaymentGateway.
    X-User-ID is an opaque operator identifier; the server may persist it
    but does not compare it to any entity's id.

  - **Entity-backed** identity: VenueOperator, ScriptAuthor, Host, NPC, Player.
    For VenueOperator, X-User-ID is the id of the acting Venue. For Player,
    X-User-ID is the id of the acting Player. For Host / NPC / ScriptAuthor,
    X-User-ID is the id of an acting StaffMember.

Every entity-backed role MUST be threaded through the per-instance builder
make_<role>_headers(<actual-id>) when the call is ownership-gated. The shared
TEST_USERS constants are only valid for tests that do not exercise ownership
(e.g., 400-on-bad-headers, 404-on-missing-resource, or opaque-role probes).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared canonical constants — safe ONLY for opaque roles or for tests that
# do not exercise ownership. Per PRD §2.1, opaque-role X-User-ID is never
# compared against any entity id.
TEST_USERS: Dict[str, Dict[str, str]] = {
    # ── Opaque roles (canonical form) ──
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "platform_admin_headers_alt": build_user_headers("test-admin-2", "PlatformAdmin"),
    "content_moderator_headers": build_user_headers("test-moderator-1", "ContentModerator"),
    "content_moderator_headers_alt": build_user_headers("test-moderator-2", "ContentModerator"),
    "payment_gateway_headers": build_user_headers("test-gateway-1", "PaymentGateway"),
    # ── Entity-backed fallbacks (only for non-ownership tests, e.g. forbidden-role
    #    probes against an endpoint whose existence checks fire before ownership). ──
    "venue_operator_headers": build_user_headers("test-venue-fallback", "VenueOperator"),
    "script_author_headers": build_user_headers("test-staff-fallback", "ScriptAuthor"),
    "host_headers": build_user_headers("test-host-fallback", "Host"),
    "npc_headers": build_user_headers("test-npc-fallback", "NPC"),
    "player_headers": build_user_headers("test-player-fallback", "Player"),
}


# ─── Per-instance builders ─────────────────────────────────────────────────
# Required for every entity_backed role whenever the call is ownership-gated.
# Pass the actual entity id as user_id so the server's ownership check can
# resolve X-User-ID to the owning row.

def make_platform_admin_headers(operator_id: str = "test-admin-1") -> Dict[str, str]:
    """PlatformAdmin headers (opaque per PRD §2.1)."""
    return build_user_headers(operator_id, "PlatformAdmin")


def make_content_moderator_headers(operator_id: str = "test-moderator-1") -> Dict[str, str]:
    """ContentModerator headers (opaque per PRD §2.1)."""
    return build_user_headers(operator_id, "ContentModerator")


def make_payment_gateway_headers(operator_id: str = "test-gateway-1") -> Dict[str, str]:
    """PaymentGateway headers (opaque per PRD §2.1)."""
    return build_user_headers(operator_id, "PaymentGateway")


def make_venue_operator_headers(venue_id: str) -> Dict[str, str]:
    """VenueOperator headers where X-User-ID == Venue.id (PRD §2.1).

    Pass the actual Venue.id whenever the call is ownership-gated:
    creating rooms / maintenance / slots, cancelling slots, checking-in
    bookings, refunding bookings, creating staff assignments, etc. The
    server resolves the venue from the path's venueId, slot.venue_id, or
    booking.slot.venue_id and rejects with ERR_INSUFFICIENT_PERMISSIONS
    when it does not equal X-User-ID.
    """
    return build_user_headers(venue_id, "VenueOperator")


def make_script_author_headers(staff_member_id: str) -> Dict[str, str]:
    """ScriptAuthor headers where X-User-ID == StaffMember.id (PRD §2.1).

    The acting StaffMember's chain_id must match the targeted theme's chain_id.
    """
    return build_user_headers(staff_member_id, "ScriptAuthor")


def make_host_headers(staff_member_id: str) -> Dict[str, str]:
    """Host headers where X-User-ID == StaffMember.id whose roles_held includes HOST."""
    return build_user_headers(staff_member_id, "Host")


def make_npc_headers(staff_member_id: str) -> Dict[str, str]:
    """NPC headers where X-User-ID == StaffMember.id whose roles_held includes NPC."""
    return build_user_headers(staff_member_id, "NPC")


def make_player_headers(player_id: str) -> Dict[str, str]:
    """Player headers where X-User-ID == Player.id (PRD §2.1).

    Used for booking creation, deposit confirmation, booking cancellation,
    waitlist enqueue/cancel, review submission/revise/resubmit. Ownership
    checks compare the resource's player foreign key (lead_player_id,
    author_player_id, etc.) to X-User-ID.
    """
    return build_user_headers(player_id, "Player")


__all__ = [
    "TEST_USERS",
    "make_platform_admin_headers",
    "make_content_moderator_headers",
    "make_payment_gateway_headers",
    "make_venue_operator_headers",
    "make_script_author_headers",
    "make_host_headers",
    "make_npc_headers",
    "make_player_headers",
]
