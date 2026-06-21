"""Pre-built role headers for every role in the Print & Copy Shop Order API.

Roles (PRD §2.1):
  - ShopStaff           : opaque identity (X-User-ID not tied to any entity)
  - ProductionOperator  : opaque identity
  - Customer            : entity-backed — X-User-ID must equal the acting Customer.id
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#   ShopStaff / ProductionOperator are opaque: the shared constant is canonical.
#   The customer shared constant is a fallback only for tests that do NOT exercise
#   ownership (e.g. 401/403/404 paths). Ownership-gated customer calls MUST use
#   make_customer_headers(customer["id"]).
TEST_USERS = {
    "shop_staff_headers": build_user_headers("test-shop-staff-1", "ShopStaff"),
    "production_operator_headers": build_user_headers("test-prod-op-1", "ProductionOperator"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (confirm/cancel/pay/reorder, proof
    decisions, artwork revision, or any create-on-own-order)."""
    return build_user_headers(customer_id, "Customer")
