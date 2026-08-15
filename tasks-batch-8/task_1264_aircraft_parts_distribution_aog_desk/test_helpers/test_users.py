"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. For CustomerContact (entity-backed by Customer) prefer
# make_customer_headers(customer_id) whenever the call is ownership-gated.
TEST_USERS = {
    "aog_desk_agent_headers": build_user_headers("test-agent-1", "AogDeskAgent"),
    # Fallback only for non-ownership CustomerContact usage; ownership-gated
    # calls MUST use make_customer_headers(customer_id).
    "customer_contact_headers": build_user_headers("test-contact-1", "CustomerContact"),
    "warehouse_operator_headers": build_user_headers("test-warehouse-1", "WarehouseOperator"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "finance_controller_headers": build_user_headers("test-finance-1", "FinanceController"),
    "warranty_adjuster_headers": build_user_headers("test-adjuster-1", "WarrantyAdjuster"),
    "warranty_approver_headers": build_user_headers("test-approver-1", "WarrantyApprover"),
    "platform_ops_headers": build_user_headers("test-ops-1", "PlatformOps"),
}


def make_customer_headers(customer_id: str) -> dict:
    """CustomerContact identity is entity-backed (PRD §2.1): X-User-ID must be the
    Customer.id. Pass the actual customer id whenever the call is ownership-gated
    (aog create/cancel, quote accept/reject, warranty claims, return authorizations)."""
    return build_user_headers(customer_id, "CustomerContact")


def make_adjuster_headers(user_id: str) -> dict:
    """WarrantyAdjuster opaque operator id — recorded as reviewed_by on review."""
    return build_user_headers(user_id, "WarrantyAdjuster")


def make_approver_headers(user_id: str) -> dict:
    """WarrantyApprover opaque operator id — must differ from reviewed_by (PRD §3.8)."""
    return build_user_headers(user_id, "WarrantyApprover")
