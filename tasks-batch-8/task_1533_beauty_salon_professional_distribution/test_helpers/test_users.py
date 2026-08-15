"""Pre-built role headers for every role in the PRD (§2.1).

DistributionAdmin, ComplianceOfficer, and WarehouseOperator are opaque roles:
the server does not compare their X-User-ID to any entity's id, so the shared
constants are canonical (per-user builders still exist for the diversion
segregation-of-duties rule, which compares X-User-ID strings).

SalesConsultant and SalonBuyer are entity-backed (their X-User-ID is the id of
the acting SalesConsultant / SalonAccount): any ownership-gated or
identity-resolved call MUST build headers with the actual entity id via
make_sales_consultant_headers(consultant_id) / make_salon_buyer_headers(salon_id).
The shared constants for those two roles are fallbacks for non-ownership tests
only (e.g., RBAC denial checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "admin_headers": build_user_headers("test-admin-1", "DistributionAdmin"),
    "compliance_officer_headers": build_user_headers(
        "test-officer-1", "ComplianceOfficer"
    ),
    "warehouse_operator_headers": build_user_headers(
        "test-warehouse-1", "WarehouseOperator"
    ),
    # Entity-backed roles — fallback for non-ownership tests only.
    "sales_consultant_headers": build_user_headers(
        "test-consultant-1", "SalesConsultant"
    ),
    "salon_buyer_headers": build_user_headers("test-buyer-1", "SalonBuyer"),
}


def make_distribution_admin_headers(user_id: str = "test-admin-1") -> dict:
    """DistributionAdmin is opaque; any identifier works."""
    return build_user_headers(user_id, "DistributionAdmin")


def make_compliance_officer_headers(user_id: str = "test-officer-1") -> dict:
    """ComplianceOfficer is opaque; pass a distinct user_id when the
    segregation-of-duties rule (filer != adjudicator) is exercised."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_warehouse_operator_headers(user_id: str = "test-warehouse-1") -> dict:
    """WarehouseOperator is opaque; any identifier works."""
    return build_user_headers(user_id, "WarehouseOperator")


def make_sales_consultant_headers(user_id: str) -> dict:
    """SalesConsultant is entity_backed:SalesConsultant. Pass the actual
    SalesConsultant.id as user_id whenever the call is ownership-gated or
    the id must resolve to an existing consultant."""
    return build_user_headers(user_id, "SalesConsultant")


def make_salon_buyer_headers(user_id: str) -> dict:
    """SalonBuyer is entity_backed:SalonAccount. Pass the actual
    SalonAccount.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "SalonBuyer")
