"""Accepting an offer onto a run: the ordered precondition checks (run state, OCC,
wheelchair/seat capacity, rider overlap) and the successful-booking side effects.

Queue A (Difficulty): priority_pair_validation_conflict (safety>constraint),
cross_entity_state_dependency (run status), resource_temporal_overlap
(rider overlap, wheelchair capacity).
Queue B (Corner): OCC stale/correct, immediate scheduled-window consistency.
"""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
import test_helpers as th

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ==========================================================================
# Difficulty A — priority_pair: wheelchair (safety) beats seat (constraint)
# ==========================================================================
def _accept_wheelchair_and_seat_both_short(api):
    base = th.scenario_certified_rider_zone_run(api, seats=0, positions=0,
                                                mobility_device="POWER_WHEELCHAIR",
                                                assessed_mobility_device="POWER_WHEELCHAIR")
    rider_id = base["rider"]["id"]
    za = base["zone_a"]["id"]
    trip = th.create_offered_trip(api, rider_id, za, za, needs_wheelchair=True, num_companions=1)
    resp = th.accept_trip(api, trip["id"], rider_id, base["run"]["id"], base["run"]["version"])
    return resp, trip["id"]


def test_accept_wheelchair_shortage_beats_seat_shortage(api):
    """PRD §3.6: "a wheelchair position must be free over the trip's interval when the
    trip needs securement (else `ERR_NO_WHEELCHAIR_CAPACITY`, HTTP 409); enough ambulatory
    seats must be free over the interval (else `ERR_NO_SEAT_CAPACITY`, HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/accept_safety_wheelchair_beats_constraint_seat
    """
    resp, _ = _accept_wheelchair_and_seat_both_short(api)
    validate_error(resp, ApiErrorId.ERR_NO_WHEELCHAIR_CAPACITY.value)


def test_accept_capacity_conflict_leaves_trip_offered(api):
    """PRD §3.6: "a wheelchair position must be free over the trip's interval when the
    trip needs securement (else `ERR_NO_WHEELCHAIR_CAPACITY`, HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/accept_safety_wheelchair_beats_constraint_seat
    """
    resp, trip_id = _accept_wheelchair_and_seat_both_short(api)
    validate_error(resp, ApiErrorId.ERR_NO_WHEELCHAIR_CAPACITY.value)
    trip = validate_success(api.get_trip(trip_id, DISPATCHER))
    assert trip["status"] == "OFFERED"


# ==========================================================================
# Difficulty A — cross_entity_state_dependency: accept onto DISPATCHED run
# ==========================================================================
def _accept_onto_dispatched_run(api):
    base = th.scenario_certified_rider_zone(api)
    rider_id = base["rider"]["id"]
    za = base["zone_a"]["id"]
    run = th.create_run(api, za)
    api.open_run(run["id"], DISPATCHER)
    api.dispatch_run(run["id"], DISPATCHER)
    run_now = validate_success(api.get_run(run["id"], DISPATCHER))
    trip = th.create_offered_trip(api, rider_id, za, za)
    resp = th.accept_trip(api, trip["id"], rider_id, run["id"], run_now["version"])
    return resp, trip["id"]


def test_accept_onto_dispatched_run_rejected(api):
    """PRD §3.6: "the target run's `status` must be `PLANNED` or `OPEN` (else
    `ERR_RUN_NOT_OPEN`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/accept_gated_by_vehicle_run_status_dispatched_rejected
    """
    resp, _ = _accept_onto_dispatched_run(api)
    validate_error(resp, ApiErrorId.ERR_RUN_NOT_OPEN.value)


def test_accept_onto_dispatched_run_leaves_trip_offered(api):
    """PRD §3.7: "A run's `status` moves through `PLANNED`, `OPEN`, `DISPATCHED`, and the
    terminal states `CLOSED` and `CANCELLED`."
    PRD §3.6: "the target run's `status` must be `PLANNED` or `OPEN` (else
    `ERR_RUN_NOT_OPEN`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/accept_gated_by_vehicle_run_status_dispatched_rejected
    """
    resp, trip_id = _accept_onto_dispatched_run(api)
    validate_error(resp, ApiErrorId.ERR_RUN_NOT_OPEN.value)
    trip = validate_success(api.get_trip(trip_id, DISPATCHER))
    assert trip["status"] == "OFFERED"


