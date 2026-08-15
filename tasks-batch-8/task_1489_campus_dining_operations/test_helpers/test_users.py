"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role probes).
TEST_USERS = {
    "dining_admin_headers": build_user_headers("test-admin-1", "DiningAdmin"),
    "hall_manager_headers": build_user_headers("test-hall-manager-1", "HallManager"),
    "kitchen_lead_headers": build_user_headers("test-kitchen-lead-1", "KitchenLead"),
    "dietitian_headers": build_user_headers("test-dietitian-1", "Dietitian"),
    "health_inspector_headers": build_user_headers("test-inspector-1", "HealthInspector"),
    "contract_manager_headers": build_user_headers("test-contract-mgr-1", "ContractManager"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "department_user_headers": build_user_headers("test-dept-user-1", "DepartmentUser"),
}


def make_department_user_headers(department_id: str) -> dict:
    """For DepartmentUser (entity_backed:Department). Pass the actual
    Department.id as department_id whenever the call is ownership-gated
    (order create / submit / cancel, own-department reads)."""
    return build_user_headers(department_id, "DepartmentUser")


def make_dining_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "DiningAdmin")


def make_hall_manager_headers(user_id: str = "test-hall-manager-1") -> dict:
    return build_user_headers(user_id, "HallManager")


def make_kitchen_lead_headers(user_id: str = "test-kitchen-lead-1") -> dict:
    return build_user_headers(user_id, "KitchenLead")


def make_dietitian_headers(user_id: str = "test-dietitian-1") -> dict:
    return build_user_headers(user_id, "Dietitian")


def make_health_inspector_headers(user_id: str = "test-inspector-1") -> dict:
    return build_user_headers(user_id, "HealthInspector")


def make_contract_manager_headers(user_id: str = "test-contract-mgr-1") -> dict:
    return build_user_headers(user_id, "ContractManager")
