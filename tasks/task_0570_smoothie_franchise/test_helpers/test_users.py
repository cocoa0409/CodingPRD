"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin and Anonymous carry opaque, non-entity identifiers, so their
shared constants are the canonical form. Franchisee, StoreStaff, and Customer
are entity-backed: ownership checks compare X-User-ID against a real entity id,
so ownership-gated calls MUST use the per-instance builders below with the
actual entity's id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — the identifier is not tied to a persisted entity.
    "platform_admin_headers": build_user_headers("admin-op-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("anon-op-1", "Anonymous"),
    # Entity-backed roles — these shared constants are a fallback for tests that
    # do NOT exercise ownership (e.g. a 400/404 before the ownership gate).
    "franchisee_headers": build_user_headers("franchisee-fallback", "Franchisee"),
    "store_staff_headers": build_user_headers("store-fallback", "StoreStaff"),
    "customer_headers": build_user_headers("customer-fallback", "Customer"),
}

# Requests that must pass authentication as no principal — used for the
# missing-headers path (ERR_UNAUTHENTICATED).
NO_AUTH_HEADERS: dict = {}


def make_franchisee_headers(franchisee_id: str) -> dict:
    """For Franchisee (entity_backed:Franchisee). Pass the actual Franchisee.id."""
    return build_user_headers(franchisee_id, "Franchisee")


def make_store_staff_headers(store_id: str) -> dict:
    """For StoreStaff (entity_backed:Store). Pass the actual Store.id."""
    return build_user_headers(store_id, "StoreStaff")


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id."""
    return build_user_headers(customer_id, "Customer")
