"""Type aliases used across the FleetCare test suite."""

from typing import Any, Dict, List

Json = Dict[str, Any]
JsonList = List[Json]
Headers = Dict[str, str]

# Role names exactly as declared by the PRD.
ROLE_CONTRACT_ADMINISTRATOR = "ContractAdministrator"
ROLE_SERVICE_COORDINATOR = "ServiceCoordinator"
ROLE_PARTS_PLANNER = "PartsPlanner"
ROLE_FIELD_TECHNICIAN = "FieldTechnician"
ROLE_SAFETY_INSPECTOR = "SafetyInspector"
ROLE_CLUB_MANAGER = "ClubManager"

ALL_ROLES = (
    ROLE_CONTRACT_ADMINISTRATOR,
    ROLE_SERVICE_COORDINATOR,
    ROLE_PARTS_PLANNER,
    ROLE_FIELD_TECHNICIAN,
    ROLE_SAFETY_INSPECTOR,
    ROLE_CLUB_MANAGER,
)

# Roles whose X-User-ID must be a real entity id (identity binding).
ENTITY_BACKED_ROLES = (
    ROLE_FIELD_TECHNICIAN,
    ROLE_SAFETY_INSPECTOR,
    ROLE_CLUB_MANAGER,
)

# Roles whose X-User-ID is an opaque operator identifier.
OPAQUE_ROLES = (
    ROLE_CONTRACT_ADMINISTRATOR,
    ROLE_SERVICE_COORDINATOR,
    ROLE_PARTS_PLANNER,
)
