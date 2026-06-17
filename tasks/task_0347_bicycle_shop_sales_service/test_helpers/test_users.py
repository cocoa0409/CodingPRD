"""Pre-built role headers for the four roles the PRD recognises (PRD §2.1).

PRD §2.1: `SalesAssociate`, `ServiceAdvisor`, and `ShopManager` are operator
roles whose identities are opaque — the server records `X-User-ID` but never
compares it to any persisted entity's `id`. Their shared constants below are
the canonical form for every call those roles make.

The `Customer` role is entity-backed: when `X-User-Role` is `Customer`,
`X-User-ID` is the `id` of the acting `Customer` entity. The one ownership-
gated mutation is approving the quote on one's own service ticket — the acting
`X-User-ID` must equal the ticket's `customer_id`, else `ERR_NOT_RESOURCE_OWNER`.
For any such call use ``make_customer_headers(customer_id)`` with the real
Customer.id; the shared constant is a fallback for non-ownership cases only
(e.g. submitting a warranty claim, reads, or 403/404 negative tests).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "sales_associate_headers": build_user_headers("sales-associate-1", "SalesAssociate"),
    "service_advisor_headers": build_user_headers("service-advisor-1", "ServiceAdvisor"),
    "shop_manager_headers": build_user_headers("shop-manager-1", "ShopManager"),
    # Customer (entity_backed): fallback only — ownership tests must use the builder.
    "customer_headers": build_user_headers("customer-fallback-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer-role calls whose success depends on owning the resource
    (PRD §2.1: a Customer approving a ticket must have X-User-ID == the
    ticket's customer_id). Pass the real Customer.id so the ownership check
    passes."""
    return build_user_headers(customer_id, "Customer")


def make_sales_associate_headers(user_id: str = "sales-associate-1") -> dict:
    """Per-instance builder for the opaque SalesAssociate role."""
    return build_user_headers(user_id, "SalesAssociate")


def make_service_advisor_headers(user_id: str = "service-advisor-1") -> dict:
    """Per-instance builder for the opaque ServiceAdvisor role."""
    return build_user_headers(user_id, "ServiceAdvisor")


def make_shop_manager_headers(user_id: str = "shop-manager-1") -> dict:
    """Per-instance builder for the opaque ShopManager role."""
    return build_user_headers(user_id, "ShopManager")
