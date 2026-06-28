"""Pre-built role headers for every role in the PRD (§2.1).

Four roles: SalesAssociate, Luthier, StoreManager (all opaque operator
identifiers), and Customer (entity-backed — X-User-ID must equal the acting
Customer's ``id`` for ownership-gated reads/actions on the customer's own
resources).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that do NOT exercise
# Customer ownership. The Customer entry here is a fallback only for tests that
# do not need ownership to succeed (it never equals any real Customer.id).
TEST_USERS = {
    "sales_associate_headers": build_user_headers("sales-associate-1", "SalesAssociate"),
    "store_manager_headers": build_user_headers("store-manager-1", "StoreManager"),
    "luthier_headers": build_user_headers("luthier-1", "Luthier"),
    "luthier_2_headers": build_user_headers("luthier-2", "Luthier"),
    "customer_headers": build_user_headers("customer-shared-1", "Customer"),
}


# Per-instance builders ------------------------------------------------------

def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual
    Customer.id as user_id whenever the call is ownership-gated (rent payment,
    buyout, return, layaway payment, special-order/lesson/financing actions on
    the customer's own resources)."""
    return build_user_headers(user_id, "Customer")


def make_luthier_headers(user_id: str) -> dict:
    """For the Luthier role (opaque). The server records the claiming luthier's
    X-User-ID into the ticket's assigned_luthier_id and compares later bench
    actions against it; pass the same id used at claim time."""
    return build_user_headers(user_id, "Luthier")


def make_sales_associate_headers(user_id: str = "sales-associate-1") -> dict:
    return build_user_headers(user_id, "SalesAssociate")


def make_store_manager_headers(user_id: str = "store-manager-1") -> dict:
    return build_user_headers(user_id, "StoreManager")
