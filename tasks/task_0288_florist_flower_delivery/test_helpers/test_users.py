"""Pre-built role headers for every role in the PRD (§2.1).

Customer and Florist are entity-backed: X-User-ID is the id of the acting
Customer / Florist row, and ownership checks compare it to the resource's owner
foreign key. For ownership-gated calls a per-instance builder MUST be used with
the real entity id. Dispatcher and CatalogAdmin are opaque operator roles whose
X-User-ID is not compared to any entity id, so a shared constant is canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# Dispatcher and CatalogAdmin are opaque operators (PRD §2.1) — shared constant
# is the canonical form. The Customer/Florist shared constants are fallbacks for
# non-ownership tests only (e.g. 401/403-on-role, 404-on-missing-resource);
# ownership-gated calls MUST use make_customer_headers / make_florist_headers.
TEST_USERS = {
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "catalog_admin_headers": build_user_headers("test-catalog-admin-1", "CatalogAdmin"),
    "customer_headers": build_user_headers("test-customer-fallback-1", "Customer"),
    "florist_headers": build_user_headers("test-florist-fallback-1", "Florist"),
}


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    """Dispatcher is opaque; X-User-ID is an operator identifier (PRD §2.1)."""
    return build_user_headers(user_id, "Dispatcher")


def make_catalog_admin_headers(user_id: str = "test-catalog-admin-1") -> dict:
    """CatalogAdmin is opaque; X-User-ID is an operator identifier (PRD §2.1)."""
    return build_user_headers(user_id, "CatalogAdmin")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated on Order/Claim/Schedule (PRD §2.1)."""
    return build_user_headers(user_id, "Customer")


def make_florist_headers(user_id: str) -> dict:
    """For Florist (entity_backed). Pass the actual Florist.id as user_id
    whenever the call is ownership-gated on a WireFulfillment (PRD §2.1)."""
    return build_user_headers(user_id, "Florist")
