"""Pre-built role headers for every role in the PRD.

There are four roles. Only Customer is entity-backed: when X-User-Role is
Customer, X-User-ID must be the acting Customer's id, and ownership checks
compare the resource's customer_id to it (PRD §2.1). The other three roles
(SalesAssociate, FittingSpecialist, ShopManager) are opaque operator
identifiers not tied to any persisted entity, so shared constants are correct
for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - The three staff roles are opaque: the shared constant is the canonical form.
#  - The customer shared constant is a fallback usable ONLY for tests that do not
#    exercise ownership (e.g. 401/403/404 probes). Ownership-gated customer calls
#    MUST use make_customer_headers(customer["id"]).
TEST_USERS = {
    "sales_associate_headers": build_user_headers("test-sales-associate-1", "SalesAssociate"),
    "fitting_specialist_headers": build_user_headers("test-fitting-specialist-1", "FittingSpecialist"),
    "shop_manager_headers": build_user_headers("test-shop-manager-1", "ShopManager"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_sales_associate_headers(user_id: str = "test-sales-associate-1") -> dict:
    return build_user_headers(user_id, "SalesAssociate")


def make_fitting_specialist_headers(user_id: str = "test-fitting-specialist-1") -> dict:
    return build_user_headers(user_id, "FittingSpecialist")


def make_shop_manager_headers(user_id: str = "test-shop-manager-1") -> dict:
    return build_user_headers(user_id, "ShopManager")
