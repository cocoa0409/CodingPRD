"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — the six internal roles are opaque identifiers (PRD §2.1),
# safe wherever the call is not a segregation-of-duties subject. Tests that
# exercise segregation build per-instance headers with the make_* builders.
TEST_USERS = {
    "plant_manager_headers": build_user_headers("pm-1", "PlantManager"),
    "production_planner_headers": build_user_headers("planner-1", "ProductionPlanner"),
    "line_operator_headers": build_user_headers("operator-1", "LineOperator"),
    "qa_technician_headers": build_user_headers("qa-tech-1", "QATechnician"),
    "qa_manager_headers": build_user_headers("qa-mgr-1", "QAManager"),
    "warehouse_lead_headers": build_user_headers("warehouse-1", "WarehouseLead"),
}


def make_plant_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantManager")


def make_production_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_line_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LineOperator")


def make_qa_technician_headers(user_id: str) -> dict:
    """Segregation-sensitive: lot release compares against CCP performers."""
    return build_user_headers(user_id, "QATechnician")


def make_qa_manager_headers(user_id: str) -> dict:
    """Segregation-sensitive: releaser/resolver must differ from performer/reporter."""
    return build_user_headers(user_id, "QAManager")


def make_warehouse_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarehouseLead")


def make_copack_customer_headers(customer_id: str) -> dict:
    """CoPackCustomer is entity-backed (PRD §2.1): X-User-ID must be the actual
    CoPackCustomer record id for ownership-scoped calls."""
    return build_user_headers(customer_id, "CoPackCustomer")
