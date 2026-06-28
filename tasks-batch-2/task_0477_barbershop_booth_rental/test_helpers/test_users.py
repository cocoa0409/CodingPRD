"""Pre-built role headers for every role in the PRD (§2.1).

ShopOwner and Receptionist are operator (opaque) roles: X-User-ID is an opaque
identifier never compared to an entity id, so the shared constants are canonical.

Barber and Customer are entity_backed: X-User-ID is the acting entity's id and
ownership checks compare a resource's FK to it. For ownership-gated calls,
use the per-instance builders make_barber_headers / make_customer_headers with
the real entity id. The shared constants are valid only for non-ownership tests
(e.g. 401/403/404 on a resource the actor does not own).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "shop_owner_headers": build_user_headers("test-owner-1", "ShopOwner"),
    "receptionist_headers": build_user_headers("test-reception-1", "Receptionist"),
    # Shared fallbacks for entity-backed roles — non-ownership tests only.
    "barber_headers": build_user_headers("test-barber-1", "Barber"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_barber_headers(barber_id: str) -> dict:
    """Headers for the Barber role (entity_backed:Barber). Pass the real Barber.id
    whenever the call is ownership-gated (own settlements/tickets/schedule reads)."""
    return build_user_headers(barber_id, "Barber")


def make_customer_headers(customer_id: str) -> dict:
    """Headers for the Customer role (entity_backed:Customer). Pass the real
    Customer.id whenever the call is ownership-gated (own appointments, queue,
    profile, subscribe)."""
    return build_user_headers(customer_id, "Customer")
