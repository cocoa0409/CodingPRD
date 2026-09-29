"""Role header builders.

Every request carries X-User-ID and X-User-Role. Six of the seven roles carry an
opaque operator identifier; the DestinationPlatform role's X-User-ID must be the
id of the destination row the caller is acting as, so its headers are always
built per destination id.
"""

from prd_bench_local_runner.testing import build_user_headers

ROLE_DATA_PLATFORM_ADMIN = "DataPlatformAdmin"
ROLE_DATA_ENGINEER = "DataEngineer"
ROLE_IDENTITY_STEWARD = "IdentitySteward"
ROLE_PRIVACY_OFFICER = "PrivacyOfficer"
ROLE_SEGMENT_ANALYST = "SegmentAnalyst"
ROLE_DATA_GOVERNANCE_OFFICER = "DataGovernanceOfficer"
ROLE_DESTINATION_PLATFORM = "DestinationPlatform"

ALL_ROLES = [
    ROLE_DATA_PLATFORM_ADMIN,
    ROLE_DATA_ENGINEER,
    ROLE_IDENTITY_STEWARD,
    ROLE_PRIVACY_OFFICER,
    ROLE_SEGMENT_ANALYST,
    ROLE_DATA_GOVERNANCE_OFFICER,
    ROLE_DESTINATION_PLATFORM,
]

# Opaque operator identifiers.
ADMIN_USER_ID = "u_admin"
ENGINEER_USER_ID = "u_eng"
STEWARD_USER_ID = "u_steward"
STEWARD_2_USER_ID = "u_steward_2"
PRIVACY_USER_ID = "u_privacy"
PRIVACY_2_USER_ID = "u_privacy_2"
ANALYST_USER_ID = "u_analyst"
ANALYST_2_USER_ID = "u_analyst_2"
GOVERNANCE_USER_ID = "u_gov"
GOVERNANCE_2_USER_ID = "u_gov_2"

ADMIN = build_user_headers(ADMIN_USER_ID, ROLE_DATA_PLATFORM_ADMIN)
ENGINEER = build_user_headers(ENGINEER_USER_ID, ROLE_DATA_ENGINEER)
STEWARD = build_user_headers(STEWARD_USER_ID, ROLE_IDENTITY_STEWARD)
STEWARD_2 = build_user_headers(STEWARD_2_USER_ID, ROLE_IDENTITY_STEWARD)
PRIVACY = build_user_headers(PRIVACY_USER_ID, ROLE_PRIVACY_OFFICER)
PRIVACY_2 = build_user_headers(PRIVACY_2_USER_ID, ROLE_PRIVACY_OFFICER)
ANALYST = build_user_headers(ANALYST_USER_ID, ROLE_SEGMENT_ANALYST)
ANALYST_2 = build_user_headers(ANALYST_2_USER_ID, ROLE_SEGMENT_ANALYST)
GOVERNANCE = build_user_headers(GOVERNANCE_USER_ID, ROLE_DATA_GOVERNANCE_OFFICER)
GOVERNANCE_2 = build_user_headers(GOVERNANCE_2_USER_ID, ROLE_DATA_GOVERNANCE_OFFICER)

# Role -> a ready-made header dict, for role-matrix sweeps. DestinationPlatform is
# deliberately absent because its X-User-ID is data-dependent.
HEADERS_BY_ROLE = {
    ROLE_DATA_PLATFORM_ADMIN: ADMIN,
    ROLE_DATA_ENGINEER: ENGINEER,
    ROLE_IDENTITY_STEWARD: STEWARD,
    ROLE_PRIVACY_OFFICER: PRIVACY,
    ROLE_SEGMENT_ANALYST: ANALYST,
    ROLE_DATA_GOVERNANCE_OFFICER: GOVERNANCE,
}

OPAQUE_ROLES = list(HEADERS_BY_ROLE.keys())


def make_destination_platform_headers(destination_id: str) -> dict:
    """Headers for the destination-backed role, whose X-User-ID is the destination id."""
    return build_user_headers(destination_id, ROLE_DESTINATION_PLATFORM)


def make_headers(user_id: str, role: str) -> dict:
    """An arbitrary user id / role pair, for identity-sensitive assertions."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = ADMIN_USER_ID) -> dict:
    """A request that omits X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_DATA_PLATFORM_ADMIN) -> dict:
    """A request that omits X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_blank_user_id(role: str = ROLE_DATA_PLATFORM_ADMIN) -> dict:
    """A request whose X-User-ID is present but blank."""
    return build_user_headers("   ", role)


def headers_with_blank_role(user_id: str = ADMIN_USER_ID) -> dict:
    """A request whose X-User-Role is present but blank."""
    return build_user_headers(user_id, "   ")


def headers_with_unknown_role(user_id: str = ADMIN_USER_ID) -> dict:
    """A request whose X-User-Role is not one of the seven declared roles."""
    return build_user_headers(user_id, "MarketingOperations")


def headers_without_auth() -> dict:
    """A request that carries neither auth header."""
    return {"Content-Type": "application/json"}
