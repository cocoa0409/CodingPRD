"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles: shared constants are the canonical form.
    "line_operator_headers": build_user_headers("test-operator-1", "LineOperator"),
    "lab_chemist_headers": build_user_headers("test-chemist-1", "LabChemist"),
    "qc_inspector_headers": build_user_headers("test-qc-1", "QCInspector"),
    "ehs_officer_headers": build_user_headers("test-ehs-1", "EHSOfficer"),
    "shop_manager_headers": build_user_headers("test-manager-1", "ShopManager"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (work order create/get/list/cancel/amend)."""
    return build_user_headers(user_id, "Customer")


def make_line_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LineOperator")


def make_lab_chemist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LabChemist")


def make_qc_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QCInspector")


def make_ehs_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EHSOfficer")


def make_shop_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ShopManager")