# ==========================================================================
# Difficulty A — resource_temporal_overlap: rider self-overlap
# ==========================================================================
def _accept_overlapping_second_trip(api):
    base = th.scenario_certified_rider_zone(api)
    rider_id = base["rider"]["id"]
    za = base["zone_a"]["id"]
    run_a = th.create_run(api, za)
    run_b = th.create_run(api, za)
    trip_a = th.create_offered_trip(api, rider_id, za, za,
                                    requested_pickup_at="2026-06-05T09:00:00Z")
    th.accept_trip(api, trip_a["id"], rider_id, run_a["id"], run_a["version"])
    trip_b = th.create_offered_trip(api, rider_id, za, za,
                                    requested_pickup_at="2026-06-05T09:05:00Z")
    resp = th.accept_trip(api, trip_b["id"], rider_id, run_b["id"], run_b["version"])
    return resp, trip_b["id"]


def test_rider_overlapping_trip_rejected(api):
    """PRD §3.6: "the rider must have no other non-terminal trip whose buffered interval
    overlaps this one (else `ERR_RIDER_TRIP_OVERLAP`, HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rider_self_buffered_interval_overlap_rejected
    """
    resp, _ = _accept_overlapping_second_trip(api)
    validate_error(resp, ApiErrorId.ERR_RIDER_TRIP_OVERLAP.value)


def test_rider_overlapping_trip_stays_offered(api):
    """PRD §3.6: "The overlap guard compares this trip's buffered interval against the
    buffered interval of each of the rider's other non-terminal trips, where a trip's
    buffered interval extends from fifteen minutes before its pickup to fifteen minutes
    after its dropoff (`TURNAROUND_BUFFER_MINUTES` of 15 minutes on each side); the
    intervals are closed, so touching endpoints count as an overlap."

    Design: Difficulty/resource_temporal_overlap/rider_self_buffered_interval_overlap_rejected
    """
    resp, trip_b_id = _accept_overlapping_second_trip(api)
    validate_error(resp, ApiErrorId.ERR_RIDER_TRIP_OVERLAP.value)
    trip = validate_success(api.get_trip(trip_b_id, DISPATCHER))
    assert trip["status"] == "OFFERED"


# ==========================================================================
# Difficulty A — resource_temporal_overlap: run aggregate wheelchair capacity
# ==========================================================================
def _two_riders_exhaust_single_wheelchair_position(api):
    th.set_clock(api, "2026-06-01T00:00:00Z")
    za = th.create_zone_a(api)
    rider1 = th.create_certified_rider(api, phone="555-0016", email="r16a@x.com",
                                       mobility_device="MANUAL_WHEELCHAIR",
                                       assessed_mobility_device="MANUAL_WHEELCHAIR")
    rider2 = th.create_certified_rider(api, phone="555-0017", email="r16b@x.com",
                                       mobility_device="MANUAL_WHEELCHAIR",
                                       assessed_mobility_device="MANUAL_WHEELCHAIR")
    run = th.create_run(api, za["id"], seats=4, positions=1)
    trip1 = th.create_offered_trip(api, rider1["id"], za["id"], za["id"],
                                   requested_pickup_at="2026-06-05T09:00:00Z", needs_wheelchair=True)
    th.accept_trip(api, trip1["id"], rider1["id"], run["id"], run["version"])
    run_v1 = validate_success(api.get_run(run["id"], DISPATCHER))["version"]
    trip2 = th.create_offered_trip(api, rider2["id"], za["id"], za["id"],
                                   requested_pickup_at="2026-06-05T09:05:00Z", needs_wheelchair=True)
    resp = th.accept_trip(api, trip2["id"], rider2["id"], run["id"], run_v1)
    return resp, run["id"], trip2["id"]


def test_wheelchair_capacity_exhausted_rejects_second_accept(api):
    """PRD §3.6: "Wheelchair availability compares the peak concurrent wheelchair
    occupancy over the trip's interval against `total_wheelchair_positions`."
    PRD §3.6: "a wheelchair position must be free over the trip's interval when the trip
    needs securement (else `ERR_NO_WHEELCHAIR_CAPACITY`, HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/run_aggregate_wheelchair_capacity_overlap_rejected
    """
    resp, run_id, _ = _two_riders_exhaust_single_wheelchair_position(api)
    validate_error(resp, ApiErrorId.ERR_NO_WHEELCHAIR_CAPACITY.value)
    run = validate_success(api.get_run(run_id, DISPATCHER))
    assert run["available_wheelchair_positions"] == 0


