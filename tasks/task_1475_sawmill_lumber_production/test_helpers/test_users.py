"""Pre-built role headers for every role in the PRD RBAC model.

Per PRD Section 2.1: for every role, X-User-ID is an opaque operator
identifier not tied to any persisted entity; access control is purely
role-based, so the shared constants below are canonical for all calls.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "scaler_headers": build_user_headers("test-scaler-1", "Scaler"),
    "sawyer_headers": build_user_headers("test-sawyer-1", "Sawyer"),
    "kiln_operator_headers": build_user_headers("test-kiln-operator-1", "KilnOperator"),
    "grader_headers": build_user_headers("test-grader-1", "Grader"),
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "SalesRep"),
    "mill_manager_headers": build_user_headers("test-mill-manager-1", "MillManager"),
}


# Per-role builders (all roles are opaque per PRD Section 2.1; a default
# stable id is supplied so callers may omit user_id entirely).
def make_scaler_headers(user_id: str = "test-scaler-1") -> dict:
    return build_user_headers(user_id, "Scaler")


def make_sawyer_headers(user_id: str = "test-sawyer-1") -> dict:
    return build_user_headers(user_id, "Sawyer")


def make_kiln_operator_headers(user_id: str = "test-kiln-operator-1") -> dict:
    return build_user_headers(user_id, "KilnOperator")


def make_grader_headers(user_id: str = "test-grader-1") -> dict:
    return build_user_headers(user_id, "Grader")


def make_sales_rep_headers(user_id: str = "test-sales-rep-1") -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_mill_manager_headers(user_id: str = "test-mill-manager-1") -> dict:
    return build_user_headers(user_id, "MillManager")
