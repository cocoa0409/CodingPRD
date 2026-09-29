"""Depth coverage for real-time matching, manual dispatch and the driver's manifest.

Every state these tests need is built in-test through the public endpoints: the
server is restarted with an empty database before each test and the logical clock
reads 2026-08-01T00:00:00Z at start-up, so each recipe moves it explicitly.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import pool_assignment_payload
from test_helpers.fixtures import (
    assignments_for_trip,
    block_version,
    build_corridor,
    create_active_zone,
    create_driver,
    create_open_block,
    create_rider,
    create_trip,
    create_vehicle,
    dispatch_trip,
    open_block,
    refresh_block,
    refresh_driver,
    refresh_trip,
    set_clock,
    setup_dispatch_ready,
)
from test_helpers.test_users import DISPATCHER_HEADERS, make_driver_headers, make_rider_headers

SERVICE_DAY_OPEN_UTC = "2026-08-03T06:00:00Z"


# ─── State recipes ─────────────────────────────────────────────────────────


def _tied_candidate_blocks_state() -> dict:
    """Two OPEN base blocks whose only difference is seat capacity (20 versus 14)
    and start instant (06:00Z versus 06:30Z), plus one S0 -> S4 trip that both can
    serve with a projected detour of zero."""
    set_clock(SERVICE_DAY_OPEN_UTC)
    zone = create_active_zone()
    stops = build_corridor(zone["id"], indexes=(0, 4))
    vehicle_a = create_vehicle(zone["id"], "VA", seat_capacity=20, wav_positions=0)
    vehicle_b = create_vehicle(zone["id"], "VB", seat_capacity=14, wav_positions=0)
    driver_a = create_driver(zone["id"], "DA", wav_certified=False)
    driver_b = create_driver(zone["id"], "DB", wav_certified=False)
    rider = create_rider(zone["id"], "R1")
    block_a = create_open_block(zone["id"], vehicle_a["id"], driver_a["id"])
    block_b = create_open_block(
        zone["id"],
        vehicle_b["id"],
        driver_b["id"],
        start_utc="2026-08-03T06:30:00Z",
    )
    trip = create_trip(
        zone["id"],
        rider["id"],
        stops[0]["id"],
        stops[4]["id"],
        requested_pickup_utc="2026-08-03T07:00:00Z",
        party_size=1,
    )
    return {
        "zone": zone,
        "stops": stops,
        "block_a": block_a,
        "block_b": block_b,
        "trip": trip,
    }


def _scheduled_block_only_state() -> dict:
    """A dispatch-ready zone whose single block is still SCHEDULED, so the
    candidate set for the trip below is empty until the block is opened."""
    state = setup_dispatch_ready(corridor=(0, 4), open_the_block=False)
    state["trip"] = create_trip(
        state["zone"]["id"],
        state["rider"]["id"],
        state["stops"][0]["id"],
        state["stops"][4]["id"],
        requested_pickup_utc="2026-08-03T07:00:00Z",
        party_size=1,
    )
    return state


def _two_offers_on_one_block_state() -> dict:
    """Two structurally identical OFFERED assignments on one open block: a
    two-seat party and a one-seat party, both S0 -> S4 promised at 07:00Z."""
    state = setup_dispatch_ready(corridor=(0, 4))
    zone_id = state["zone"]["id"]
    origin, destination = state["stops"][0]["id"], state["stops"][4]["id"]
    rider_two = create_rider(zone_id, "R2")
    trip_one = create_trip(
        zone_id,
        state["rider"]["id"],
        origin,
        destination,
        requested_pickup_utc="2026-08-03T07:00:00Z",
        party_size=2,
    )
    offer_one = dispatch_trip(trip_one["id"], state["block"]["id"])
    trip_two = create_trip(
        zone_id,
        rider_two["id"],
        origin,
        destination,
        requested_pickup_utc="2026-08-03T07:00:00Z",
        party_size=1,
    )
    offer_two = dispatch_trip(trip_two["id"], state["block"]["id"])
    block = refresh_block(state["block"]["id"])
    assert block["seats_committed"] == 3, block["seats_committed"]
    assert refresh_driver(state["driver"]["id"])["consecutive_decline_count"] == 0
    state.update(
        {
            "rider_two": rider_two,
            "trip_one": trip_one,
            "trip_two": trip_two,
            "offer_one": offer_one,
            "offer_two": offer_two,
            "block": block,
        }
    )
    return state


def _detour_boundary_state() -> dict:
    """Two open blocks whose committed corridor spans differ by one index step
    (0..4 versus 0..5) and two identical S0 -> S2 trips waiting to be dispatched,
    one onto each block. The zone's curb ceiling is raised to 6 so curb
    congestion can never bind before the detour comparison."""
    set_clock(SERVICE_DAY_OPEN_UTC)
    zone = create_active_zone(
        name="Riverbend Detour Lab",
        zone_code="RBM-DTR",
        detour_tolerance_pct=0.25,
        detour_tolerance_floor_minutes=6,
        curb_capacity_per_bucket=6,
    )
    stops = build_corridor(zone["id"], indexes=(0, 2, 4, 5))
    vehicle_one = create_vehicle(zone["id"], "V1", seat_capacity=6, wav_positions=0)
    vehicle_two = create_vehicle(zone["id"], "V2", seat_capacity=6, wav_positions=0)
    driver_one = create_driver(zone["id"], "D1", wav_certified=False)
    driver_two = create_driver(zone["id"], "D2", wav_certified=False)
    rider_a = create_rider(zone["id"], "RA")
    rider_b = create_rider(zone["id"], "RB")
    rider_ok = create_rider(zone["id"], "RT1")
    rider_bad = create_rider(zone["id"], "RT2")
    block_a = create_open_block(zone["id"], vehicle_one["id"], driver_one["id"])
    block_b = create_open_block(zone["id"], vehicle_two["id"], driver_two["id"])
    anchor_a = create_trip(
        zone["id"],
        rider_a["id"],
        stops[0]["id"],
        stops[4]["id"],
        requested_pickup_utc="2026-08-03T07:00:00Z",
        party_size=1,
    )
    dispatch_trip(anchor_a["id"], block_a["id"])
    anchor_b = create_trip(
        zone["id"],
        rider_b["id"],
        stops[0]["id"],
        stops[5]["id"],
        requested_pickup_utc="2026-08-03T07:00:00Z",
        party_size=1,
    )
    dispatch_trip(anchor_b["id"], block_b["id"])
    trip_ok = create_trip(
        zone["id"],
        rider_ok["id"],
        stops[0]["id"],
        stops[2]["id"],
        requested_pickup_utc="2026-08-03T07:00:00Z",
        party_size=1,
    )
    trip_bad = create_trip(
        zone["id"],
        rider_bad["id"],
        stops[0]["id"],
        stops[2]["id"],
        requested_pickup_utc="2026-08-03T07:00:00Z",
        party_size=1,
    )
    assertions.assert_block_commitments(
        refresh_block(block_a["id"]), committed_index_min=0, committed_index_max=4
    )
    assertions.assert_block_commitments(
        refresh_block(block_b["id"]), committed_index_min=0, committed_index_max=5
    )
    return {
        "zone": zone,
        "stops": stops,
        "block_a": block_a,
        "block_b": block_b,
        "trip_ok": trip_ok,
        "trip_bad": trip_bad,
    }


def _curb_bucket_state() -> dict:
    """Three open blocks in a zone whose curb ceiling is 2, plus four S0 -> S4
    trips requested at 07:00, 07:05, 07:10 and 07:20. The first two are already
    offered — on two different blocks — so the 07:00-07:15 curb bucket at S0 is
    full before the trigger."""
    set_clock(SERVICE_DAY_OPEN_UTC)
    zone = create_active_zone()
    stops = build_corridor(zone["id"], indexes=(0, 4))
    blocks = []
    for index in (1, 2, 3):
        vehicle = create_vehicle(
            zone["id"], f"V{index}", seat_capacity=6, wav_positions=0
        )
        driver = create_driver(zone["id"], f"D{index}", wav_certified=False)
        blocks.append(create_open_block(zone["id"], vehicle["id"], driver["id"]))
    trips = []
    riders = []
    for index, pickup in enumerate(
        (
            "2026-08-03T07:00:00Z",
            "2026-08-03T07:05:00Z",
            "2026-08-03T07:10:00Z",
            "2026-08-03T07:20:00Z",
        ),
        start=1,
    ):
        rider = create_rider(zone["id"], f"R{index}")
        riders.append(rider)
        trips.append(
            create_trip(
                zone["id"],
                rider["id"],
                stops[0]["id"],
                stops[4]["id"],
                requested_pickup_utc=pickup,
                party_size=1,
            )
        )
    offer_one = dispatch_trip(trips[0]["id"], blocks[0]["id"])
    offer_two = dispatch_trip(trips[1]["id"], blocks[1]["id"])
    return {
        "zone": zone,
        "stops": stops,
        "blocks": blocks,
        "riders": riders,
        "trips": trips,
        "offer_one": offer_one,
        "offer_two": offer_two,
    }


def _wheelchair_offer_state() -> dict:
    """One OFFERED assignment holding two seats and one securement position on an
    open block whose capacity fields read 0 / 0 / null / null before the offer."""
    state = setup_dispatch_ready(
        corridor=(0, 4),
        rider_overrides={"rider_code": "RW", "mobility_device": "WHEELCHAIR"},
    )
    assertions.assert_block_commitments(
        state["block"],
        seats_committed=0,
        wav_positions_committed=0,
        committed_index_min=None,
        committed_index_max=None,
    )
    trip = create_trip(
        state["zone"]["id"],
        state["rider"]["id"],
        state["stops"][0]["id"],
        state["stops"][4]["id"],
        requested_pickup_utc="2026-08-03T07:00:00Z",
        party_size=2,
    )
    assert trip["wav_required"] is True, trip["wav_required"]
    offer = dispatch_trip(trip["id"], state["block"]["id"])
    block = refresh_block(state["block"]["id"])
    assertions.assert_block_commitments(
        block,
        seats_committed=2,
        wav_positions_committed=1,
        committed_index_min=0,
        committed_index_max=4,
    )
    assertions.assert_trip_state(refresh_trip(trip["id"]), "OFFERED", "QUOTED")
    state.update({"trip": trip, "offer": offer, "block": block})
    return state


# ─── Match scoring: the seat-slack term and the pinned tie-break ───────────


class TestMatchScoreSeatSlackSaturation:
    def test_seat_slack_term_saturates_at_twelve_so_the_winning_score_is_24(self):
        """A 20-seat block scores 24 because the seat-slack term caps its 19 free seats at 12.

        PRD: "The fourth is a seat-slack term that prefers fuller vehicles: take the seats that would remain after this trip boarded, that is the vehicle's `seat_capacity` minus the block's `seats_committed` minus the trip's `party_size`, cap that at 12, and multiply by 2."

        Design: Difficulty/combinatorial_formula/pool_match_score_seat_slack_saturation_forces_tiebreak
        """
        state = _tied_candidate_blocks_state()

        offered = validate_success(
            api_client.match_trip_request(state["trip"]["id"], DISPATCHER_HEADERS), 200
        )

        assertions.assert_trip_state(offered, "OFFERED")
        rows = assignments_for_trip(state["trip"]["id"])
        assertions.assert_row_count(rows, 1)
        # Detour 0 * 4 = 0, BASE surge penalty 0, no securement penalty, and the
        # seat slack min(12, 20 - 0 - 1) * 2 = 24.
        assertions.assert_fields(
            rows[0],
            block_id=state["block_a"]["id"],
            match_score=24,
            offer_origin="AUTO_MATCH",
            baseline_direct_minutes=12,
            projected_detour_minutes=0,
            state="OFFERED",
        )

    def test_tied_scores_are_broken_by_the_earlier_block_start_instant(self):
        """Two candidates that both score 24 hand the offer to the block starting at 06:00Z.

        PRD: "When two candidates tie on `match_score`, the block with the earlier `start_utc` wins; if they also share a start instant, the block with the earlier `created_at` wins."

        Design: Difficulty/combinatorial_formula/pool_match_score_seat_slack_saturation_forces_tiebreak
        """
        state = _tied_candidate_blocks_state()
        assertions.assert_instant_equals(
            state["block_a"]["start_utc"], "2026-08-03T06:00:00Z"
        )
        assertions.assert_instant_equals(
            state["block_b"]["start_utc"], "2026-08-03T06:30:00Z"
        )

        validate_success(
            api_client.match_trip_request(state["trip"]["id"], DISPATCHER_HEADERS), 200
        )

        trip = refresh_trip(state["trip"]["id"])
        assertions.assert_fields(
            trip,
            status="OFFERED",
            assigned_block_id=state["block_a"]["id"],
            match_attempt_count=1,
        )
        winner = refresh_block(state["block_a"]["id"])
        assertions.assert_block_commitments(
            winner, seats_committed=1, committed_index_min=0, committed_index_max=4
        )
        loser = refresh_block(state["block_b"]["id"])
        assertions.assert_block_commitments(
            loser,
            seats_committed=0,
            wav_positions_committed=0,
            committed_index_min=None,
            committed_index_max=None,
        )


# ─── Matching self-loop and the parallel fare axis ─────────────────────────


class TestMatchingSelfLoopAndFareAxis:
    def test_empty_candidate_set_self_loops_without_counting_an_attempt(self):
        """Two matching rounds against a still-SCHEDULED block leave the trip MATCHING, uncounted and unpriced.

        PRD: "A trip in `RECEIVED` moves to `MATCHING`, and a trip already in `MATCHING` stays in `MATCHING` as a self-loop, staying queued for another round; either way `match_attempt_count` is *not* incremented, because no offer was created, and the trip's `version` advances by 1."

        Design: Difficulty/non_linear_state_machine/trip_matching_self_loop_then_offer_with_parallel_fare_axis
        """
        state = _scheduled_block_only_state()
        trip_id = state["trip"]["id"]

        first = validate_success(
            api_client.match_trip_request(trip_id, DISPATCHER_HEADERS), 200
        )
        second = validate_success(
            api_client.match_trip_request(trip_id, DISPATCHER_HEADERS), 200
        )

        assertions.assert_fields(first, status="MATCHING", match_attempt_count=0)
        assertions.assert_trip_state(first, "MATCHING", "UNPRICED")
        assertions.assert_version_advanced(state["trip"], first)
        assertions.assert_fields(second, status="MATCHING", match_attempt_count=0)
        assertions.assert_trip_state(second, "MATCHING", "UNPRICED")
        assertions.assert_version_advanced(first, second)
        assertions.assert_null_fields(
            second, "assigned_block_id", "quoted_fare_cents", "no_service_reason"
        )
        _, meta = validate_paginated(
            api_client.list_pool_assignments(
                DISPATCHER_HEADERS, params={"trip_request_id": trip_id}
            )
        )
        assert meta["total_count"] == 0, meta

    def test_opening_the_block_turns_the_same_trigger_into_an_offer(self):
        """Once the block is OPEN the third matching round offers the trip and quotes it at 325 cents.

        PRD: "When a block does win, the trip is offered onto it and the fulfilment axis advances `RECEIVED → OFFERED` or `MATCHING → OFFERED`; the two share an identical side-effect set."

        Design: Difficulty/non_linear_state_machine/trip_matching_self_loop_then_offer_with_parallel_fare_axis
        """
        state = _scheduled_block_only_state()
        trip_id = state["trip"]["id"]
        validate_success(
            api_client.match_trip_request(trip_id, DISPATCHER_HEADERS), 200
        )
        validate_success(
            api_client.match_trip_request(trip_id, DISPATCHER_HEADERS), 200
        )
        open_block(state["block"]["id"])

        offered = validate_success(
            api_client.match_trip_request(trip_id, DISPATCHER_HEADERS), 200
        )

        # Baseline direct ride 12 minutes is the MEDIUM band, so the quote is
        # 250 base + 75 surcharge with a FULL multiplier of 1.00.
        assertions.assert_fields(
            offered,
            status="OFFERED",
            match_attempt_count=1,
            fare_status="QUOTED",
            quoted_fare_cents=325,
            assigned_block_id=state["block"]["id"],
            no_service_reason=None,
        )
        rows = assignments_for_trip(trip_id)
        assertions.assert_row_count(rows, 1)
        assertions.assert_assignment_state(rows[0], "OFFERED")


# ─── The OFFERED fork: accept versus decline ───────────────────────────────


class TestOfferedBranchDivergence:
    def test_accept_confirms_the_reservation_without_moving_committed_capacity(self):
        """Accepting the two-seat offer advances the trip to ASSIGNED and leaves the block's committed capacity where the offer put it.

        PRD: "Notably, the block's `seats_committed` and `wav_positions_committed` do **not** change here: the capacity was already held from the moment the offer was created, so acceptance merely confirms a reservation rather than making one."

        Design: Difficulty/non_linear_state_machine/pool_assignment_offered_branch_accept_vs_decline_side_effect_sets_diverge
        """
        state = _two_offers_on_one_block_state()
        driver_headers = make_driver_headers(state["driver"]["id"])

        accepted = validate_success(
            api_client.accept_pool_assignment(
                state["offer_one"]["id"], driver_headers
            ),
            200,
        )

        assertions.assert_assignment_state(accepted, "ACCEPTED")
        assert accepted["seats_held"] == 2, accepted["seats_held"]
        trip_one = refresh_trip(state["trip_one"]["id"])
        assertions.assert_trip_state(trip_one, "ASSIGNED", "QUOTED")
        assertions.assert_fields(
            trip_one,
            quoted_fare_cents=325,
            assigned_block_id=state["block"]["id"],
        )
        block = refresh_block(state["block"]["id"])
        assertions.assert_block_commitments(
            block,
            seats_committed=3,
            wav_positions_committed=0,
            committed_index_min=0,
            committed_index_max=4,
        )
        assert refresh_driver(state["driver"]["id"])["consecutive_decline_count"] == 0

    def test_decline_unbooks_the_trip_and_advances_the_decline_streak(self):
        """Declining the one-seat offer returns its seat, voids the quote and sends the trip back to MATCHING.

        PRD: "The second hop, caused by the first, does two things at once: the driver's `consecutive_decline_count` increases by 1, and the trip is un-booked — `assigned_block_id`, `promised_pickup_utc`, `promised_dropoff_utc` and `projected_detour_minutes` are cleared to null and a `fare_status` of `QUOTED` or `CAPPED` reverts to `UNPRICED` with `quoted_fare_cents` cleared to null, after which the trip returns `OFFERED → MATCHING` if its `match_attempt_count` is still below 2, or instead moves `OFFERED → NO_SERVICE` with `no_service_reason` set to `MAX_ATTEMPTS_EXHAUSTED` and the zone's `unserved_trip_count` recomputed when that count has already reached 2."

        Design: Difficulty/non_linear_state_machine/pool_assignment_offered_branch_accept_vs_decline_side_effect_sets_diverge
        """
        state = _two_offers_on_one_block_state()
        driver_headers = make_driver_headers(state["driver"]["id"])
        validate_success(
            api_client.accept_pool_assignment(
                state["offer_one"]["id"], driver_headers
            ),
            200,
        )

        declined = validate_success(
            api_client.decline_pool_assignment(
                state["offer_two"]["id"],
                driver_headers,
                {"reason": "detour too long for this manifest"},
            ),
            200,
        )

        assertions.assert_assignment_state(declined, "DECLINED")
        trip_two = refresh_trip(state["trip_two"]["id"])
        assertions.assert_trip_state(trip_two, "MATCHING", "UNPRICED")
        assertions.assert_null_fields(
            trip_two,
            "quoted_fare_cents",
            "assigned_block_id",
            "promised_pickup_utc",
            "promised_dropoff_utc",
            "projected_detour_minutes",
        )
        assert trip_two["match_attempt_count"] == 1, trip_two["match_attempt_count"]
        block = refresh_block(state["block"]["id"])
        assertions.assert_block_commitments(
            block,
            seats_committed=2,
            wav_positions_committed=0,
            committed_index_min=0,
            committed_index_max=4,
        )
        driver = refresh_driver(state["driver"]["id"])
        assertions.assert_fields(
            driver, consecutive_decline_count=1, status="ACTIVE"
        )


# ─── The detour allowance at exact equality ────────────────────────────────


class TestDetourAllowanceInclusiveBoundary:
    def test_projected_detour_equal_to_the_allowance_is_offered(self):
        """A six-minute projected detour against a six-minute allowance is dispatched, not rejected.

        PRD: "The projected detour must be less than or equal to the trip's detour allowance — the comparison is inclusive — with a violation reported as `ERR_DETOUR_TOLERANCE_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/detour_allowance_inclusive_equality_accepted_next_step_rejected
        """
        state = _detour_boundary_state()
        # Baseline S0 -> S2 is 6 minutes, so the allowance is max(6, ceil(6 * 0.25)
        # = 2) = 6, and the 0..4 envelope makes the projected detour 3 * 4 - 6 = 6.
        offer = validate_success(
            api_client.create_pool_assignment(
                pool_assignment_payload(
                    state["trip_ok"]["id"],
                    state["block_a"]["id"],
                    block_version(state["block_a"]["id"]),
                ),
                DISPATCHER_HEADERS,
            ),
            201,
        )

        assertions.assert_fields(
            offer,
            state="OFFERED",
            baseline_direct_minutes=6,
            projected_detour_minutes=6,
            seq_pickup=2,
            offer_origin="MANUAL_DISPATCH",
            match_score=None,
        )
        trip_ok = refresh_trip(state["trip_ok"]["id"])
        assertions.assert_fields(
            trip_ok,
            status="OFFERED",
            baseline_direct_minutes=6,
            projected_detour_minutes=6,
            assigned_block_id=state["block_a"]["id"],
        )
        assertions.assert_block_commitments(
            refresh_block(state["block_a"]["id"]),
            seats_committed=2,
            committed_index_min=0,
            committed_index_max=4,
        )

    def test_projected_detour_one_index_step_past_the_allowance_is_rejected(self):
        """The same trip geometry against a 0..5 envelope projects nine minutes of detour and is refused.

        PRD: "The projected detour must be less than or equal to the trip's detour allowance — the comparison is inclusive — with a violation reported as `ERR_DETOUR_TOLERANCE_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/detour_allowance_inclusive_equality_accepted_next_step_rejected
        """
        state = _detour_boundary_state()
        # The 0..5 envelope makes the projected detour 3 * 5 - 6 = 9 > 6.
        response = api_client.create_pool_assignment(
            pool_assignment_payload(
                state["trip_bad"]["id"],
                state["block_b"]["id"],
                block_version(state["block_b"]["id"]),
            ),
            DISPATCHER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_DETOUR_TOLERANCE_EXCEEDED.value)
        trip_bad = refresh_trip(state["trip_bad"]["id"])
        # Intake computed the baseline direct ride straight away, so it survives
        # the rejection; only the offer-time detour is still unwritten.
        assertions.assert_fields(
            trip_bad,
            status="RECEIVED",
            fare_status="UNPRICED",
            baseline_direct_minutes=6,
            projected_detour_minutes=None,
            assigned_block_id=None,
            match_attempt_count=0,
        )
        assertions.assert_block_commitments(
            refresh_block(state["block_b"]["id"]),
            seats_committed=1,
            committed_index_min=0,
            committed_index_max=5,
        )


# ─── Curb capacity: one quarter-hour bucket across three blocks ────────────


class TestCurbBucketCapacity:
    def test_third_pickup_in_the_same_bucket_is_refused_even_on_a_third_block(self):
        """The 07:00-07:15 bucket at S0 is counted across blocks, so a 07:10 pickup is refused while 07:20 is not.

        PRD: "And the curb at the origin stop must have room: the number of pool assignments in state `OFFERED`, `ACCEPTED` or `ONBOARD` whose trip shares this trip's `origin_stop_id` and whose trip's `promised_pickup_utc` falls in the same quarter-hour bucket as this offer's prospective promised pickup must be strictly less than the zone's `curb_capacity_per_bucket`."

        Design: Difficulty/resource_temporal_overlap/curb_bucket_capacity_aggregates_across_blocks_and_frees_on_release
        """
        state = _curb_bucket_state()
        third_block = state["blocks"][2]

        rejected = api_client.create_pool_assignment(
            pool_assignment_payload(
                state["trips"][2]["id"],
                third_block["id"],
                block_version(third_block["id"]),
            ),
            DISPATCHER_HEADERS,
        )

        validate_error(rejected, ApiErrorId.ERR_CURB_CAPACITY_EXCEEDED.value)
        blocked_trip = refresh_trip(state["trips"][2]["id"])
        assertions.assert_fields(
            blocked_trip,
            status="RECEIVED",
            match_attempt_count=0,
            assigned_block_id=None,
        )

        # 07:20 falls in the next quarter-hour bucket, which is still empty.
        next_bucket_offer = validate_success(
            api_client.create_pool_assignment(
                pool_assignment_payload(
                    state["trips"][3]["id"],
                    third_block["id"],
                    block_version(third_block["id"]),
                ),
                DISPATCHER_HEADERS,
            ),
            201,
        )
        assertions.assert_assignment_state(next_bucket_offer, "OFFERED")
        assertions.assert_instant_equals(
            refresh_trip(state["trips"][3]["id"])["promised_pickup_utc"],
            "2026-08-03T07:20:00Z",
        )

    def test_cancelling_the_first_trip_releases_its_curb_slot(self):
        """Releasing the 07:00 offer through a rider cancellation lets the previously refused 07:10 offer succeed.

        PRD: "From `OFFERED → CANCELLED` and `ASSIGNED → CANCELLED` the offer must be given back, and both branches carry the same effects: the trip's pool assignment — in `OFFERED` for the first branch, in `ACCEPTED` for the second — moves to `RELEASED`; the block reduces `seats_committed` by that assignment's `seats_held` and `wav_positions_committed` by its `wav_positions_held`, recomputes `committed_index_min` and `committed_index_max`, and advances its `version` by 1; the trip's `assigned_block_id`, `promised_pickup_utc`, `promised_dropoff_utc` and `projected_detour_minutes` are cleared to null; and a `fare_status` of `QUOTED` reverts to `UNPRICED` with `quoted_fare_cents` cleared to null."

        Design: Difficulty/resource_temporal_overlap/curb_bucket_capacity_aggregates_across_blocks_and_frees_on_release
        """
        state = _curb_bucket_state()
        third_block = state["blocks"][2]
        validate_error(
            api_client.create_pool_assignment(
                pool_assignment_payload(
                    state["trips"][2]["id"],
                    third_block["id"],
                    block_version(third_block["id"]),
                ),
                DISPATCHER_HEADERS,
            ),
            ApiErrorId.ERR_CURB_CAPACITY_EXCEEDED.value,
        )
        validate_success(
            api_client.create_pool_assignment(
                pool_assignment_payload(
                    state["trips"][3]["id"],
                    third_block["id"],
                    block_version(third_block["id"]),
                ),
                DISPATCHER_HEADERS,
            ),
            201,
        )

        cancelled = validate_success(
            api_client.cancel_trip_request(
                state["trips"][0]["id"],
                make_rider_headers(state["riders"][0]["id"]),
                {"note": "rider found another ride"},
            ),
            200,
        )

        assertions.assert_trip_state(cancelled, "CANCELLED", "UNPRICED")
        assertions.assert_null_fields(
            cancelled,
            "assigned_block_id",
            "quoted_fare_cents",
            "promised_pickup_utc",
            "promised_dropoff_utc",
            "projected_detour_minutes",
        )
        released = api_client.get_pool_assignment(
            state["offer_one"]["id"], DISPATCHER_HEADERS
        )
        assertions.assert_assignment_state(
            validate_success(released, 200), "RELEASED"
        )
        assertions.assert_block_commitments(
            refresh_block(state["blocks"][0]["id"]),
            seats_committed=0,
            wav_positions_committed=0,
            committed_index_min=None,
            committed_index_max=None,
        )

        retried = validate_success(
            api_client.create_pool_assignment(
                pool_assignment_payload(
                    state["trips"][2]["id"],
                    third_block["id"],
                    block_version(third_block["id"]),
                ),
                DISPATCHER_HEADERS,
            ),
            201,
        )
        assertions.assert_fields(
            retried, state="OFFERED", projected_detour_minutes=0
        )
        assertions.assert_fields(
            refresh_trip(state["trips"][2]["id"]),
            status="OFFERED",
            match_attempt_count=1,
            quoted_fare_cents=325,
        )
        assertions.assert_block_commitments(
            refresh_block(third_block["id"]),
            seats_committed=2,
            committed_index_min=0,
            committed_index_max=4,
        )
        untouched = validate_success(
            api_client.get_pool_assignment(
                state["offer_two"]["id"], DISPATCHER_HEADERS
            ),
            200,
        )
        assertions.assert_assignment_state(untouched, "OFFERED")


# ─── Decline as an exact compensation of the offer ─────────────────────────


class TestDeclineRestoresBlockCapacity:
    def test_decline_zeroes_the_holds_and_collapses_the_corridor_envelope(self):
        """A decline returns both seats and the securement position and drops the envelope back to null.

        PRD: "The first hop returns the block's capacity: `seats_committed` is reduced by the assignment's `seats_held`, `wav_positions_committed` is reduced by its `wav_positions_held`, `committed_index_min` and `committed_index_max` are recomputed over the narrowed envelope, and the block's `version` advances by 1."

        Design: Difficulty/compensating_invariant/seat_and_securement_capacity_returns_to_zero_after_decline
        """
        state = _wheelchair_offer_state()
        driver_headers = make_driver_headers(state["driver"]["id"])

        validate_success(
            api_client.decline_pool_assignment(
                state["offer"]["id"],
                driver_headers,
                {"reason": "securement strap out of service"},
            ),
            200,
        )

        block = refresh_block(state["block"]["id"])
        assertions.assert_block_commitments(
            block,
            seats_committed=0,
            wav_positions_committed=0,
            committed_index_min=None,
            committed_index_max=None,
        )
        assertions.assert_fields(block, boardings_count=0, state="OPEN")
        assertions.assert_version_advanced(state["block"], block)
        _, live_meta = validate_paginated(
            api_client.list_pool_assignments(
                DISPATCHER_HEADERS,
                params={"block_id": state["block"]["id"], "state": "OFFERED"},
            )
        )
        assert live_meta["total_count"] == 0, live_meta
        _, ledger_meta = validate_paginated(
            api_client.list_fare_transactions(
                DISPATCHER_HEADERS, params={"trip_request_id": state["trip"]["id"]}
            )
        )
        assert ledger_meta["total_count"] == 0, ledger_meta

    def test_declined_assignment_keeps_its_frozen_holds_while_the_trip_is_voided(self):
        """The declined row still records two seats held and one securement position held, yet the trip is unpriced and re-queued.

        PRD: "A pool assignment's `seats_held` is copied from the trip's `party_size` at creation and never changes thereafter, and its `wav_positions_held` is 1 when the trip's `wav_required` is true and 0 otherwise, likewise frozen."

        Design: Difficulty/compensating_invariant/seat_and_securement_capacity_returns_to_zero_after_decline
        """
        state = _wheelchair_offer_state()
        driver_headers = make_driver_headers(state["driver"]["id"])

        declined = validate_success(
            api_client.decline_pool_assignment(
                state["offer"]["id"],
                driver_headers,
                {"reason": "securement strap out of service"},
            ),
            200,
        )

        assertions.assert_fields(
            declined,
            state="DECLINED",
            seats_held=2,
            wav_positions_held=1,
            baseline_direct_minutes=12,
            projected_detour_minutes=0,
        )
        trip = refresh_trip(state["trip"]["id"])
        assertions.assert_trip_state(trip, "MATCHING", "UNPRICED")
        assertions.assert_fields(trip, match_attempt_count=1, wav_required=True)
        assertions.assert_null_fields(
            trip,
            "assigned_block_id",
            "projected_detour_minutes",
            "promised_pickup_utc",
            "promised_dropoff_utc",
            "quoted_fare_cents",
        )
        driver = refresh_driver(state["driver"]["id"])
        assertions.assert_fields(
            driver, consecutive_decline_count=1, status="ACTIVE"
        )
