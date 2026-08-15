"""Pre-built role headers for every role in the PRD.

All eight roles are opaque: X-User-ID is an operator identifier never compared
to any entity id (PRD section 2.1). Shared constants are therefore the canonical
form; builders exist so change-order segregation-of-duties tests can pin a
specific X-User-ID per call.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "gc_admin_headers": build_user_headers("admin-1", "GCAdmin"),
    "buyout_lead_headers": build_user_headers("bl-1", "BuyoutLead"),
    "ops_manager_headers": build_user_headers("om-1", "OperationsManager"),
    "project_exec_headers": build_user_headers("pe-1", "ProjectExecutive"),
    "project_manager_headers": build_user_headers("pm-1", "ProjectManager"),
    "vice_president_headers": build_user_headers("vp-1", "VicePresident"),
    "estimator_headers": build_user_headers("est-1", "Estimator"),
    "supplier_diversity_headers": build_user_headers("sd-1", "SupplierDiversity"),
}


def make_gc_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GCAdmin")


def make_buyout_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BuyoutLead")


def make_ops_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OperationsManager")


def make_project_exec_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectExecutive")


def make_project_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectManager")


def make_vice_president_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VicePresident")


def make_estimator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Estimator")


def make_supplier_diversity_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupplierDiversity")
