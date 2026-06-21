"""Pre-built role headers for every role in the PRD (§2.1).

Contractor is entity-backed: X-User-ID must be the acting ContractorAccount.id.
The other five roles are opaque operator identities whose X-User-ID is an
operator string not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for Contractor tests that do
# NOT exercise ownership (e.g. 401/403/404 paths). For any ownership-gated
# Contractor call, build per-instance headers via make_contractor_headers().
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
    # opaque operator roles: shared constant is the canonical form.
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "yard_admin_headers": build_user_headers("test-yardadmin-1", "YardAdmin"),
    "scale_operator_headers": build_user_headers("test-scale-1", "ScaleOperator"),
    "permit_officer_headers": build_user_headers("test-permit-1", "PermitOfficer"),
    "billing_clerk_headers": build_user_headers("test-billing-1", "BillingClerk"),
}


def make_contractor_headers(account_id: str) -> dict:
    """For Contractor (entity_backed:ContractorAccount). Pass the actual
    ContractorAccount.id as X-User-ID whenever the call is ownership-gated
    (booking for itself, cancelling its own order, etc.)."""
    return build_user_headers(account_id, "Contractor")
