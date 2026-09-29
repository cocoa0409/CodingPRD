"""Role headers.

Two roles are backed by persisted entities, so their ``X-User-ID`` must be the
id of a row created during the test: a ``Member``'s id for the ``Member`` role
and a ``Park``'s id for the ``ParkManager`` role. Those two roles therefore get
per-instance builders and must never be exercised through the shared constants
below on any ownership-gated call.

The two distinct ``ClubAdmin`` identities exist because a decision must be taken
by an operator other than the one who created the thing being decided.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers, not tied to any persisted entity.
CLUB_ADMIN_PRIMARY_ID = "clubadmin-hq-1"
CLUB_ADMIN_SECONDARY_ID = "clubadmin-hq-2"
COMPLIANCE_OFFICER_ID = "compliance-officer-1"
COMPLIANCE_OFFICER_SECONDARY_ID = "compliance-officer-2"
TRANSIENT_GUEST_ID = "transient-guest-1"
TRANSIENT_GUEST_SECONDARY_ID = "transient-guest-2"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "club_admin_headers": build_user_headers(CLUB_ADMIN_PRIMARY_ID, "ClubAdmin"),
    "club_admin_secondary_headers": build_user_headers(
        CLUB_ADMIN_SECONDARY_ID, "ClubAdmin"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_ID, "ComplianceOfficer"
    ),
    "compliance_officer_secondary_headers": build_user_headers(
        COMPLIANCE_OFFICER_SECONDARY_ID, "ComplianceOfficer"
    ),
    "transient_guest_headers": build_user_headers(TRANSIENT_GUEST_ID, "TransientGuest"),
    "transient_guest_secondary_headers": build_user_headers(
        TRANSIENT_GUEST_SECONDARY_ID, "TransientGuest"
    ),
    # Placeholder identities for the two entity-backed roles. These are only
    # valid where the call is not ownership-gated (for example a role-refusal
    # probe); ownership-gated calls must use the builders below.
    "member_headers": build_user_headers("member-placeholder-1", "Member"),
    "park_manager_headers": build_user_headers("park-placeholder-1", "ParkManager"),
}


def make_member_headers(member_id: str) -> Dict[str, str]:
    """Headers for a Member acting as itself: X-User-ID is the Member row's id."""
    return build_user_headers(member_id, "Member")


def make_park_manager_headers(park_id: str) -> Dict[str, str]:
    """Headers for a ParkManager: X-User-ID is the Park row's id."""
    return build_user_headers(park_id, "ParkManager")


def make_club_admin_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary opaque ClubAdmin operator identifier."""
    return build_user_headers(user_id, "ClubAdmin")


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary opaque ComplianceOfficer operator identifier."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_transient_guest_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary opaque public-booking identifier."""
    return build_user_headers(user_id, "TransientGuest")


def headers_without_user_id(role: str = "ClubAdmin") -> Dict[str, str]:
    """Well-formed request headers with X-User-ID deliberately absent."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = CLUB_ADMIN_PRIMARY_ID) -> Dict[str, str]:
    """Well-formed request headers with X-User-Role deliberately absent."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = CLUB_ADMIN_PRIMARY_ID) -> Dict[str, str]:
    """Headers whose X-User-Role holds a string outside the five-value set."""
    return build_user_headers(user_id, "RegionalDirector")
