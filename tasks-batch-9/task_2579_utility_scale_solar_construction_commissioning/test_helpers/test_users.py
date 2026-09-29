"""Acting principals for the eight roles of PRD 2.1.

All eight roles are opaque identities: ``X-User-ID`` is an operator identifier
that is never compared against any entity's ``id``, so a module-level constant
is safe for every role. The server does compare recorded operator identifiers to
each other for the separation rules of PRD 2.10, which is why each role also has
an explicit builder and a second, distinct identity.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CIVIL_SUPERINTENDENT,
    ROLE_COMMISSIONING_ENGINEER,
    ROLE_EPC_PROJECT_MANAGER,
    ROLE_INSTALLATION_FOREMAN,
    ROLE_LABOR_COMPLIANCE_OFFICER,
    ROLE_OWNER_ENGINEER,
    ROLE_PROCUREMENT_COORDINATOR,
    ROLE_UTILITY_COORDINATOR,
)

# Primary operator identity per role.
EPM_USER_ID = "EPM-77"
CIVIL_USER_ID = "CS-14"
PROCUREMENT_USER_ID = "PC-23"
FOREMAN_USER_ID = "IF-31"
UTILITY_USER_ID = "UC-52"
COMMISSIONING_USER_ID = "CE-8"
OWNER_USER_ID = "OE-12"
LABOR_USER_ID = "LCO-9"

# Second identity per role, for the separation-of-duties comparisons.
EPM_ALT_USER_ID = "EPM-78"
FOREMAN_ALT_USER_ID = "IF-32"
OWNER_ALT_USER_ID = "OE-13"
LABOR_ALT_USER_ID = "LCO-2"

EPC_PROJECT_MANAGER = build_user_headers(EPM_USER_ID, ROLE_EPC_PROJECT_MANAGER)
CIVIL_SUPERINTENDENT = build_user_headers(CIVIL_USER_ID, ROLE_CIVIL_SUPERINTENDENT)
PROCUREMENT_COORDINATOR = build_user_headers(
    PROCUREMENT_USER_ID, ROLE_PROCUREMENT_COORDINATOR
)
INSTALLATION_FOREMAN = build_user_headers(FOREMAN_USER_ID, ROLE_INSTALLATION_FOREMAN)
UTILITY_COORDINATOR = build_user_headers(UTILITY_USER_ID, ROLE_UTILITY_COORDINATOR)
COMMISSIONING_ENGINEER = build_user_headers(
    COMMISSIONING_USER_ID, ROLE_COMMISSIONING_ENGINEER
)
OWNER_ENGINEER = build_user_headers(OWNER_USER_ID, ROLE_OWNER_ENGINEER)
LABOR_COMPLIANCE_OFFICER = build_user_headers(
    LABOR_USER_ID, ROLE_LABOR_COMPLIANCE_OFFICER
)

EPC_PROJECT_MANAGER_ALT = build_user_headers(EPM_ALT_USER_ID, ROLE_EPC_PROJECT_MANAGER)
INSTALLATION_FOREMAN_ALT = build_user_headers(
    FOREMAN_ALT_USER_ID, ROLE_INSTALLATION_FOREMAN
)
OWNER_ENGINEER_ALT = build_user_headers(OWNER_ALT_USER_ID, ROLE_OWNER_ENGINEER)
LABOR_COMPLIANCE_OFFICER_ALT = build_user_headers(
    LABOR_ALT_USER_ID, ROLE_LABOR_COMPLIANCE_OFFICER
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "epc_project_manager_headers": EPC_PROJECT_MANAGER,
    "civil_superintendent_headers": CIVIL_SUPERINTENDENT,
    "procurement_coordinator_headers": PROCUREMENT_COORDINATOR,
    "installation_foreman_headers": INSTALLATION_FOREMAN,
    "utility_coordinator_headers": UTILITY_COORDINATOR,
    "commissioning_engineer_headers": COMMISSIONING_ENGINEER,
    "owner_engineer_headers": OWNER_ENGINEER,
    "labor_compliance_officer_headers": LABOR_COMPLIANCE_OFFICER,
}

# Role name -> headers, for the tests that sweep every role over one operation.
HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    ROLE_EPC_PROJECT_MANAGER: EPC_PROJECT_MANAGER,
    ROLE_CIVIL_SUPERINTENDENT: CIVIL_SUPERINTENDENT,
    ROLE_PROCUREMENT_COORDINATOR: PROCUREMENT_COORDINATOR,
    ROLE_INSTALLATION_FOREMAN: INSTALLATION_FOREMAN,
    ROLE_UTILITY_COORDINATOR: UTILITY_COORDINATOR,
    ROLE_COMMISSIONING_ENGINEER: COMMISSIONING_ENGINEER,
    ROLE_OWNER_ENGINEER: OWNER_ENGINEER,
    ROLE_LABOR_COMPLIANCE_OFFICER: LABOR_COMPLIANCE_OFFICER,
}


def role_headers(role: str, user_id: str = "OP-1") -> Dict[str, str]:
    """Headers for an arbitrary role string, including undeclared ones."""
    return build_user_headers(user_id, role)


def make_epc_headers(user_id: str) -> Dict[str, str]:
    """An `EpcProjectManager` acting under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_EPC_PROJECT_MANAGER)


def make_civil_headers(user_id: str) -> Dict[str, str]:
    """A `CivilSuperintendent` acting under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_CIVIL_SUPERINTENDENT)


def make_procurement_headers(user_id: str) -> Dict[str, str]:
    """A `ProcurementCoordinator` acting under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_PROCUREMENT_COORDINATOR)


def make_foreman_headers(user_id: str) -> Dict[str, str]:
    """An `InstallationForeman` acting under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_INSTALLATION_FOREMAN)


def make_utility_headers(user_id: str) -> Dict[str, str]:
    """A `UtilityCoordinator` acting under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_UTILITY_COORDINATOR)


def make_commissioning_headers(user_id: str) -> Dict[str, str]:
    """A `CommissioningEngineer` acting under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_COMMISSIONING_ENGINEER)


def make_owner_headers(user_id: str) -> Dict[str, str]:
    """An `OwnerEngineer` acting under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_OWNER_ENGINEER)


def make_labor_headers(user_id: str) -> Dict[str, str]:
    """A `LaborComplianceOfficer` acting under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_LABOR_COMPLIANCE_OFFICER)


def headers_without_auth() -> Dict[str, str]:
    """A request carrying neither `X-User-ID` nor `X-User-Role`."""
    return {"Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """A request carrying `X-User-Role` but no `X-User-ID`."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """A request carrying `X-User-ID` but no `X-User-Role`."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
