"""Role headers for the nine roles the PRD declares.

Every role is opaque: the PRD authorises purely on the ``X-User-Role`` header,
while ``X-User-ID`` is the actor identity the separation-of-duty rules compare.
Each builder therefore takes an explicit user id so a test can make the same
role act as two different people.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

PLATFORM_ADMIN = "PlatformAdmin"
APPLICATION_ENGINEER = "ApplicationEngineer"
DESIGN_REVIEWER = "DesignReviewer"
FABRICATION_MANAGER = "FabricationManager"
QUALITY_ENGINEER = "QualityEngineer"
COMMISSIONING_ENGINEER = "CommissioningEngineer"
ENGINEER_OF_RECORD = "EngineerOfRecord"
OWNER_REPRESENTATIVE = "OwnerRepresentative"
CONTRACTS_ADMINISTRATOR = "ContractsAdministrator"

ALL_ROLES = (
    PLATFORM_ADMIN,
    APPLICATION_ENGINEER,
    DESIGN_REVIEWER,
    FABRICATION_MANAGER,
    QUALITY_ENGINEER,
    COMMISSIONING_ENGINEER,
    ENGINEER_OF_RECORD,
    OWNER_REPRESENTATIVE,
    CONTRACTS_ADMINISTRATOR,
)

# Canonical actor id per role. Tests that need a second person in the same role
# pass an explicit user_id to the matching builder.
DEFAULT_USER_IDS = {
    PLATFORM_ADMIN: "admin-1",
    APPLICATION_ENGINEER: "eng-1",
    DESIGN_REVIEWER: "rev-1",
    FABRICATION_MANAGER: "fab-1",
    QUALITY_ENGINEER: "qa-1",
    COMMISSIONING_ENGINEER: "comm-1",
    ENGINEER_OF_RECORD: "eor-1",
    OWNER_REPRESENTATIVE: "own-1",
    CONTRACTS_ADMINISTRATOR: "ca-1",
}

TEST_USERS: Dict[str, Dict[str, str]] = {
    role: {"user_id": user_id, "role": role}
    for role, user_id in DEFAULT_USER_IDS.items()
}


def make_headers(role: str, user_id: str = None) -> Dict[str, str]:
    """Build auth headers for ``role``, defaulting to that role's canonical actor."""
    return build_user_headers(user_id or DEFAULT_USER_IDS[role], role)


def make_platform_admin_headers(user_id: str = None) -> Dict[str, str]:
    return make_headers(PLATFORM_ADMIN, user_id)


def make_application_engineer_headers(user_id: str = None) -> Dict[str, str]:
    return make_headers(APPLICATION_ENGINEER, user_id)


def make_design_reviewer_headers(user_id: str = None) -> Dict[str, str]:
    return make_headers(DESIGN_REVIEWER, user_id)


def make_fabrication_manager_headers(user_id: str = None) -> Dict[str, str]:
    return make_headers(FABRICATION_MANAGER, user_id)


def make_quality_engineer_headers(user_id: str = None) -> Dict[str, str]:
    return make_headers(QUALITY_ENGINEER, user_id)


def make_commissioning_engineer_headers(user_id: str = None) -> Dict[str, str]:
    return make_headers(COMMISSIONING_ENGINEER, user_id)


def make_engineer_of_record_headers(user_id: str = None) -> Dict[str, str]:
    return make_headers(ENGINEER_OF_RECORD, user_id)


def make_owner_representative_headers(user_id: str = None) -> Dict[str, str]:
    return make_headers(OWNER_REPRESENTATIVE, user_id)


def make_contracts_administrator_headers(user_id: str = None) -> Dict[str, str]:
    return make_headers(CONTRACTS_ADMINISTRATOR, user_id)


def make_headers_without_role(user_id: str = "eng-1") -> Dict[str, str]:
    """Headers carrying an actor but no role, used to probe the 401 path."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
