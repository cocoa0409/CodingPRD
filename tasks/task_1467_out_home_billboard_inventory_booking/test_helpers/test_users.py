"""Pre-built role headers for every role in the PRD (section 2.1).

All nine roles are opaque: X-User-ID is an operator identifier never compared
against any resource id. Shared constants are therefore the canonical form.
The make_*_headers builders exist so segregation-of-duties tests (posting
verification, make-good approval) can pin a specific X-User-ID per call.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "inventory_manager_headers": build_user_headers("im-1", "InventoryManager"),
    "sales_planner_headers": build_user_headers("sp-1", "SalesPlanner"),
    "sales_manager_headers": build_user_headers("sm-1", "SalesManager"),
    "production_coordinator_headers": build_user_headers("pc-1", "ProductionCoordinator"),
    "field_installer_headers": build_user_headers("installer-1", "FieldInstaller"),
    "operations_auditor_headers": build_user_headers("auditor-1", "OperationsAuditor"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "finance_analyst_headers": build_user_headers("fin-1", "FinanceAnalyst"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_inventory_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InventoryManager")


def make_sales_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalesPlanner")


def make_sales_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalesManager")


def make_production_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionCoordinator")


def make_field_installer_headers(user_id: str) -> dict:
    """FieldInstaller with a pinned X-User-ID (posting-record installer identity)."""
    return build_user_headers(user_id, "FieldInstaller")


def make_operations_auditor_headers(user_id: str) -> dict:
    """OperationsAuditor with a pinned X-User-ID (verifier/proposer identity)."""
    return build_user_headers(user_id, "OperationsAuditor")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_finance_analyst_headers(user_id: str) -> dict:
    """FinanceAnalyst with a pinned X-User-ID (make-good approver identity)."""
    return build_user_headers(user_id, "FinanceAnalyst")
