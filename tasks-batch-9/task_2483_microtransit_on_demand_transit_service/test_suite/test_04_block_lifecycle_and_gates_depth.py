"""Depth tests for the block lifecycle, its cascades and the gates that guard it.

Three families live here:
  * the two multi-hop cascades — cancelling an OPEN block, and the third
    consecutive decline that takes a driver off the road;
  * the two rejection-precedence pairs on manual dispatch, where the same
    request violates two checks at once and only the earlier one may answer;
  * the two cross-entity gates — trip intake reading the zone's status, and a
    block open reading its pinned vehicle's status.

Every test builds its own state from scratch: the server is restarted and the
database emptied before each one, and the logical clock is moved explicitly.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, DISPATCHER_HEADERS, api_client, assertions, fixtures
from test_helpers.factories import pool_assignment_payload, trip_request_payload
from test_helpers.test_users import make_driver_headers, make_rider_headers

# ─── Per-instance state builders ───────────────────────────────────────────
#
# Each helper is a plain callable invoked inside the test body, so the two tests
# derived from one recipe never share a row.


def _build_trip_at_attempt_budget():
    """Zone RBM ACTIVE, block B1 OPEN 06:00-10:00Z, and one S0->S4 trip that was
    auto-matched, declined and then manually re-dispatched, so it sits OFFERED
    with `match_attempt_count` at the two-attempt budget."""
    state = fixtures.setup_dispatch_ready()
    trip = fixtures.create_trip(
        state["zone"]["id"],
        state["rider"]["id"],
        state["stops"][0]["id"],
        state["stops"][4]["id"],
    )
    fixtures.match_trip(trip["id"])
    first_offer = fixtures.live_assignment_for_trip(trip["id"])
    fixtures.decline_assignment(first_offer["id"], state["driver"]["id"])
    second_offer = fixtures.dispatch_trip(trip["id"], state["block"]["id"])
    state["trip"] = fixtures.refresh_trip(trip["id"])
    state["block"] = fixtures.refresh_block(state["block"]["id"])
    state["declined_assignment"] = first_offer
    state["live_assignment"] = second_offer
    return state


def _build_driver_on_two_declines():
    """Zone RBM ACTIVE with block B1 OPEN 06:00-10:00Z and block BS SCHEDULED
    10:30-12:30Z on the same vehicle and driver, the driver carrying two declines
    and a third offer still live on B1."""
    state = fixtures.setup_dispatch_ready()
    scheduled_block = fixtures.create_block(
        state["zone"]["id"],
        state["vehicle"]["id"],
        state["driver"]["id"],
        start_utc="2026-08-03T10:30:00Z",
        end_utc="2026-08-03T12:30:00Z",
    )
    for _ in range(2):
        trip = fixtures.create_trip(
            state["zone"]["id"],
            state["rider"]["id"],
            state["stops"][0]["id"],
            state["stops"][4]["id"],
        )
        offer = fixtures.dispatch_trip(trip["id"], state["block"]["id"])
        fixtures.decline_assignment(offer["id"], state["driver"]["id"])
    third_trip = fixtures.create_trip(
        state["zone"]["id"],
        state["rider"]["id"],
        state["stops"][0]["id"],
        state["stops"][4]["id"],
    )
    state["scheduled_block"] = scheduled_block
    state["trip"] = third_trip
    state["live_assignment"] = fixtures.dispatch_trip(
        third_trip["id"], state["block"]["id"]
    )
    state["driver"] = fixtures.refresh_driver(state["driver"]["id"])
    state["block"] = fixtures.refresh_block(state["block"]["id"])
    return state


def _build_oversized_party_on_scheduled_block():
    """A two-seat vehicle on a block deliberately left SCHEDULED, plus a trip
    whose party of three cannot fit even on an empty manifest."""
    state = fixtures.setup_dispatch_ready(
        vehicle_overrides={"seat_capacity": 2, "wav_positions": 0},
        driver_overrides={"wav_certified": False},
        open_the_block=False,
    )
    state["trip"] = fixtures.create_trip(
        state["zone"]["id"],
        state["rider"]["id"],
        state["stops"][0]["id"],
        state["stops"][4]["id"],
        party_size=3,
    )
    return state


def _build_wheelchair_trip_and_two_zones():
    """Two ACTIVE zones, each with an OPEN block on a vehicle with no securement
    positions and an uncertified driver, and a wheelchair rider's trip in the
    first zone."""
    fixtures.set_clock("2026-08-03T06:00:00Z")
    zone_a = fixtures.create_active_zone(name="Riverbend A", zone_code="RBM-A")
    zone_b = fixtures.create_active_zone(name="Riverbend B", zone_code="RBM-B")
    stop_a0 = fixtures.create_approved_stop(zone_a["id"], "A0", 0)
    stop_a4 = fixtures.create_approved_stop(zone_a["id"], "A4", 4)
    vehicle_a = fixtures.create_vehicle(zone_a["id"], "AV", wav_positions=0)
    driver_a = fixtures.create_driver(zone_a["id"], "AD", wav_certified=False)
    vehicle_b = fixtures.create_vehicle(zone_b["id"], "BV", wav_positions=0)
    driver_b = fixtures.create_driver(zone_b["id"], "BD", wav_certified=False)
    rider = fixtures.create_rider(zone_a["id"], "RW", mobility_device="WHEELCHAIR")
    block_a = fixtures.create_open_block(zone_a["id"], vehicle_a["id"], driver_a["id"])
    block_b = fixtures.create_open_block(zone_b["id"], vehicle_b["id"], driver_b["id"])
    trip = fixtures.create_trip(zone_a["id"], rider["id"], stop_a0["id"], stop_a4["id"])
    return {
        "zone_a": zone_a,
        "zone_b": zone_b,
        "block_a": block_a,
        "block_b": block_b,
        "rider": rider,
        "trip": trip,
    }


def _build_suspended_zone_with_swept_trip():
    """An ACTIVE zone holding one RECEIVED trip, then suspended so that trip is
    swept out of the fulfilment pipeline."""
    fixtures.set_clock("2026-08-03T06:00:00Z")
    zone = fixtures.create_active_zone()
    stops = fixtures.build_corridor(zone["id"], indexes=(0, 4))
    rider_one = fixtures.create_rider(zone["id"], "R1")
    rider_two = fixtures.create_rider(zone["id"], "R2", fare_category="REDUCED")
    swept_trip = fixtures.create_trip(
        zone["id"], rider_one["id"], stops[0]["id"], stops[4]["id"]
    )
    zone = fixtures.suspend_zone(zone["id"])
    return {
        "zone": zone,
        "stops": stops,
        "rider_one": rider_one,
        "rider_two": rider_two,
        "swept_trip": swept_trip,
    }


def _second_rider_intake_payload(state):
    return trip_request_payload(
        state["zone"]["id"],
        state["rider_two"]["id"],
        state["stops"][0]["id"],
        state["stops"][4]["id"],
        requested_pickup_utc="2026-08-03T07:30:00Z",
    )


def _build_scheduled_block_with_vehicle_in_maintenance():
    """A SCHEDULED block over 06:00-10:00Z whose pinned vehicle has been pulled
    into maintenance, with no published forecast to mask the vehicle gate."""
    fixtures.set_clock("2026-08-03T05:30:00Z")
    zone = fixtures.create_active_zone()
    vehicle = fixtures.create_vehicle(zone["id"], "V1")
    driver = fixtures.create_driver(zone["id"], "D1")
    block = fixtures.create_block(zone["id"], vehicle["id"], driver["id"])
    fixtures.set_vehicle_status(vehicle["id"], "IN_MAINTENANCE")
    return {"zone": zone, "vehicle": vehicle, "driver": driver, "block": block}


# ─── Cancelling an OPEN block: the four ordered hops ───────────────────────


def test_open_block_cancel_zeroes_commitments_and_releases_the_live_offer():
    """Cancelling an OPEN block zeroes its committed capacity and releases the offer on it.

    PRD: "The first hop zeroes the block's own commitments: `seats_committed` and `wav_positions_committed` are set to 0, and `committed_index_min` and `committed_index_max` are set to null."

    Design: Difficulty/transitive_cascade/block_cancel_cascade_four_hops_to_no_service
    """
    state = _build_trip_at_attempt_budget()
    before = state["block"]
    assertions.assert_block_commitments(
        before,
        seats_committed=1,
        wav_positions_committed=0,
        committed_index_min=0,
        committed_index_max=4,
    )

    cancelled = validate_success(
        api_client.cancel_vehicle_block(
            before["id"], DISPATCHER_HEADERS, {"note": "vehicle pulled for a road call"}
        ),
        200,
    )

    assertions.assert_block_state(cancelled, "CANCELLED")
    assertions.assert_block_commitments(
        cancelled,
        seats_committed=0,
        wav_positions_committed=0,
        committed_index_min=None,
        committed_index_max=None,
    )
    assertions.assert_version_advanced(before, cancelled)

    released = fixtures.refresh_assignment(state["live_assignment"]["id"])
    assertions.assert_assignment_state(released, "RELEASED")
    still_declined = fixtures.refresh_assignment(state["declined_assignment"]["id"])
    assertions.assert_assignment_state(still_declined, "DECLINED")


def test_open_block_cancel_exhausts_the_trip_and_recomputes_unserved_count():
    """A released trip that already used both match attempts lands in NO_SERVICE with MAX_ATTEMPTS_EXHAUSTED.

    PRD: "The fourth hop, caused by the third, handles trips that have run out of chances: any such trip whose `match_attempt_count` has already reached 2 moves instead to `NO_SERVICE` with `no_service_reason` set to `MAX_ATTEMPTS_EXHAUSTED`, and the `unserved_trip_count` of that trip's zone is recomputed."

    Design: Difficulty/transitive_cascade/block_cancel_cascade_four_hops_to_no_service
    """
    state = _build_trip_at_attempt_budget()
    assertions.assert_trip_state(state["trip"], "OFFERED", "QUOTED")
    assertions.assert_fields(
        state["trip"], match_attempt_count=2, quoted_fare_cents=325
    )
    assert fixtures.refresh_zone(state["zone"]["id"])["unserved_trip_count"] == 0

    validate_success(
        api_client.cancel_vehicle_block(
            state["block"]["id"],
            DISPATCHER_HEADERS,
            {"note": "vehicle pulled for a road call"},
        ),
        200,
    )

    trip = fixtures.refresh_trip(state["trip"]["id"])
    assertions.assert_trip_state(trip, "NO_SERVICE", "UNPRICED")
    assertions.assert_fields(
        trip, no_service_reason="MAX_ATTEMPTS_EXHAUSTED", match_attempt_count=2
    )
    assertions.assert_null_fields(
        trip,
        "assigned_block_id",
        "quoted_fare_cents",
        "promised_pickup_utc",
        "promised_dropoff_utc",
        "projected_detour_minutes",
    )

    zone = fixtures.refresh_zone(state["zone"]["id"])
    assertions.assert_fields(zone, unserved_trip_count=1, completed_trip_count=0)
    driver = fixtures.refresh_driver(state["driver"]["id"])
    assertions.assert_fields(driver, consecutive_decline_count=1, status="ACTIVE")


# ─── The third consecutive decline ─────────────────────────────────────────


def test_third_decline_returns_block_capacity_and_requeues_the_trip():
    """A decline hands the block's capacity back and un-books the trip into MATCHING.

    PRD: "The second hop, caused by the first, does two things at once: the driver's `consecutive_decline_count` increases by 1, and the trip is un-booked — `assigned_block_id`, `promised_pickup_utc`, `promised_dropoff_utc` and `projected_detour_minutes` are cleared to null and a `fare_status` of `QUOTED` or `CAPPED` reverts to `UNPRICED` with `quoted_fare_cents` cleared to null, after which the trip returns `OFFERED → MATCHING` if its `match_attempt_count` is still below 2, or instead moves `OFFERED → NO_SERVICE` with `no_service_reason` set to `MAX_ATTEMPTS_EXHAUSTED` and the zone's `unserved_trip_count` recomputed when that count has already reached 2."

    Design: Difficulty/transitive_cascade/decline_streak_suspends_driver_and_cancels_their_scheduled_block
    """
    state = _build_driver_on_two_declines()
    before_block = state["block"]
    assertions.assert_fields(state["driver"], consecutive_decline_count=2)

    declined = validate_success(
        api_client.decline_pool_assignment(
            state["live_assignment"]["id"],
            make_driver_headers(state["driver"]["id"]),
            {"reason": "third refusal"},
        ),
        200,
    )

    assertions.assert_assignment_state(declined, "DECLINED")

    block = fixtures.refresh_block(before_block["id"])
    assertions.assert_block_commitments(
        block,
        seats_committed=0,
        wav_positions_committed=0,
        committed_index_min=None,
        committed_index_max=None,
    )
    assertions.assert_version_advanced(before_block, block)

    trip = fixtures.refresh_trip(state["trip"]["id"])
    assertions.assert_trip_state(trip, "MATCHING", "UNPRICED")
    assertions.assert_fields(trip, match_attempt_count=1)
    assertions.assert_null_fields(
        trip,
        "assigned_block_id",
        "quoted_fare_cents",
        "promised_pickup_utc",
        "promised_dropoff_utc",
        "projected_detour_minutes",
    )
    assert fixtures.refresh_zone(state["zone"]["id"])["unserved_trip_count"] == 0


def test_third_decline_suspends_driver_and_cancels_only_their_scheduled_block():
    """Three declines in a row suspend the driver and sweep their SCHEDULED block, leaving the OPEN one alone.

    PRD: "The third hop, caused by the second, is the roster consequence: a driver whose `consecutive_decline_count` has reached three declines in a row is moved `ACTIVE → SUSPENDED`, their `version` advances by 1, and every vehicle block of theirs in state `SCHEDULED` is cancelled, processed in block `start_utc` ascending and then block `created_at` ascending order."

    Design: Difficulty/transitive_cascade/decline_streak_suspends_driver_and_cancels_their_scheduled_block
    """
    state = _build_driver_on_two_declines()
    before_driver = state["driver"]
    assertions.assert_fields(before_driver, status="ACTIVE", consecutive_decline_count=2)
    assertions.assert_block_state(state["scheduled_block"], "SCHEDULED")

    validate_success(
        api_client.decline_pool_assignment(
            state["live_assignment"]["id"],
            make_driver_headers(state["driver"]["id"]),
            {"reason": "third refusal"},
        ),
        200,
    )

    driver = fixtures.refresh_driver(before_driver["id"])
    assertions.assert_fields(driver, status="SUSPENDED", consecutive_decline_count=3)
    assertions.assert_version_advanced(before_driver, driver)

    assertions.assert_block_state(
        fixtures.refresh_block(state["scheduled_block"]["id"]), "CANCELLED"
    )
    open_block = fixtures.refresh_block(state["block"]["id"])
    assertions.assert_block_state(open_block, "OPEN")
    assertions.assert_block_commitments(open_block, seats_committed=0)


# ─── Manual dispatch: block state outranks seat capacity ───────────────────


def test_offer_onto_scheduled_block_reports_block_state_not_seat_capacity():
    """When the block is still SCHEDULED and the party also overflows the vehicle, the state gate answers.

    PRD: "Manual dispatch of a trip onto a block runs, in order: assignment-state legality, zone active, the block-version concurrency check, cross-zone consistency, wheelchair-accessible dispatch capability, the pickup-inside-window check, curb capacity, detour tolerance, seat capacity and finally securement-position capacity."

    Design: Difficulty/priority_pair_validation_conflict/block_state_priority_12_outranks_seat_capacity_priority_52
    """
    state = _build_oversized_party_on_scheduled_block()
    block = state["block"]
    assertions.assert_block_state(block, "SCHEDULED")
    assertions.assert_fields(state["vehicle"], seat_capacity=2)
    assertions.assert_fields(state["trip"], party_size=3)

    response = api_client.create_pool_assignment(
        pool_assignment_payload(state["trip"]["id"], block["id"], block["version"]),
        DISPATCHER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_BLOCK_STATE.value)

    rows, meta = validate_paginated(
        api_client.list_pool_assignments(
            DISPATCHER_HEADERS, params={"trip_request_id": state["trip"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assertions.assert_row_count(rows, 0)

    trip = fixtures.refresh_trip(state["trip"]["id"])
    assertions.assert_trip_state(trip, "RECEIVED", "UNPRICED")
    assertions.assert_fields(trip, match_attempt_count=0, assigned_block_id=None)
    unchanged = fixtures.refresh_block(block["id"])
    assertions.assert_block_state(unchanged, "SCHEDULED")
    assertions.assert_version_unchanged(block, unchanged)


def test_offer_onto_opened_block_then_reports_seat_capacity_exceeded():
    """Once the block is OPEN the untouched capacity violation surfaces on its own.

    PRD: "And the block's `seats_committed` plus the trip's `party_size` must not exceed the vehicle's `seat_capacity`, with a violation reported as `ERR_SEAT_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/block_state_priority_12_outranks_seat_capacity_priority_52
    """
    state = _build_oversized_party_on_scheduled_block()
    scheduled = state["block"]
    validate_error(
        api_client.create_pool_assignment(
            pool_assignment_payload(
                state["trip"]["id"], scheduled["id"], scheduled["version"]
            ),
            DISPATCHER_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_BLOCK_STATE.value,
    )

    opened = fixtures.open_block(scheduled["id"])
    assertions.assert_block_state(opened, "OPEN")

    response = api_client.create_pool_assignment(
        pool_assignment_payload(state["trip"]["id"], opened["id"], opened["version"]),
        DISPATCHER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED.value)

    rows, meta = validate_paginated(
        api_client.list_pool_assignments(
            DISPATCHER_HEADERS, params={"trip_request_id": state["trip"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assertions.assert_row_count(rows, 0)

    trip = fixtures.refresh_trip(state["trip"]["id"])
    assertions.assert_trip_state(trip, "RECEIVED", "UNPRICED")
    assertions.assert_fields(trip, match_attempt_count=0, assigned_block_id=None)
    block = fixtures.refresh_block(opened["id"])
    assertions.assert_block_state(block, "OPEN")
    assertions.assert_block_commitments(block, seats_committed=0)


# ─── Manual dispatch: cross-zone consistency outranks the accessibility gate ─


def test_cross_zone_wheelchair_offer_reports_zone_mismatch_not_wav_unavailable():
    """A wheelchair offer aimed at a foreign zone's block fails on zone consistency first.

    PRD: "Manual dispatch of a trip onto a block runs, in order: assignment-state legality, zone active, the block-version concurrency check, cross-zone consistency, wheelchair-accessible dispatch capability, the pickup-inside-window check, curb capacity, detour tolerance, seat capacity and finally securement-position capacity."

    Design: Difficulty/priority_pair_validation_conflict/zone_mismatch_priority_20_outranks_wav_unavailable_priority_28
    """
    state = _build_wheelchair_trip_and_two_zones()
    assertions.assert_fields(state["trip"], wav_required=True)
    foreign_block = state["block_b"]

    response = api_client.create_pool_assignment(
        pool_assignment_payload(
            state["trip"]["id"], foreign_block["id"], foreign_block["version"]
        ),
        DISPATCHER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ZONE_MISMATCH.value)

    after = fixtures.refresh_block(foreign_block["id"])
    assertions.assert_version_unchanged(foreign_block, after)
    assertions.assert_block_commitments(
        after, seats_committed=0, wav_positions_committed=0
    )

    rows, meta = validate_paginated(
        api_client.list_pool_assignments(
            DISPATCHER_HEADERS, params={"trip_request_id": state["trip"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assertions.assert_row_count(rows, 0)

    trip = fixtures.refresh_trip(state["trip"]["id"])
    assertions.assert_trip_state(trip, "RECEIVED", "UNPRICED")
    assertions.assert_fields(trip, match_attempt_count=0, assigned_block_id=None)


def test_same_zone_wheelchair_offer_then_reports_wav_unavailable():
    """Re-aimed at its own zone, the same wheelchair offer fails on the accessibility gate.

    PRD: "A wheelchair-accessible trip may only be placed on a block whose vehicle has at least one securement position and whose driver is `wav_certified`, with a failure reported as `ERR_WAV_UNAVAILABLE`, and separately the block's remaining securement headroom must still be at least 1, with exhaustion reported as `ERR_WAV_POSITION_UNAVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/zone_mismatch_priority_20_outranks_wav_unavailable_priority_28
    """
    state = _build_wheelchair_trip_and_two_zones()
    assertions.assert_fields(state["trip"], wav_required=True)
    validate_error(
        api_client.create_pool_assignment(
            pool_assignment_payload(
                state["trip"]["id"],
                state["block_b"]["id"],
                state["block_b"]["version"],
            ),
            DISPATCHER_HEADERS,
        ),
        ApiErrorId.ERR_ZONE_MISMATCH.value,
    )

    home_block = state["block_a"]
    response = api_client.create_pool_assignment(
        pool_assignment_payload(
            state["trip"]["id"], home_block["id"], home_block["version"]
        ),
        DISPATCHER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_WAV_UNAVAILABLE.value)

    after = fixtures.refresh_block(home_block["id"])
    assertions.assert_block_state(after, "OPEN")
    assertions.assert_block_commitments(
        after, seats_committed=0, wav_positions_committed=0
    )

    rows, meta = validate_paginated(
        api_client.list_pool_assignments(
            DISPATCHER_HEADERS, params={"trip_request_id": state["trip"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assertions.assert_row_count(rows, 0)

    trip = fixtures.refresh_trip(state["trip"]["id"])
    assertions.assert_trip_state(trip, "RECEIVED", "UNPRICED")
    assertions.assert_fields(trip, match_attempt_count=0)


# ─── Trip intake gated on the zone's status ────────────────────────────────


def test_zone_suspension_sweeps_the_received_trip_and_closes_intake():
    """Suspending a zone evicts its unfulfilled demand and rejects further intake.

    PRD: "Every trip request in the zone whose `status` is `RECEIVED` or `MATCHING` is swept to `NO_SERVICE` with `no_service_reason` set to `ZONE_SUSPENDED` and `assigned_block_id` cleared to null, processed in trip `created_at` ascending order."

    Design: Difficulty/cross_entity_state_dependency/trip_intake_gated_on_zone_status_and_suspension_is_not_undone
    """
    state = _build_suspended_zone_with_swept_trip()
    assertions.assert_fields(state["zone"], status="SUSPENDED")

    swept = fixtures.refresh_trip(state["swept_trip"]["id"])
    assertions.assert_trip_state(swept, "NO_SERVICE", "UNPRICED")
    assertions.assert_fields(swept, no_service_reason="ZONE_SUSPENDED")
    assertions.assert_null_fields(swept, "assigned_block_id", "quoted_fare_cents")

    zone = fixtures.refresh_zone(state["zone"]["id"])
    assertions.assert_fields(zone, unserved_trip_count=1, completed_trip_count=0)

    response = api_client.create_trip_request(
        _second_rider_intake_payload(state),
        make_rider_headers(state["rider_two"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ZONE_NOT_ACTIVE.value)


def test_zone_reactivation_restores_intake_without_restoring_the_swept_trip():
    """Reopening the zone lets intake through again but leaves the evicted trip terminal.

    PRD: "Note also what reactivation does *not* do: `NO_SERVICE` is terminal, so reopening a zone never restores the trips its suspension evicted."

    Design: Difficulty/cross_entity_state_dependency/trip_intake_gated_on_zone_status_and_suspension_is_not_undone
    """
    state = _build_suspended_zone_with_swept_trip()
    validate_error(
        api_client.create_trip_request(
            _second_rider_intake_payload(state),
            make_rider_headers(state["rider_two"]["id"]),
        ),
        ApiErrorId.ERR_ZONE_NOT_ACTIVE.value,
    )

    reactivated = fixtures.activate_zone(state["zone"]["id"])
    assertions.assert_fields(reactivated, status="ACTIVE")

    still_swept = fixtures.refresh_trip(state["swept_trip"]["id"])
    assertions.assert_trip_state(still_swept, "NO_SERVICE", "UNPRICED")
    assertions.assert_fields(still_swept, no_service_reason="ZONE_SUSPENDED")

    fresh = validate_success(
        api_client.create_trip_request(
            _second_rider_intake_payload(state),
            make_rider_headers(state["rider_two"]["id"]),
        ),
        201,
    )
    assertions.assert_trip_state(fresh, "RECEIVED", "UNPRICED")
    assertions.assert_fields(fresh, match_attempt_count=0)

    zone = fixtures.refresh_zone(state["zone"]["id"])
    assertions.assert_fields(zone, unserved_trip_count=1)

    rows, meta = validate_paginated(
        api_client.list_trip_requests(
            DISPATCHER_HEADERS,
            params={"zone_id": state["zone"]["id"], "status": "NO_SERVICE"},
        )
    )
    assert meta["total_count"] == 1
    assertions.assert_contains_ids(rows, state["swept_trip"]["id"])
    assertions.assert_excludes_ids(rows, fresh["id"])


# ─── Block open gated on the pinned vehicle's status ───────────────────────


def test_block_open_rejected_while_pinned_vehicle_is_in_maintenance_is_a_no_op():
    """A block whose vehicle sits in maintenance cannot open, and the refusal writes nothing.

    PRD: "Four things must hold beyond the origin state: the block's zone must be `ACTIVE` (otherwise `ERR_ZONE_NOT_ACTIVE`), the pinned vehicle's `status` must be `AVAILABLE` (otherwise `ERR_INVALID_VEHICLE_STATE`), the rostered driver's `status` must be `ACTIVE` (otherwise `ERR_INVALID_DRIVER_STATE`), and the peak-surge fleet-sizing ceiling must not be breached."

    Design: Difficulty/cross_entity_state_dependency/block_open_gated_on_vehicle_status_then_released_by_maintenance_return
    """
    state = _build_scheduled_block_with_vehicle_in_maintenance()
    block = state["block"]
    assertions.assert_fields(state["zone"], status="ACTIVE")
    assertions.assert_fields(
        fixtures.refresh_vehicle(state["vehicle"]["id"]), status="IN_MAINTENANCE"
    )
    assertions.assert_fields(
        fixtures.refresh_driver(state["driver"]["id"]), status="ACTIVE"
    )

    response = api_client.open_vehicle_block(block["id"], DISPATCHER_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_VEHICLE_STATE.value)

    after = fixtures.refresh_block(block["id"])
    assertions.assert_block_state(after, "SCHEDULED")
    assertions.assert_null_fields(after, "opened_at", "closed_at")
    assertions.assert_version_unchanged(block, after)


def test_block_open_succeeds_once_the_vehicle_returns_from_maintenance():
    """The identical open succeeds after the vehicle is AVAILABLE again, stamping the logical clock.

    PRD: "On success `state` becomes `OPEN`, `opened_at` is stamped with the current logical clock reading, and `version` advances by 1."

    Design: Difficulty/cross_entity_state_dependency/block_open_gated_on_vehicle_status_then_released_by_maintenance_return
    """
    state = _build_scheduled_block_with_vehicle_in_maintenance()
    block = state["block"]
    validate_error(
        api_client.open_vehicle_block(block["id"], DISPATCHER_HEADERS),
        ApiErrorId.ERR_INVALID_VEHICLE_STATE.value,
    )

    vehicle = fixtures.set_vehicle_status(state["vehicle"]["id"], "AVAILABLE")
    assertions.assert_fields(vehicle, status="AVAILABLE")
    fixtures.set_clock("2026-08-03T06:00:00Z")

    opened = validate_success(
        api_client.open_vehicle_block(block["id"], DISPATCHER_HEADERS), 200
    )

    assertions.assert_block_state(opened, "OPEN")
    assertions.assert_instant_equals(opened["opened_at"], "2026-08-03T06:00:00Z")
    assertions.assert_version_advanced(block, opened)
    assert opened["actual_revenue_hours"] == pytest.approx(0.00, abs=0.01)
    assert opened["scheduled_revenue_hours"] == pytest.approx(4.00, abs=0.01)

    persisted = get_success_data(
        api_client.get_vehicle_block(block["id"], DISPATCHER_HEADERS)
    )
    assertions.assert_block_state(persisted, "OPEN")
    assertions.assert_instant_equals(persisted["opened_at"], "2026-08-03T06:00:00Z")
