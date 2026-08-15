"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. Per PRD §2.1, X-User-ID is opaque for every role except
# PartnerVendorRep, where it must equal the acting PartnerVendor's id.
TEST_USERS = {
    "ops_manager_headers": build_user_headers("test-ops-1", "OpsManager"),
    "ops_manager_b_headers": build_user_headers("test-ops-2", "OpsManager"),
    "tour_manager_headers": build_user_headers("test-tm-1", "TourManager"),
    "logistics_headers": build_user_headers("test-lc-1", "LogisticsCoordinator"),
    "warehouse_tech_headers": build_user_headers("test-wt-1", "WarehouseTech"),
    "warehouse_tech_b_headers": build_user_headers("test-wt-2", "WarehouseTech"),
    # Fallback only — never valid for ownership-gated calls.
    "vendor_rep_headers": build_user_headers("test-vendor-rep-1", "PartnerVendorRep"),
}


def make_vendor_rep_headers(vendor_id: str) -> dict:
    """For PartnerVendorRep (entity_backed:PartnerVendor). Pass the actual
    PartnerVendor.id as vendor_id whenever the call is ownership-gated."""
    return build_user_headers(vendor_id, "PartnerVendorRep")
