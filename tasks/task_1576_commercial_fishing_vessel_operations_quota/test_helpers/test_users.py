"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (VesselOwner/Captain -> Vessel.id, CrewMember ->
CrewShareContract.id, Observer -> Observer.id) MUST be built per-instance with
the actual entity id whenever the call is ownership-gated. Opaque roles
(ObserverCoordinator, FisheriesRegulator, SettlementClerk) use the shared
constants below directly.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Fallback constants for entity-backed roles — safe only for tests whose
    # outcome does not depend on ownership (e.g. role-denial checks).
    "vessel_owner_headers": build_user_headers("test-owner-1", "VesselOwner"),
    "captain_headers": build_user_headers("test-captain-1", "Captain"),
    "crew_member_headers": build_user_headers("test-crew-1", "CrewMember"),
    "observer_headers": build_user_headers("test-observer-1", "Observer"),
    # Opaque roles — canonical form.
    "coordinator_headers": build_user_headers("test-coordinator-1", "ObserverCoordinator"),
    "regulator_headers": build_user_headers("test-regulator-1", "FisheriesRegulator"),
    "clerk_headers": build_user_headers("test-clerk-1", "SettlementClerk"),
}


def make_vessel_owner_headers(vessel_id: str) -> dict:
    """VesselOwner is entity-backed by Vessel: pass the actual Vessel.id."""
    return build_user_headers(vessel_id, "VesselOwner")


def make_captain_headers(vessel_id: str) -> dict:
    """Captain is entity-backed by Vessel: pass the actual Vessel.id."""
    return build_user_headers(vessel_id, "Captain")


def make_crew_member_headers(crew_contract_id: str) -> dict:
    """CrewMember is entity-backed by CrewShareContract: pass the contract id."""
    return build_user_headers(crew_contract_id, "CrewMember")


def make_observer_headers(observer_id: str) -> dict:
    """Observer is entity-backed by Observer: pass the actual Observer.id."""
    return build_user_headers(observer_id, "Observer")
