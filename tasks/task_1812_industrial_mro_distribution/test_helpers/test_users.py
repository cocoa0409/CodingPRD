"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for entity-backed roles only in
# tests that do not exercise ownership (400-shape checks, 404 checks, role denials).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "DistributionAdmin"),
    # entity_backed:CustomerAccount — fallback for non-ownership tests only.
    "buyer_headers": build_user_headers("test-buyer-1", "CustomerBuyer"),
    # entity_backed:CustomerAccount — fallback for non-ownership tests only.
    "approver_headers": build_user_headers("test-approver-1", "CustomerApprover"),
    "branch_manager_headers": build_user_headers("test-branch-1", "BranchManager"),
    "vendor_rep_headers": build_user_headers("test-vendor-1", "VendorRep"),
}


def make_buyer_headers(customer_id: str) -> dict:
    """For CustomerBuyer (entity_backed:CustomerAccount). Pass the actual
    CustomerAccount.id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(customer_id, "CustomerBuyer")


def make_approver_headers(customer_id: str) -> dict:
    """For CustomerApprover (entity_backed:CustomerAccount). Pass the actual
    CustomerAccount.id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(customer_id, "CustomerApprover")
