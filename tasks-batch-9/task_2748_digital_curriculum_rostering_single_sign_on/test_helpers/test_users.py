"""
Pre-built auth headers for the five roles of the rostering API.

Four roles (RosterOperator, DataGovernanceOfficer, VendorIntegrationManager,
IdentityAdmin) are opaque operator identities: X-User-ID is an opaque operator
identifier that is never resolved to an entity row. BuildingLicenseAdmin is the
single entity-backed role: its X-User-ID is the id of the acting School, so its
headers can only be built once the school exists.

Two-person controls compare recorded operator identifiers to each other, so a
second distinct identity is provided for the roles that participate in them.
"""

from prd_bench_local_runner.testing import build_user_headers

# ── Role names, spelled exactly as the contract spells them ──────────────────
ROLE_ROSTER_OPERATOR = "RosterOperator"
ROLE_DATA_GOVERNANCE_OFFICER = "DataGovernanceOfficer"
ROLE_VENDOR_INTEGRATION_MANAGER = "VendorIntegrationManager"
ROLE_BUILDING_LICENSE_ADMIN = "BuildingLicenseAdmin"
ROLE_IDENTITY_ADMIN = "IdentityAdmin"

ALL_ROLES = [
    ROLE_ROSTER_OPERATOR,
    ROLE_DATA_GOVERNANCE_OFFICER,
    ROLE_VENDOR_INTEGRATION_MANAGER,
    ROLE_BUILDING_LICENSE_ADMIN,
    ROLE_IDENTITY_ADMIN,
]

# ── Opaque operator identifiers ──────────────────────────────────────────────
ROSTER_OPERATOR_ID = "ro-001"
ROSTER_OPERATOR_2_ID = "ro-002"
DATA_GOVERNANCE_OFFICER_ID = "dgo-001"
DATA_GOVERNANCE_OFFICER_2_ID = "dgo-002"
VENDOR_INTEGRATION_MANAGER_ID = "vim-001"
VENDOR_INTEGRATION_MANAGER_2_ID = "vim-002"
IDENTITY_ADMIN_ID = "ia-001"
IDENTITY_ADMIN_2_ID = "ia-002"

# ── Ready-made header dicts ──────────────────────────────────────────────────
ROSTER_OPERATOR = build_user_headers(ROSTER_OPERATOR_ID, ROLE_ROSTER_OPERATOR)
ROSTER_OPERATOR_2 = build_user_headers(ROSTER_OPERATOR_2_ID, ROLE_ROSTER_OPERATOR)
DATA_GOVERNANCE_OFFICER = build_user_headers(
    DATA_GOVERNANCE_OFFICER_ID, ROLE_DATA_GOVERNANCE_OFFICER
)
DATA_GOVERNANCE_OFFICER_2 = build_user_headers(
    DATA_GOVERNANCE_OFFICER_2_ID, ROLE_DATA_GOVERNANCE_OFFICER
)
VENDOR_INTEGRATION_MANAGER = build_user_headers(
    VENDOR_INTEGRATION_MANAGER_ID, ROLE_VENDOR_INTEGRATION_MANAGER
)
VENDOR_INTEGRATION_MANAGER_2 = build_user_headers(
    VENDOR_INTEGRATION_MANAGER_2_ID, ROLE_VENDOR_INTEGRATION_MANAGER
)
IDENTITY_ADMIN = build_user_headers(IDENTITY_ADMIN_ID, ROLE_IDENTITY_ADMIN)
IDENTITY_ADMIN_2 = build_user_headers(IDENTITY_ADMIN_2_ID, ROLE_IDENTITY_ADMIN)


def building_license_admin(school_id: str) -> dict:
    """Headers for the BuildingLicenseAdmin acting as the given School."""
    return build_user_headers(school_id, ROLE_BUILDING_LICENSE_ADMIN)


def headers_for_role(role: str, user_id: str = None) -> dict:
    """Headers for an arbitrary role, defaulting to that role's usual identity."""
    defaults = {
        ROLE_ROSTER_OPERATOR: ROSTER_OPERATOR_ID,
        ROLE_DATA_GOVERNANCE_OFFICER: DATA_GOVERNANCE_OFFICER_ID,
        ROLE_VENDOR_INTEGRATION_MANAGER: VENDOR_INTEGRATION_MANAGER_ID,
        ROLE_BUILDING_LICENSE_ADMIN: "school-placeholder",
        ROLE_IDENTITY_ADMIN: IDENTITY_ADMIN_ID,
    }
    return build_user_headers(user_id or defaults[role], role)


# Headers missing one or both auth headers, for the ERR_UNAUTHENTICATED rung.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
MISSING_USER_ID_HEADERS = {
    "X-User-Role": ROLE_ROSTER_OPERATOR,
    "Content-Type": "application/json",
}
MISSING_ROLE_HEADERS = {
    "X-User-ID": ROSTER_OPERATOR_ID,
    "Content-Type": "application/json",
}
BLANK_USER_ID_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": ROLE_ROSTER_OPERATOR,
    "Content-Type": "application/json",
}
BLANK_ROLE_HEADERS = {
    "X-User-ID": ROSTER_OPERATOR_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}
