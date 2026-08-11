"""Pre-built role headers for every role named in the PRD.

Four roles are operator roles whose identity is opaque: PlatformAdmin,
StagingCoordinator, WarehouseManager and BillingClerk. For those the shared
constant is the canonical form.

Four roles are entity backed: ListingAgent and Seller carry the acting Client
row id, BrokerageAdmin carries the acting Brokerage row id and VendorRep
carries the acting VendorPartner row id. Every ownership-gated call MUST use
the matching per-instance builder with the real row id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the four opaque operator roles, and for tests
# that never exercise an ownership check.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("op-admin-1", "PlatformAdmin"),
    "staging_coordinator_headers": build_user_headers("op-coord-1", "StagingCoordinator"),
    "warehouse_manager_headers": build_user_headers("op-wh-1", "WarehouseManager"),
    "billing_clerk_headers": build_user_headers("op-clerk-1", "BillingClerk"),
    # Entity-backed fallbacks: only for 400/404/403-by-role probes that never
    # reach a party-scope rung.
    "listing_agent_headers": build_user_headers("unbound-agent-1", "ListingAgent"),
    "seller_headers": build_user_headers("unbound-seller-1", "Seller"),
    "brokerage_admin_headers": build_user_headers("unbound-brokerage-1", "BrokerageAdmin"),
    "vendor_rep_headers": build_user_headers("unbound-vendor-1", "VendorRep"),
}

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["staging_coordinator_headers"]
WAREHOUSE = TEST_USERS["warehouse_manager_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


def make_listing_agent_headers(client_id: str) -> dict:
    """ListingAgent acts as a Client row; pass that Client's id."""
    return build_user_headers(client_id, "ListingAgent")


def make_seller_headers(client_id: str) -> dict:
    """Seller acts as a Client row; pass that Client's id."""
    return build_user_headers(client_id, "Seller")


def make_brokerage_admin_headers(brokerage_id: str) -> dict:
    """BrokerageAdmin acts as a Brokerage row; pass that Brokerage's id."""
    return build_user_headers(brokerage_id, "BrokerageAdmin")


def make_vendor_rep_headers(vendor_id: str) -> dict:
    """VendorRep acts as a VendorPartner row; pass that vendor's id."""
    return build_user_headers(vendor_id, "VendorRep")


def headers_without_role(user_id: str = "someone") -> dict:
    """Headers carrying an identity but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_role_only(role: str) -> dict:
    """Headers naming a role but supplying no X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(role_name: str = "WarehouseSupervisor") -> dict:
    """Headers naming a role string the PRD never declares."""
    return {
        "X-User-ID": "op-somebody-1",
        "X-User-Role": role_name,
        "Content-Type": "application/json",
    }
