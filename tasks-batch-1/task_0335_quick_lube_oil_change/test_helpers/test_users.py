"""Pre-built role headers for every role in the Quick Lube & Oil Change PRD (§2.1).

ShopManager and ServiceAdvisor are opaque roles: X-User-ID is not tied to any entity,
so the shared constants are the canonical form.

Technician and FleetManager are entity-backed: X-User-ID must equal the acting
Technician.id / FleetAccount.id. For ownership-gated calls, build per-instance headers
with make_technician_headers(tech_id) / make_fleet_manager_headers(account_id) — never
fall back to a shared constant for those calls (a fixed string never equals any real id,
so every ownership check would reject the request).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles (canonical) + entity-backed fallbacks for tests
# that do NOT exercise ownership (e.g. 400/403/404 paths).
TEST_USERS = {
    "shop_manager_headers": build_user_headers("test-shop-manager-1", "ShopManager"),
    "service_advisor_headers": build_user_headers("test-service-advisor-1", "ServiceAdvisor"),
    # entity-backed fallbacks (non-ownership tests only):
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
}


def make_technician_headers(technician_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id whenever
    the call is ownership-gated (claim, start, lines, mark-ready, etc.)."""
    return build_user_headers(technician_id, "Technician")


def make_fleet_manager_headers(fleet_account_id: str) -> dict:
    """For FleetManager (entity_backed:FleetAccount). Pass the actual FleetAccount.id
    whenever the call reads or acts within that fleet account's data."""
    return build_user_headers(fleet_account_id, "FleetManager")
