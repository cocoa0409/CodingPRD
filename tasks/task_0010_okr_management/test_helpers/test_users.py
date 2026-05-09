"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity model:
- PlatformAdmin / HRBP: opaque identifier — shared constant is canonical and safe.
- Manager / Employee: X-User-ID is the id of the acting User row. Shared constants
  are safe ONLY for tests that do NOT exercise ownership (e.g., 400-on-bad-payload,
  404-on-missing-resource, GET-without-confidentiality). Any ownership-gated call
  MUST use make_employee_headers / make_manager_headers with the actual User.id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't touch ownership.
TEST_USERS = {
    # opaque roles — shared constant is canonical
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "hrbp_headers": build_user_headers("hrbp-1", "HRBP"),

    # entity_backed roles — shared constants are FALLBACK ONLY for non-ownership tests.
    # These constants intentionally do NOT resolve to any real User; for any ownership
    # check they will fail. Use make_employee_headers / make_manager_headers instead
    # for ownership-gated calls.
    "employee_headers": build_user_headers("employee-shared-no-ownership", "Employee"),
    "manager_headers": build_user_headers("manager-shared-no-ownership", "Manager"),
}


# Per-instance builders — REQUIRED for every ownership-gated call.
def make_employee_headers(user_id: str) -> dict:
    """For Employee (entity_backed:User). Pass the actual User.id whose role_type=EMPLOYEE."""
    return build_user_headers(user_id, "Employee")


def make_manager_headers(user_id: str) -> dict:
    """For Manager (entity_backed:User). Pass the actual User.id whose role_type=MANAGER."""
    return build_user_headers(user_id, "Manager")


def make_admin_headers(opaque_id: str = "platform-admin-1") -> dict:
    """For PlatformAdmin. Opaque id; default is the shared constant."""
    return build_user_headers(opaque_id, "PlatformAdmin")


def make_hrbp_headers(opaque_id: str = "hrbp-1") -> dict:
    """For HRBP. Opaque id; default is the shared constant."""
    return build_user_headers(opaque_id, "HRBP")
