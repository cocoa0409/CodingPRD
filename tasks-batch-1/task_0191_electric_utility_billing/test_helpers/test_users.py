"""Pre-built role headers for every role in the Electric Utility Billing PRD.

Four roles (PRD §2.1). BillingOperator, FieldDispatcher, and
AssistanceCaseworker carry an opaque identity: their X-User-ID is an operator
identifier never compared to any entity, so the shared constants below are the
canonical form. Customer is entity-backed: when X-User-Role is Customer,
X-User-ID is the acting Account.id, and ownership checks compare a resource's
account_id to it. For ownership-gated Customer calls (e.g. posting a payment
against one's own account), use make_customer_headers(account_id) with the
real Account.id; the shared "customer_headers" constant is a fallback only for
non-ownership paths (auth/forbidden/not-found checks).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constant is canonical.
    "operator_headers": build_user_headers("test-operator-1", "BillingOperator"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "FieldDispatcher"),
    "caseworker_headers": build_user_headers("test-caseworker-1", "AssistanceCaseworker"),
    # Entity-backed Customer — shared fallback for non-ownership paths only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(account_id: str) -> dict:
    """For Customer (entity_backed:Account). Pass the acting Account.id as
    X-User-ID whenever the call is ownership-gated (e.g. POST /payments against
    one's own account)."""
    return build_user_headers(account_id, "Customer")


def make_role_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary (possibly unrecognized) role string. Used
    by negative authentication tests."""
    return build_user_headers(user_id, role)
