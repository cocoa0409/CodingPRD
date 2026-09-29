"""Pre-built role headers for every role the PRD recognises.

The five operator roles carry an opaque X-User-ID that is never compared to any
entity id. The Customer role is account-backed: its X-User-ID must be the id of
the acting Account, so ownership-gated calls use make_customer_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "sales_rep_headers": build_user_headers("rep-1", "SalesRep"),
    "warehouse_operator_headers": build_user_headers("op-1", "WarehouseOperator"),
    "hazmat_certifier_headers": build_user_headers("cert-1", "HazmatCertifier"),
    "compliance_officer_headers": build_user_headers("comp-1", "ComplianceOfficer"),
    # Fallback only - never use for a call whose success depends on account scope.
    "customer_headers": build_user_headers("customer-1", "Customer"),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_sales_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_warehouse_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarehouseOperator")


def make_hazmat_certifier_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HazmatCertifier")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_customer_headers(account_id: str) -> dict:
    """For the Customer role. Pass the acting Account's id: every ownership
    check compares the resource's account foreign key to X-User-ID."""
    return build_user_headers(account_id, "Customer")
