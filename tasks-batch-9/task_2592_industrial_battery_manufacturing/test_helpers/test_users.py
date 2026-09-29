"""Actor identities and header builders.

Four roles are backed by a Worker row: their `X-User-ID` must be the identifier
of an existing worker, so tests build their headers from an identifier captured
during setup. The remaining three roles use an opaque identifier, so a constant
is enough for them.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DESIGN_ENGINEER,
    ROLE_FLEET_ENGINEER,
    ROLE_PLANT_ADMIN,
    ROLE_PRODUCTION_SUPERVISOR,
    ROLE_QUALITY_INSPECTOR,
    ROLE_SAFETY_OFFICER,
    ROLE_WARRANTY_ADMINISTRATOR,
)

# --- Opaque actors ---------------------------------------------------------
PLANT_ADMIN_USER_ID = "admin-0001"
FLEET_ENGINEER_USER_ID = "fleet-0001"
WARRANTY_ADMIN_USER_ID = "warranty-0001"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "plant_admin": {"user_id": PLANT_ADMIN_USER_ID, "role": ROLE_PLANT_ADMIN},
    "fleet_engineer": {"user_id": FLEET_ENGINEER_USER_ID, "role": ROLE_FLEET_ENGINEER},
    "warranty_admin": {
        "user_id": WARRANTY_ADMIN_USER_ID,
        "role": ROLE_WARRANTY_ADMINISTRATOR,
    },
}

PLANT_ADMIN_HEADERS = build_user_headers(PLANT_ADMIN_USER_ID, ROLE_PLANT_ADMIN)
FLEET_ENGINEER_HEADERS = build_user_headers(FLEET_ENGINEER_USER_ID, ROLE_FLEET_ENGINEER)
WARRANTY_ADMIN_HEADERS = build_user_headers(
    WARRANTY_ADMIN_USER_ID, ROLE_WARRANTY_ADMINISTRATOR
)


def make_plant_admin_headers(user_id: str = PLANT_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLANT_ADMIN)


def make_fleet_engineer_headers(user_id: str = FLEET_ENGINEER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_FLEET_ENGINEER)


def make_warranty_admin_headers(
    user_id: str = WARRANTY_ADMIN_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_WARRANTY_ADMINISTRATOR)


# --- Worker-backed actors --------------------------------------------------
def make_design_engineer_headers(worker_id: str) -> Dict[str, str]:
    """Headers for a DesignEngineer acting as the worker `worker_id`."""
    return build_user_headers(worker_id, ROLE_DESIGN_ENGINEER)


def make_production_supervisor_headers(worker_id: str) -> Dict[str, str]:
    """Headers for a ProductionSupervisor acting as the worker `worker_id`."""
    return build_user_headers(worker_id, ROLE_PRODUCTION_SUPERVISOR)


def make_quality_inspector_headers(worker_id: str) -> Dict[str, str]:
    """Headers for a QualityInspector acting as the worker `worker_id`."""
    return build_user_headers(worker_id, ROLE_QUALITY_INSPECTOR)


def make_safety_officer_headers(worker_id: str) -> Dict[str, str]:
    """Headers for a SafetyOfficer acting as the worker `worker_id`."""
    return build_user_headers(worker_id, ROLE_SAFETY_OFFICER)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role/identifier pair."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = PLANT_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers carrying an identifier but no role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user(role: str = ROLE_PLANT_ADMIN) -> Dict[str, str]:
    """Headers carrying a role but no identifier at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
