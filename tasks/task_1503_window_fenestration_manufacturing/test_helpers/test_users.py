"""Pre-built role headers for every role in the PRD (§2.1 RBAC)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for calls that are not
# ownership-gated (catalog reads, 400/404 probes, cross-dealer denial checks).
TEST_USERS = {
    # DealerRep is entity-backed (X-User-ID is the acting Dealer's id):
    # this shared constant is a fallback for non-ownership scenarios only.
    "dealer_rep_headers": build_user_headers("test-dealer-rep-1", "DealerRep"),
    "plant_engineer_headers": build_user_headers("test-engineer-1", "PlantEngineer"),
    "production_lead_headers": build_user_headers("test-production-lead-1", "ProductionLead"),
    "shipping_coordinator_headers": build_user_headers(
        "test-shipping-coordinator-1", "ShippingCoordinator"
    ),
    "warranty_adjuster_headers": build_user_headers("test-adjuster-1", "WarrantyAdjuster"),
    "plant_manager_headers": build_user_headers("test-plant-manager-1", "PlantManager"),
}


def make_dealer_rep_headers(dealer_id: str) -> dict:
    """DealerRep is entity-backed: X-User-ID must equal the acting Dealer's id.

    Pass the actual Dealer.id whenever the call is ownership-gated
    (own orders, own claims, confirm-delivery, provide-info, appeal).
    """
    return build_user_headers(dealer_id, "DealerRep")
