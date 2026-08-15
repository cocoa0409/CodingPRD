"""Pre-built role headers for every role in the PRD (§2.1).

Every role's X-User-ID is an opaque operator identifier (PRD §2.1: "It is never
compared to any entity's id"), so shared constants are canonical. Segregation-
of-duties scenarios pick distinct user ids from the per-role constants below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator ids per role (several per role where workflows compare
# recorded actors against the caller: creator vs approver, reporter vs
# confirmer, screener vs adjudicator, grader vs releaser, closer vs finalizer).
TEST_USERS = {
    "plant_manager_headers": build_user_headers("pmgr-1", "PlantManager"),
    "plant_manager_2_headers": build_user_headers("pmgr-9", "PlantManager"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "compliance_officer_2_headers": build_user_headers("co-2", "ComplianceOfficer"),
    "compliance_officer_3_headers": build_user_headers("co-3", "ComplianceOfficer"),
    "regulator_headers": build_user_headers("reg-1", "Regulator"),
    "procurement_manager_headers": build_user_headers("pm-1", "ProcurementManager"),
    "procurement_manager_2_headers": build_user_headers("pm-2", "ProcurementManager"),
    "route_dispatcher_headers": build_user_headers("rd-1", "RouteDispatcher"),
    "scalehouse_operator_headers": build_user_headers("sh-1", "ScalehouseOperator"),
    "scalehouse_operator_2_headers": build_user_headers("sh-2", "ScalehouseOperator"),
    "production_supervisor_headers": build_user_headers("ps-1", "ProductionSupervisor"),
    "quality_lab_tech_headers": build_user_headers("ql-1", "QualityLabTech"),
    "sales_manager_headers": build_user_headers("sm-1", "SalesManager"),
    "finance_analyst_headers": build_user_headers("fa-1", "FinanceAnalyst"),
    "finance_analyst_2_headers": build_user_headers("fa-2", "FinanceAnalyst"),
    "any_headers": build_user_headers("reader-1", "Any"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary operator id under a declared role.

    Used when a workflow must pin the exact X-User-ID (e.g. a segregation-of-
    duties check compares the caller against a recorded actor field).
    """
    return build_user_headers(user_id, role)
