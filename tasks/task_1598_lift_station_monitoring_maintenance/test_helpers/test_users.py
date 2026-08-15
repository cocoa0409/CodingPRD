"""Pre-built role headers for every role in PRD §2.1."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise Operator-entity ownership (arrive / clear / permit issue-close).
TEST_USERS = {
    "utility_admin_headers": build_user_headers("test-admin-1", "UtilityAdmin"),
    "operations_supervisor_headers": build_user_headers("test-supervisor-1", "OperationsSupervisor"),
    "on_call_operator_headers": build_user_headers("test-oncall-1", "OnCallOperator"),
    # entity_backed:Operator — fallback for non-ownership calls only.
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    "maintenance_planner_headers": build_user_headers("test-planner-1", "MaintenancePlanner"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "capital_program_manager_headers": build_user_headers("test-cpm-1", "CapitalProgramManager"),
    "scada_webhook_headers": build_user_headers("test-scada-1", "ScadaWebhook"),
    "regulator_portal_headers": build_user_headers("test-regulator-1", "RegulatorPortal"),
}


def make_operator_headers(user_id: str) -> dict:
    """For Operator (entity_backed:Operator). Pass the actual Operator.id as
    user_id whenever the call is ownership-gated (arrive/clear on a dispatched
    ticket, permit issue/close by the named supervisor)."""
    return build_user_headers(user_id, "Operator")
