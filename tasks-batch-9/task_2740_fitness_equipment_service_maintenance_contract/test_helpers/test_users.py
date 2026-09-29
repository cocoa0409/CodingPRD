"""
Auth headers for the six FleetCare roles.

Identity binding differs by role, and that difference is load-bearing:

- ``ContractAdministrator``, ``ServiceCoordinator`` and ``PartsPlanner`` present an
  opaque operator identifier that the server never compares to any row, so the
  module-level constants below are safe for them.
- ``FieldTechnician`` and ``SafetyInspector`` present the ``id`` of the acting
  ``Technician`` row, and ``ClubManager`` presents the ``id`` of the acting ``Club``
  row. For those three, always build headers from the real entity id created by the
  fixture with ``make_field_technician_headers`` / ``make_safety_inspector_headers`` /
  ``make_club_manager_headers``. Reusing a fixed constant for them makes every
  ownership-checked call fail with ERR_TECHNICIAN_NOT_ASSIGNED or
  ERR_CLUB_SCOPE_FORBIDDEN.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_CLUB_MANAGER,
    ROLE_CONTRACT_ADMINISTRATOR,
    ROLE_FIELD_TECHNICIAN,
    ROLE_PARTS_PLANNER,
    ROLE_SAFETY_INSPECTOR,
    ROLE_SERVICE_COORDINATOR,
)

# ─── Opaque-identity roles: fixed headers are correct ─────────────────────────

CONTRACT_ADMIN_USER_ID = "op-contract-admin-1"
SERVICE_COORDINATOR_USER_ID = "op-service-coordinator-1"
PARTS_PLANNER_USER_ID = "op-parts-planner-1"

CONTRACT_ADMIN = build_user_headers(CONTRACT_ADMIN_USER_ID, ROLE_CONTRACT_ADMINISTRATOR)
SERVICE_COORDINATOR = build_user_headers(
    SERVICE_COORDINATOR_USER_ID, ROLE_SERVICE_COORDINATOR
)
PARTS_PLANNER = build_user_headers(PARTS_PLANNER_USER_ID, ROLE_PARTS_PLANNER)

# Convenience alias set used by tests that only need "some authorised reader".
ANY_READER = CONTRACT_ADMIN


# ─── Entity-backed roles: build headers from the real row id ──────────────────


def make_contract_admin_headers(user_id: str = CONTRACT_ADMIN_USER_ID):
    """Headers for a ContractAdministrator (identifier is opaque)."""
    return build_user_headers(user_id, ROLE_CONTRACT_ADMINISTRATOR)


def make_service_coordinator_headers(user_id: str = SERVICE_COORDINATOR_USER_ID):
    """Headers for a ServiceCoordinator (identifier is opaque)."""
    return build_user_headers(user_id, ROLE_SERVICE_COORDINATOR)


def make_parts_planner_headers(user_id: str = PARTS_PLANNER_USER_ID):
    """Headers for a PartsPlanner (identifier is opaque)."""
    return build_user_headers(user_id, ROLE_PARTS_PLANNER)


def make_field_technician_headers(technician_id: str):
    """Headers for a FieldTechnician acting as the Technician row ``technician_id``."""
    return build_user_headers(technician_id, ROLE_FIELD_TECHNICIAN)


def make_safety_inspector_headers(technician_id: str):
    """Headers for a SafetyInspector acting as the Technician row ``technician_id``."""
    return build_user_headers(technician_id, ROLE_SAFETY_INSPECTOR)


def make_club_manager_headers(club_id: str):
    """Headers for a ClubManager acting as the Club row ``club_id``."""
    return build_user_headers(club_id, ROLE_CLUB_MANAGER)


def headers_for_role(role: str, entity_id: str = None):
    """
    Build headers for any role by name.

    ``entity_id`` is required for FieldTechnician, SafetyInspector and ClubManager
    because their X-User-ID is compared against a persisted row.
    """
    if role in (ROLE_FIELD_TECHNICIAN, ROLE_SAFETY_INSPECTOR, ROLE_CLUB_MANAGER):
        assert entity_id is not None, f"{role} needs the id of its backing row"
        return build_user_headers(entity_id, role)
    defaults = {
        ROLE_CONTRACT_ADMINISTRATOR: CONTRACT_ADMIN_USER_ID,
        ROLE_SERVICE_COORDINATOR: SERVICE_COORDINATOR_USER_ID,
        ROLE_PARTS_PLANNER: PARTS_PLANNER_USER_ID,
    }
    return build_user_headers(entity_id or defaults[role], role)
