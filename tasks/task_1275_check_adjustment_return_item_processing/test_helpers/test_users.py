"""Pre-built role headers for every role in the PRD (§2.1).

Five roles are opaque: their X-User-ID is not tied to any persisted entity.
The Customer role is entity-backed: X-User-ID must be the acting
DepositorAccount's id, so ownership-gated calls MUST use
make_customer_headers(account["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, etc.).
TEST_USERS = {
    "operations_admin_headers": build_user_headers("test-ops-admin-1", "OperationsAdmin"),
    "item_processor_headers": build_user_headers("test-item-processor-1", "ItemProcessor"),
    "adjustment_analyst_headers": build_user_headers("test-analyst-1", "AdjustmentAnalyst"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "customer_service_headers": build_user_headers("test-customer-service-1", "CustomerService"),
    # Fallback only for Customer tests that do not exercise ownership.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_operations_admin_headers(user_id: str) -> dict:
    """OperationsAdmin headers with a specific opaque operator id."""
    return build_user_headers(user_id, "OperationsAdmin")


def make_item_processor_headers(user_id: str) -> dict:
    """ItemProcessor headers with a specific opaque operator id."""
    return build_user_headers(user_id, "ItemProcessor")


def make_adjustment_analyst_headers(user_id: str) -> dict:
    """AdjustmentAnalyst headers with a specific opaque analyst id (e.g. analyst-1)."""
    return build_user_headers(user_id, "AdjustmentAnalyst")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer headers with a specific opaque operator id."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_customer_service_headers(user_id: str) -> dict:
    """CustomerService headers with a specific opaque operator id."""
    return build_user_headers(user_id, "CustomerService")


def make_customer_headers(account_id: str) -> dict:
    """Customer headers (entity-backed). Pass the actual DepositorAccount.id
    whenever the call is ownership-gated."""
    return build_user_headers(account_id, "Customer")
