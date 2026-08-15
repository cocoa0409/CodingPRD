"""Pre-built role headers for every role in the PRD.

All roles are opaque: X-User-ID is an operator identifier never compared to
any entity id (PRD section 2.1). Shared constants are therefore the canonical
form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "procurement_manager_headers": build_user_headers(
        "proc-1", "ProcurementManager"),
    "yard_supervisor_headers": build_user_headers("yard-1", "YardSupervisor"),
    "heat_treat_operator_headers": build_user_headers(
        "ht-1", "HeatTreatOperator"),
    "sales_rep_headers": build_user_headers("sales-1", "SalesRep"),
    "fleet_planner_headers": build_user_headers("fleet-1", "FleetPlanner"),
    "plant_manager_headers": build_user_headers("plant-1", "PlantManager"),
    "any_headers": build_user_headers("any-1", "Any"),
}


def make_procurement_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProcurementManager")


def make_yard_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "YardSupervisor")


def make_heat_treat_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HeatTreatOperator")


def make_sales_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_fleet_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FleetPlanner")


def make_plant_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantManager")
