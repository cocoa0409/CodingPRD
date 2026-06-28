"""Pre-built role headers for every role in the 3PL fulfillment PRD.

Seven of the eight roles carry an `opaque` identity (their X-User-ID is an
operator id not tied to any persisted entity). Only ClientUser is entity_backed:
its X-User-ID must equal the acting Client's id for ownership checks to pass, so
ownership-gated calls MUST use make_client_user_headers(client_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "billing_clerk_headers": build_user_headers("billing-clerk-1", "BillingClerk"),
    # entity_backed: shared constant is a fallback for non-ownership tests only.
    "client_user_headers": build_user_headers("client-user-1", "ClientUser"),
    "receiving_clerk_headers": build_user_headers("receiving-clerk-1", "ReceivingClerk"),
    "wave_planner_headers": build_user_headers("wave-planner-1", "WavePlanner"),
    "pick_operator_headers": build_user_headers("pick-operator-1", "PickOperator"),
    "pack_station_headers": build_user_headers("pack-station-1", "PackStation"),
    "ship_station_headers": build_user_headers("ship-station-1", "ShipStation"),
    "returns_clerk_headers": build_user_headers("returns-clerk-1", "ReturnsClerk"),
}


def make_client_user_headers(client_id: str) -> dict:
    """For ClientUser (entity_backed:Client). Pass the acting Client.id as the
    X-User-ID whenever the call is ownership-gated (SKU onboard/discontinue,
    order import/cancel, and any read scoped to the client's own resources)."""
    return build_user_headers(client_id, "ClientUser")


def make_billing_clerk_headers(user_id: str = "billing-clerk-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_receiving_clerk_headers(user_id: str = "receiving-clerk-1") -> dict:
    return build_user_headers(user_id, "ReceivingClerk")


def make_wave_planner_headers(user_id: str = "wave-planner-1") -> dict:
    return build_user_headers(user_id, "WavePlanner")


def make_pick_operator_headers(user_id: str = "pick-operator-1") -> dict:
    return build_user_headers(user_id, "PickOperator")


def make_pack_station_headers(user_id: str = "pack-station-1") -> dict:
    return build_user_headers(user_id, "PackStation")


def make_ship_station_headers(user_id: str = "ship-station-1") -> dict:
    return build_user_headers(user_id, "ShipStation")


def make_returns_clerk_headers(user_id: str = "returns-clerk-1") -> dict:
    return build_user_headers(user_id, "ReturnsClerk")
