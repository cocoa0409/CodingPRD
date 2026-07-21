"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed (Customer, Fitter): ownership/identity checks compare
X-User-ID to a persisted entity id, so tests exercising those calls MUST use the
per-instance builders with the real entity id. The two opaque operator roles
(StoreManager, BillingClerk) use shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity-backed roles: shared constants are a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "fitter_headers": build_user_headers("test-fitter-1", "Fitter"),
    # opaque operator roles: shared constant is the canonical form.
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
}


def make_customer_headers(customer_id: str) -> dict:
    """Headers for a Customer (entity-backed). Pass the actual Customer.id whenever
    the call is ownership-gated (own appointments, orders, exchanges, reminders)."""
    return build_user_headers(customer_id, "Customer")


def make_fitter_headers(fitter_id: str) -> dict:
    """Headers for a Fitter (entity-backed). Pass the actual Fitter.id conducting
    the appointment lifecycle actions."""
    return build_user_headers(fitter_id, "Fitter")


def store_manager_headers() -> dict:
    return TEST_USERS["store_manager_headers"]


def billing_clerk_headers() -> dict:
    return TEST_USERS["billing_clerk_headers"]
