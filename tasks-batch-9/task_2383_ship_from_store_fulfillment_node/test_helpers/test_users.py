"""Pre-built role headers for the four roles the PRD declares.

NetworkPlanner, CarrierCoordinator and CustomerCare carry an opaque
``X-User-ID``, so a shared constant is the canonical form for them.

StoreAssociate is different: its ``X-User-ID`` must be the id of the node it
acts for. Any ownership-gated call therefore MUST build its headers with
``make_store_associate_headers(store["id"])``; the shared constant below is
only for calls where no node ownership is evaluated (bad payloads, unknown
ids, forbidden-role probes).
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "network_planner_headers": build_user_headers(
        "test-network-planner-1", "NetworkPlanner"
    ),
    # StoreAssociate identity is node-backed: this constant never equals a
    # real Store.id, so use it only for non-ownership scenarios.
    "store_associate_headers": build_user_headers(
        "test-store-associate-1", "StoreAssociate"
    ),
    "carrier_coordinator_headers": build_user_headers(
        "test-carrier-coordinator-1", "CarrierCoordinator"
    ),
    "customer_care_headers": build_user_headers("test-customer-care-1", "CustomerCare"),
}


def make_store_associate_headers(store_id: str) -> dict:
    """Headers for a StoreAssociate acting for the node ``store_id``.

    Pass the actual Store id whenever the call is node-scope checked
    (accept / reject / pick / pack / ship, inventory adjustments, restock).
    """
    return build_user_headers(store_id, "StoreAssociate")


def make_network_planner_headers(user_id: str = "test-network-planner-1") -> dict:
    return build_user_headers(user_id, "NetworkPlanner")


def make_carrier_coordinator_headers(
    user_id: str = "test-carrier-coordinator-1",
) -> dict:
    return build_user_headers(user_id, "CarrierCoordinator")


def make_customer_care_headers(user_id: str = "test-customer-care-1") -> dict:
    return build_user_headers(user_id, "CustomerCare")


PLANNER = TEST_USERS["network_planner_headers"]
CARRIER = TEST_USERS["carrier_coordinator_headers"]
CARE = TEST_USERS["customer_care_headers"]
