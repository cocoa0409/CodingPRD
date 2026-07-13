"""Vehicle-run lifecycle: the dispatch cascade to EN_ROUTE and the run manifest.

Queue A (Difficulty): transitive_cascade / run dispatch -> EN_ROUTE (depth-2).
Queue B (Corner): manifest reverse-reachability.
"""
from test_helpers import validate_success, validate_paginated, TEST_USERS
import test_helpers as th

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ==========================================================================
# Difficulty A — dispatch cascades SCHEDULED trip to EN_ROUTE
# ==========================================================================
def _dispatch_run_with_scheduled_trip(api):
    base = th.scenario_certified_rider_zone_run(api)
    rider_id = base["rider"]["id"]
    za = base["zone_a"]["id"]
    run_id = base["run"]["id"]
    # Opening the run is a mutation, so it increments the run's version (PRD §2.1:
    # version "increments by one on every mutation of the resource"). Re-observe the
    # post-open version before accepting, or the accept trips ERR_STALE_RUN_VERSION.
    opened = validate_success(api.open_run(run_id, DISPATCHER))
    trip = th.create_offered_trip(api, rider_id, za, za)
    th.accept_trip(api, trip["id"], rider_id, run_id, opened["version"])
    api.dispatch_run(run_id, DISPATCHER)
    return run_id, trip["id"]


def test_dispatch_advances_run_to_dispatched(api):
    """PRD §3.7: "A dispatcher creates a run in `PLANNED`, opens it for booking (advancing
    `PLANNED → OPEN`), and later dispatches it (advancing `OPEN → DISPATCHED`)."

    Design: Difficulty/transitive_cascade/run_dispatch_cascades_scheduled_trip_to_en_route_depth2
    """
    run_id, _ = _dispatch_run_with_scheduled_trip(api)
    run = validate_success(api.get_run(run_id, DISPATCHER))
    assert run["status"] == "DISPATCHED"


def test_dispatch_cascades_scheduled_trip_to_en_route(api):
    """PRD §3.7: "Dispatching a run cascades to its trips: every trip assigned to the run
    that is currently `SCHEDULED` advances from `SCHEDULED` to `EN_ROUTE`, and the run's
    `version` is incremented by one."

    Design: Difficulty/transitive_cascade/run_dispatch_cascades_scheduled_trip_to_en_route_depth2
    """
    _, trip_id = _dispatch_run_with_scheduled_trip(api)
    trip = validate_success(api.get_trip(trip_id, DISPATCHER))
    assert trip["status"] == "EN_ROUTE"


# ==========================================================================
# Corner B — manifest reverse-reachability
# ==========================================================================
def test_run_manifest_lists_assigned_trip(api):
    """PRD §3.7: "A run's manifest lists the trips assigned to it (those whose
    `assigned_run_id` is the run), and the run read exposes `available_ambulatory_seats`,
    `available_wheelchair_positions`, and `version`."

    Design: Corner/endpoints/vehicle_run_manifest_reverse_reachability
    """
    base = th.scenario_scheduled_trip(api)
    resp = api.get_manifest(base["run"]["id"], DISPATCHER)
    data, meta = validate_paginated(resp)
    assert any(t["id"] == base["trip"]["id"] for t in data)
