"""Pre-built identity headers for every role the programme recognises.

``HotelOwner`` and ``Member`` are backed by persisted rows: for those two roles the
acting ``X-User-ID`` must be the id of the property or the member being addressed,
so ownership-gated calls MUST use the per-instance builders below rather than the
shared constants.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the three operator roles, and for the two
# entity-backed roles only in tests that never reach an ownership check.
TEST_USERS = {
    "admin_headers": build_user_headers("op-admin-1", "ProgramAdministrator"),
    "auditor_headers": build_user_headers("op-auditor-1", "ProgramAuditor"),
    "care_agent_headers": build_user_headers("op-care-1", "MemberCareAgent"),
    "hotel_owner_headers": build_user_headers("test-hotel-owner-1", "HotelOwner"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_admin_headers(user_id: str = "op-admin-1") -> dict:
    """ProgramAdministrator. The identifier is opaque, but batch release, approval
    and payment record it, so distinct operators need distinct identifiers."""
    return build_user_headers(user_id, "ProgramAdministrator")


def make_auditor_headers(user_id: str = "op-auditor-1") -> dict:
    """ProgramAuditor - an opaque, read-only assurance identity."""
    return build_user_headers(user_id, "ProgramAuditor")


def make_care_agent_headers(user_id: str = "op-care-1") -> dict:
    """MemberCareAgent - an opaque operator identity never compared to a member."""
    return build_user_headers(user_id, "MemberCareAgent")


def make_hotel_owner_headers(hotel_id: str) -> dict:
    """HotelOwner. Pass the acting property's own id: ownership checks compare a
    resource's property foreign key against this value."""
    return build_user_headers(hotel_id, "HotelOwner")


def make_member_headers(member_id: str) -> dict:
    """Member. Pass the acting member's own id: ownership checks compare a
    resource's member foreign key against this value."""
    return build_user_headers(member_id, "Member")


# Headers that deliberately fail authentication.
NO_IDENTITY_HEADERS = {"Content-Type": "application/json"}


def make_unknown_role_headers(user_id: str = "op-ghost-1", role: str = "SuperAdmin") -> dict:
    """Well-formed headers carrying a role outside the five the programme knows."""
    return build_user_headers(user_id, role)


def make_role_without_user_id_headers(role: str = "ProgramAdministrator") -> dict:
    """A declared role with no acting principal at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
