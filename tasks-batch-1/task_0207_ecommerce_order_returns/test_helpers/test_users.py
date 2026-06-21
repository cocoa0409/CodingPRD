"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
  - Customer is entity_backed: X-User-ID is the acting Customer's id, and
    ownership checks compare resource.customer_id to X-User-ID. Every
    ownership-gated Customer call MUST use make_customer_headers(customer_id).
  - Anonymous, WarehouseOperator, StoreAdmin are opaque: X-User-ID is an
    arbitrary identifier never compared to any persisted entity's id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Customer tests that do NOT
# exercise ownership (e.g. 400/404 paths reached before the ownership check, or
# cross-customer denial where the wrong id is intentional).
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "warehouse_operator_headers": build_user_headers("op-1", "WarehouseOperator"),
    "store_admin_headers": build_user_headers("admin-1", "StoreAdmin"),
    # Fallback constant for Customer — only for non-ownership scenarios.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (checkout, add line, open
    return, cancel return)."""
    return build_user_headers(user_id, "Customer")


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_warehouse_operator_headers(user_id: str = "op-1") -> dict:
    return build_user_headers(user_id, "WarehouseOperator")


def make_store_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "StoreAdmin")
