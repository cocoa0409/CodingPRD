"""Caller identities for the seven roles named in the PRD.

Six roles are opaque: any identifier presented with the role is accepted, so a
single fixed identifier per role suffices. `Developer` is different — the API
compares the caller's `X-User-ID` against a stored `developer_id`, so Developer
headers must always be built from a registered developer's `id`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_REAL_ESTATE_OFFICER = "RealEstateOfficer"
ROLE_VALUATION_OFFICER = "ValuationOfficer"
ROLE_BOARD_SECRETARY = "BoardSecretary"
ROLE_GRANTS_COMPLIANCE_OFFICER = "GrantsComplianceOfficer"
ROLE_TRANSIT_OPERATIONS_MANAGER = "TransitOperationsManager"
ROLE_DEVELOPER = "Developer"
ROLE_SYSTEM_ADMIN = "SystemAdmin"

ALL_ROLES = [
    ROLE_REAL_ESTATE_OFFICER,
    ROLE_VALUATION_OFFICER,
    ROLE_BOARD_SECRETARY,
    ROLE_GRANTS_COMPLIANCE_OFFICER,
    ROLE_TRANSIT_OPERATIONS_MANAGER,
    ROLE_DEVELOPER,
    ROLE_SYSTEM_ADMIN,
]

DEFAULT_USER_IDS = {
    ROLE_REAL_ESTATE_OFFICER: "reo-001",
    ROLE_VALUATION_OFFICER: "vo-001",
    ROLE_BOARD_SECRETARY: "bsec-001",
    ROLE_GRANTS_COMPLIANCE_OFFICER: "gco-001",
    ROLE_TRANSIT_OPERATIONS_MANAGER: "tom-001",
    ROLE_SYSTEM_ADMIN: "sa-001",
}

# Secondary staff identities, used where one person must not act twice.
SECOND_REAL_ESTATE_OFFICER_ID = "reo-002"
SECOND_BOARD_SECRETARY_ID = "bsec-002"

TEST_USERS: Dict[str, Dict[str, str]] = {
    role: build_user_headers(user_id, role)
    for role, user_id in DEFAULT_USER_IDS.items()
}


def make_real_estate_officer_headers(user_id: str = "reo-001") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_REAL_ESTATE_OFFICER)


def make_valuation_officer_headers(user_id: str = "vo-001") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_VALUATION_OFFICER)


def make_board_secretary_headers(user_id: str = "bsec-001") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_BOARD_SECRETARY)


def make_grants_compliance_officer_headers(user_id: str = "gco-001") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_GRANTS_COMPLIANCE_OFFICER)


def make_transit_operations_manager_headers(user_id: str = "tom-001") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_TRANSIT_OPERATIONS_MANAGER)


def make_system_admin_headers(user_id: str = "sa-001") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_SYSTEM_ADMIN)


def make_developer_headers(developer_id: str) -> Dict[str, str]:
    """Developer headers must carry the registered developer's own identifier."""
    return build_user_headers(developer_id, ROLE_DEVELOPER)


def make_role_headers(role: str, user_id: str = None) -> Dict[str, str]:
    """Headers for an arbitrary role, defaulting to that role's staff identity."""
    if user_id is None:
        user_id = DEFAULT_USER_IDS.get(role, "user-001")
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
