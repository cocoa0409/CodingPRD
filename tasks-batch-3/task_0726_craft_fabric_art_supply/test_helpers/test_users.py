"""Pre-built role headers for every role in the PRD.

Customer is entity_backed: X-User-ID is the acting Customer entity's id, and
ownership checks compare a resource's customer_id to X-User-ID. Any Customer
call that touches an owned resource MUST use make_customer_headers(customer_id).

StoreAssociate, StoreManager, and FramingSpecialist are opaque operator roles
whose X-User-ID is not tied to any entity, so the shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Customer: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # Opaque roles: shared constants are the canonical form.
    "store_associate_headers": build_user_headers("test-associate-1", "StoreAssociate"),
    "store_manager_headers": build_user_headers("test-manager-1", "StoreManager"),
    "framing_specialist_headers": build_user_headers("test-framing-1", "FramingSpecialist"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "Customer")


def make_store_associate_headers(user_id: str = "test-associate-1") -> dict:
    return build_user_headers(user_id, "StoreAssociate")


def make_store_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "StoreManager")


def make_framing_specialist_headers(user_id: str = "test-framing-1") -> dict:
    return build_user_headers(user_id, "FramingSpecialist")
