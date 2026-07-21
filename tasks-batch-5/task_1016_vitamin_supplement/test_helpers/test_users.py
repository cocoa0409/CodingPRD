"""Pre-built role headers for every role in the PRD (§2.1).

StoreOperator is opaque — its X-User-ID is not tied to any entity, so a shared
constant is the canonical form. Customer and Practitioner are entity-backed —
ownership checks compare X-User-ID to the resource's owning FK — so ownership-
gated calls MUST use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator — shared constant is canonical (never ownership-checked).
    "store_operator_headers": build_user_headers("test-operator-1", "StoreOperator"),
    # Entity-backed roles — shared constants are ONLY safe for non-ownership
    # tests (e.g. 401/403/404 on missing/foreign resources). Ownership-gated
    # calls must use the builders below with the real entity id.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "practitioner_headers": build_user_headers("test-practitioner-1", "Practitioner"),
}


def make_store_operator_headers(user_id: str = "test-operator-1") -> dict:
    """StoreOperator headers. X-User-ID is opaque; any value works."""
    return build_user_headers(user_id, "StoreOperator")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the real Customer.id whenever
    the call is ownership-gated (own orders/subscriptions/returns)."""
    return build_user_headers(user_id, "Customer")


def make_practitioner_headers(user_id: str) -> dict:
    """For Practitioner (entity_backed:Practitioner). Pass the real
    Practitioner.id whenever the call is ownership-gated (own recommendations)."""
    return build_user_headers(user_id, "Practitioner")
