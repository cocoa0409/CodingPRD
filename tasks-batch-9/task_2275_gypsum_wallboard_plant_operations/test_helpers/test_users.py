"""Pre-built request headers, one per role plus the extra identities.

PRD 2.1 treats ``X-User-ID`` as an opaque identifier that is never validated, but
four fields record it and three rules compare it, so several distinct identities
are kept for the same role.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# --------------------------------------------------------------------------- #
# Opaque user identifiers
# --------------------------------------------------------------------------- #

USER_ADMIN = "u_admin"
USER_MATERIALS = "u_mat"
USER_SCHEDULER = "u_sched"
USER_INSPECTOR_1 = "u_qi_1"
USER_INSPECTOR_2 = "u_qi_2"
USER_QUALITY_MANAGER = "u_qm"
USER_PLANNER = "u_planner"
USER_MANAGER = "u_mgr"


# --------------------------------------------------------------------------- #
# Headers
# --------------------------------------------------------------------------- #

PLANT_ADMIN = build_user_headers(USER_ADMIN, Role.PLANT_ADMIN.value)
MATERIALS_CONTROLLER = build_user_headers(USER_MATERIALS, Role.MATERIALS_CONTROLLER.value)
PRODUCTION_SCHEDULER = build_user_headers(USER_SCHEDULER, Role.PRODUCTION_SCHEDULER.value)
QUALITY_INSPECTOR = build_user_headers(USER_INSPECTOR_1, Role.QUALITY_INSPECTOR.value)
QUALITY_INSPECTOR_2 = build_user_headers(USER_INSPECTOR_2, Role.QUALITY_INSPECTOR.value)
QUALITY_MANAGER = build_user_headers(USER_QUALITY_MANAGER, Role.QUALITY_MANAGER.value)
MAINTENANCE_PLANNER = build_user_headers(USER_PLANNER, Role.MAINTENANCE_PLANNER.value)
PLANT_MANAGER = build_user_headers(USER_MANAGER, Role.PLANT_MANAGER.value)


#: One representative header per role, keyed by the PRD role name.
HEADERS_BY_ROLE: dict[str, dict[str, str]] = {
    Role.PLANT_ADMIN.value: PLANT_ADMIN,
    Role.MATERIALS_CONTROLLER.value: MATERIALS_CONTROLLER,
    Role.PRODUCTION_SCHEDULER.value: PRODUCTION_SCHEDULER,
    Role.QUALITY_INSPECTOR.value: QUALITY_INSPECTOR,
    Role.QUALITY_MANAGER.value: QUALITY_MANAGER,
    Role.MAINTENANCE_PLANNER.value: MAINTENANCE_PLANNER,
    Role.PLANT_MANAGER.value: PLANT_MANAGER,
}


def headers_for(role: str, user_id: str = "u_probe") -> dict[str, str]:
    """Build headers for an arbitrary role/user pair, including unknown roles."""
    return build_user_headers(user_id, role)


def roles_other_than(*allowed: str) -> list[str]:
    """Every PRD role except the ones named — the cross-role rejection set."""
    return [role for role in HEADERS_BY_ROLE if role not in allowed]


#: Headers with no ``X-User-Role`` at all (PRD 2.1 authentication band).
NO_ROLE_HEADERS: dict[str, str] = {
    "X-User-ID": "u_probe",
    "Content-Type": "application/json",
}

#: Headers naming a role that does not appear in PRD 2.1.
UNKNOWN_ROLE_HEADERS: dict[str, str] = build_user_headers("u_probe", "WarehouseClerk")
