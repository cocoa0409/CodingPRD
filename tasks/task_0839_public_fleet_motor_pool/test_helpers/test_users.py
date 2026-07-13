"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity-backed ownership. Four of the five roles carry an opaque identity.
TEST_USERS = {
    "fleet_admin_headers": build_user_headers("test-fleet-admin-1", "FleetAdmin"),
    "motor_pool_clerk_headers": build_user_headers("test-clerk-1", "MotorPoolClerk"),
    "shop_tech_headers": build_user_headers("test-shoptech-1", "ShopTech"),
    "finance_officer_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
    # DepartmentUser is entity_backed:Department. The shared constant here is only a
    # fallback for non-ownership scenarios; ownership-gated calls MUST use the builder.
    "department_user_headers": build_user_headers("test-dept-user-1", "DepartmentUser"),
}


def make_department_user_headers(department_id: str) -> dict:
    """For DepartmentUser (entity_backed:Department). Pass the acting Department.id
    as X-User-ID whenever the call is ownership-gated (its department FK is compared
    to this value)."""
    return build_user_headers(department_id, "DepartmentUser")


def anonymous_headers() -> dict:
    """Headers carrying no X-User-Role / X-User-ID — used for unauthenticated tests."""
    return {"Content-Type": "application/json"}
