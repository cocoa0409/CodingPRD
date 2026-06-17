"""Pre-built role headers for every role in the PRD (§2.1).

DispatchOperator, BillingClerk, and PlatformAdmin carry opaque operator identities
(X-User-ID not tied to any persisted entity), so their shared constants are the
canonical form. The Customer role is entity-backed: X-User-ID must equal the acting
Customer's id for ownership checks to pass, so ownership-gated Customer calls MUST
use make_customer_headers(customer_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "dispatch_operator_headers": build_user_headers("test-dispatch-1", "DispatchOperator"),
    "billing_clerk_headers": build_user_headers("test-billing-1", "BillingClerk"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # Customer (entity_backed): shared constant is a fallback ONLY for tests that do
    # not exercise ownership (e.g. a 403-forbidden RBAC check that never reaches an
    # ownership comparison).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (hold/resume/closeout/cancel/payment,
    access-visit and packing-supply creation on an agreement the customer owns)."""
    return build_user_headers(user_id, "Customer")
