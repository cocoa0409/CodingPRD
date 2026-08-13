"""Pre-built role headers for every role in the PRD (§2.1).

FarmManager, SalesRep, HarvestSupervisor, and FleetManager use opaque operator
identifiers (the server does not compare X-User-ID against any resource id).
Customer is entity-backed: X-User-ID must be the acting Customer's id whenever
the call is ownership-gated, so tests must build those headers with
make_customer_headers(customer["id"]) after creating the customer.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "farm_manager_headers": build_user_headers("test-farm-manager-1", "FarmManager"),
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "SalesRep"),
    "harvest_supervisor_headers": build_user_headers(
        "test-harvest-supervisor-1", "HarvestSupervisor"
    ),
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
    # Entity-backed role: fallback for non-ownership calls only (e.g. role
    # denial where the role itself is rejected before any ownership check).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity-backed). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (own orders, install progress,
    warranty claims, watering logs)."""
    return build_user_headers(user_id, "Customer")
