"""Pre-built role headers for every role in the PRD.

StoreManager, VetTech, and SalesAssociate carry opaque X-User-IDs not tied to
any persisted entity, so their shared constants are the canonical form. The
per-instance builders exist for the two four-eyes controls (recall close and
warranty approve) that compare distinct operator X-User-IDs.

Customer is entity_backed: its X-User-ID is the acting Customer's id. Ownership
checks compare a resource's customer_id to that id, so any ownership-gated call
MUST use make_customer_headers(customer["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# customer ownership.
TEST_USERS = {
    "store_manager_headers": build_user_headers("mgr-1", "StoreManager"),
    "vet_tech_headers": build_user_headers("vet-1", "VetTech"),
    "sales_associate_headers": build_user_headers("sales-1", "SalesAssociate"),
    # Fallback for non-ownership Customer tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_store_manager_headers(user_id: str) -> dict:
    """StoreManager (opaque). Pass a distinct user_id for four-eyes controls
    (recall open vs close, warranty acquirer vs approver)."""
    return build_user_headers(user_id, "StoreManager")


def make_vet_tech_headers(user_id: str) -> dict:
    """VetTech (opaque)."""
    return build_user_headers(user_id, "VetTech")


def make_sales_associate_headers(user_id: str) -> dict:
    """SalesAssociate (opaque)."""
    return build_user_headers(user_id, "SalesAssociate")


def make_customer_headers(user_id: str) -> dict:
    """Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (permits, subscriptions, warranty
    claims, habitat builds)."""
    return build_user_headers(user_id, "Customer")