def test_wheelchair_capacity_conflict_leaves_second_trip_offered(api):
    """PRD §3.6: "The seat and position demand of a trip depends on how the rider travels.
    When the trip's `needs_wheelchair` flag is set, the rider occupies one wheelchair
    (securement) position and does not consume an ambulatory seat."

    Design: Difficulty/resource_temporal_overlap/run_aggregate_wheelchair_capacity_overlap_rejected
    """
    resp, _, trip2_id = _two_riders_exhaust_single_wheelchair_position(api)
    validate_error(resp, ApiErrorId.ERR_NO_WHEELCHAIR_CAPACITY.value)
    trip = validate_success(api.get_trip(trip2_id, DISPATCHER))
    assert trip["status"] == "OFFERED"


# ==========================================================================
# Corner B — optimistic concurrency (stale + correct) and immediate consistency
# ==========================================================================
def test_stale_run_version_accept_rejected(api):
    """PRD §2.9: "If that value does not match the run's current `version` — that is, if
    another accept has already booked against the run and advanced its version since the
    client last read it — the accept is rejected with `ERR_STALE_RUN_VERSION` (HTTP 412),
    preventing the client from booking against a run whose capacity it has not actually
    seen."

    Design: Corner/validations/occ_stale_run_version_returns_stale_run_version
    """
    base = th.scenario_certified_rider_zone_run(api)
    rider_id = base["rider"]["id"]
    za = base["zone_a"]["id"]
    run_id = base["run"]["id"]
    run_v0 = base["run"]["version"]
    trip1 = th.create_offered_trip(api, rider_id, za, za, requested_pickup_at="2026-06-05T09:00:00Z")
    th.accept_trip(api, trip1["id"], rider_id, run_id, run_v0)
    trip2 = th.create_offered_trip(api, rider_id, za, za, requested_pickup_at="2026-06-05T14:00:00Z")
    resp = th.accept_trip(api, trip2["id"], rider_id, run_id, run_v0)  # run_v0 now stale
    validate_error(resp, ApiErrorId.ERR_STALE_RUN_VERSION.value)
    trip = validate_success(api.get_trip(trip2["id"], DISPATCHER))
    assert trip["status"] == "OFFERED"


def test_correct_run_version_accept_succeeds_and_increments(api):
    """PRD §2.9: "Every capacity-mutating event on a run — an accept, a release on cancel
    or dropoff, and the dispatch cascade — increments the run's `version` by one and
    refreshes its `updated_at`."
    PRD §3.6: "decrements the run's `available_wheelchair_positions` and
    `available_ambulatory_seats` by the trip's needs, and increments the run's `version`
    by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_run_version_accept_succeeds_and_increments
    """
    base = th.scenario_certified_rider_zone_run(api)
    rider_id = base["rider"]["id"]
    za = base["zone_a"]["id"]
    baseline_version = base["run"]["version"]
    trip = th.create_offered_trip(api, rider_id, za, za)
    resp = th.accept_trip(api, trip["id"], rider_id, base["run"]["id"], baseline_version)
    data = validate_success(resp, 200)
    assert data["status"] == "SCHEDULED"
    run = validate_success(api.get_run(base["run"]["id"], DISPATCHER))
    assert run["version"] == baseline_version + 1
    assert run["available_ambulatory_seats"] == 3


def test_accept_response_reflects_scheduled_window_immediately(api):
    """PRD §3.6: "A successful accept sets `scheduled_pickup_at` equal to
    `current_offer_pickup_at` and `scheduled_dropoff_at` equal to `scheduled_pickup_at`
    plus the fixed trip duration (`TRIP_DURATION_MINUTES`)."

    Design: Corner/consistency_model/accept_response_reflects_scheduled_window_immediately
    """
    base = th.scenario_certified_rider_zone_run(api)
    rider_id = base["rider"]["id"]
    za = base["zone_a"]["id"]
    trip = th.create_offered_trip(api, rider_id, za, za, requested_pickup_at="2026-06-05T09:00:00Z")
    resp = th.accept_trip(api, trip["id"], rider_id, base["run"]["id"], base["run"]["version"])
    data = validate_success(resp, 200)
    assert data["scheduled_pickup_at"] == "2026-06-05T09:00:00Z"
    assert data["scheduled_dropoff_at"] is not None
