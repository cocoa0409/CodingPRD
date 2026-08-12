"""Pre-built role headers for every role in the PRD (section 2.1).

Shared constants are safe for opaque roles (EventOrganizer, AuthenticityOfficer,
SafetyOfficer, Spectator) and for tests that never exercise entity-backed
ownership. For entity-backed roles (UnitCommander -> Unit, Participant ->
Participant, Vendor -> Vendor), ownership-gated calls MUST use the
per-instance builders below with the actual entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "organizer_headers": build_user_headers("test-organizer-1", "EventOrganizer"),
    "authenticity_officer_headers": build_user_headers("test-ao-1", "AuthenticityOfficer"),
    "safety_officer_headers": build_user_headers("so-1", "SafetyOfficer"),
    "spectator_headers": build_user_headers("spec-1", "Spectator"),
    # Fallbacks for entity-backed roles; only for calls that are not
    # ownership-gated (e.g. bootstrap creation calls).
    "unit_commander_headers": build_user_headers("test-uc-1", "UnitCommander"),
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
}


def make_organizer_headers(user_id: str = "test-organizer-1") -> dict:
    """EventOrganizer is an opaque role; any identifier works."""
    return build_user_headers(user_id, "EventOrganizer")


def make_authenticity_officer_headers(user_id: str = "test-ao-1") -> dict:
    """AuthenticityOfficer is an opaque role; any identifier works."""
    return build_user_headers(user_id, "AuthenticityOfficer")


def make_safety_officer_headers(user_id: str) -> dict:
    """SafetyOfficer is an opaque role. Pass distinct ids (so-1, so-2) when a
    test exercises segregation of duties on inspection waivers."""
    return build_user_headers(user_id, "SafetyOfficer")


def make_spectator_headers(user_id: str) -> dict:
    """Spectator is an opaque buyer id, stored as buyer_user_id on orders.
    Pass the same id that created the order for ownership-gated calls."""
    return build_user_headers(user_id, "Spectator")


def make_unit_commander_headers(user_id: str) -> dict:
    """UnitCommander is entity-backed by Unit. After unit creation, pass the
    actual unit's id so ownership checks (own unit / its participants /
    their equipment) succeed."""
    return build_user_headers(user_id, "UnitCommander")


def make_participant_headers(user_id: str) -> dict:
    """Participant is entity-backed by Participant. Pass the actual
    participant's id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Participant")


def make_vendor_headers(user_id: str) -> dict:
    """Vendor is entity-backed through owner_user_id. Pass the value recorded
    as owner_user_id at application time (the vendor's own id when the
    application omitted X-User-ID)."""
    return build_user_headers(user_id, "Vendor")


def role_only_headers(role: str) -> dict:
    """Headers carrying only X-User-Role (no X-User-ID), for bootstrap
    creation calls whose identity is self-anchored by the server."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
