"""Pre-built role headers for every role in the PRD (§2.1).

All eight roles use the opaque identity model: X-User-ID is an opaque operator
identifier never compared to any entity's id, so shared constants are safe for
every role. Named operator ids matter only where segregation-of-duties compares
X-User-ID against recorded completer/verifier/recorder identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "plant_manager_headers": build_user_headers("pm-1", "PlantManager"),
    "shift_supervisor_headers": build_user_headers("sup-1", "ShiftSupervisor"),
    "receiving_clerk_headers": build_user_headers("rcv-1", "ReceivingClerk"),
    "line_operator_headers": build_user_headers("op-1", "LineOperator"),
    "qa_technician_headers": build_user_headers("qa-1", "QATechnician"),
    "sanitation_lead_headers": build_user_headers("san-1", "SanitationLead"),
    "usda_inspector_headers": build_user_headers("usda-1", "USDAInspector"),
    "order_planner_headers": build_user_headers("plan-1", "OrderPlanner"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for a specific operator id in a role — required wherever
    segregation-of-duties compares X-User-ID against recorded identifiers."""
    return build_user_headers(user_id, role)


def make_plant_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantManager")


def make_shift_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ShiftSupervisor")


def make_receiving_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ReceivingClerk")


def make_line_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LineOperator")


def make_qa_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QATechnician")


def make_sanitation_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SanitationLead")


def make_usda_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "USDAInspector")


def make_order_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OrderPlanner")
