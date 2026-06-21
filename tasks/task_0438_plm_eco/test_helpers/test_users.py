"""Pre-built role headers for every role in the PRD.

All roles in this domain use an opaque X-User-ID — it is an operator identifier
never compared to any entity's id (PRD 2.1). It IS, however, recorded on certain
entities (submitted_by_user_id, created_by_user_id, decided_by_user_id) and later
compared against the acting X-User-ID for the segregation-of-duties and
task-assignment checks. Tests that exercise those checks must control the exact
operator id used at create-time and at decision-time, so per-id builder functions
are provided alongside the shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for any test that does not depend on a specific
# recorded operator id (creation, retrieval, RBAC denials, missing-resource).
TEST_USERS = {
    "designer_headers": build_user_headers("designer-1", "Designer"),
    "change_admin_headers": build_user_headers("ca1", "ChangeAdmin"),
    "approver_headers": build_user_headers("ap1", "Approver"),
    "quality_engineer_headers": build_user_headers("qe-1", "QualityEngineer"),
    "supplier_manager_headers": build_user_headers("sm-1", "SupplierManager"),
    "viewer_headers": build_user_headers("viewer-1", "Viewer"),
}


# Per-operator-id builders. Use these whenever a test must thread a specific
# X-User-ID through a workflow (ECO creator vs. approver for segregation of
# duties; task assignee for the assignment check).
def make_designer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Designer")


def make_change_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ChangeAdmin")


def make_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Approver")


def make_quality_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityEngineer")


def make_supplier_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupplierManager")


def make_viewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Viewer")
