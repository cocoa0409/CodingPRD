"""Pre-built role headers for every role in the PRD (Section 2.1).

- StoreAdmin is opaque: its X-User-ID is an operator identifier not tied to any
  entity, so the shared constant is the canonical form.
- Customer is entity_backed:Customer — X-User-ID must be the acting Customer.id.
  Use make_customer_headers(customer_id) for ownership-gated calls.
- CommercialBuyer is entity_backed:CommercialAccount — X-User-ID must be the acting
  CommercialAccount.id. Use make_commercial_buyer_headers(account_id).
- Consultant is entity_backed:Consultant — X-User-ID must be the acting Consultant.id.
  Use make_consultant_headers(consultant_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque role — shared constant is canonical
    "store_admin_headers": build_user_headers("test-admin-1", "StoreAdmin"),
    # entity_backed fallbacks — only for non-ownership tests (403-role / 404 / 422)
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "commercial_buyer_headers": build_user_headers("test-buyer-1", "CommercialBuyer"),
    "consultant_headers": build_user_headers("test-consultant-1", "Consultant"),
}


def make_store_admin_headers(user_id: str = "test-admin-1") -> dict:
    """StoreAdmin (opaque). The id is never compared to an entity."""
    return build_user_headers(user_id, "StoreAdmin")


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the acting Customer.id so that
    ownership checks on the customer's own orders / bookings / RMAs pass."""
    return build_user_headers(customer_id, "Customer")


def make_commercial_buyer_headers(account_id: str) -> dict:
    """For CommercialBuyer (entity_backed:CommercialAccount). Pass the acting
    CommercialAccount.id so placement against the buyer's own account passes."""
    return build_user_headers(account_id, "CommercialBuyer")


def make_consultant_headers(consultant_id: str) -> dict:
    """For Consultant (entity_backed:Consultant). Pass the acting Consultant.id so
    completing the consultant's own booking passes."""
    return build_user_headers(consultant_id, "Consultant")
