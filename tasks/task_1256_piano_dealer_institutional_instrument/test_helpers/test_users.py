"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (PlatformAdmin .. FinanceOfficer) use shared constants. The two
entity-backed roles (Customer, Consignor) additionally get per-instance builder
functions: any ownership-gated call MUST use the builder with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
    "sales_associate_headers": build_user_headers("test-sales-associate-1", "SalesAssociate"),
    "bid_officer_headers": build_user_headers("test-bid-officer-1", "InstitutionalBidOfficer"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "service_coordinator_headers": build_user_headers("test-service-coordinator-1", "ServiceCoordinator"),
    "finance_officer_headers": build_user_headers("test-finance-officer-1", "FinanceOfficer"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "consignor_headers": build_user_headers("test-consignor-1", "Consignor"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity-backed). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (appraisal counter/accept/decline,
    own-order reads, confirm-installation)."""
    return build_user_headers(user_id, "Customer")


def make_consignor_headers(user_id: str) -> dict:
    """For Consignor (entity-backed). Pass the actual Consignor.id as user_id
    whenever the call is ownership-gated (own record / own instruments)."""
    return build_user_headers(user_id, "Consignor")


def make_bid_officer_headers(user_id: str) -> dict:
    """For InstitutionalBidOfficer with a specific identity (drives the
    prepared_by_user_id recorded on created bid packages)."""
    return build_user_headers(user_id, "InstitutionalBidOfficer")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For ComplianceOfficer with a specific identity (segregation-of-duties
    checks compare it against a bid's prepared_by_user_id)."""
    return build_user_headers(user_id, "ComplianceOfficer")
