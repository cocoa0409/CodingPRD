"""Pre-built role headers for every role in the PRD (§2.1).

All five roles are opaque: `X-User-ID` is not tied to any persisted entity, so
the shared constants below are safe everywhere. Segregation-of-duties scenarios
need a specific user id on a specific role; use the per-role builders for that.
"""
from prd_bench_local_runner.testing import build_user_headers


def admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def ip_headers(user_id: str = "test-ip-1") -> dict:
    return build_user_headers(user_id, "InfectionPreventionist")


def director_headers(user_id: str = "test-director-1") -> dict:
    return build_user_headers(user_id, "InfectionControlDirector")


def nurse_manager_headers(user_id: str = "test-unm-1") -> dict:
    return build_user_headers(user_id, "UnitNurseManager")


def health_nurse_headers(user_id: str = "test-ehn-1") -> dict:
    return build_user_headers(user_id, "EmployeeHealthNurse")


TEST_USERS = {
    "platform_admin_headers": admin_headers(),
    "infection_preventionist_headers": ip_headers(),
    "infection_control_director_headers": director_headers(),
    "unit_nurse_manager_headers": nurse_manager_headers(),
    "employee_health_nurse_headers": health_nurse_headers(),
}
