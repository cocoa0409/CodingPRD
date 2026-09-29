"""Operational validation rules: block close vs. cancel, stop retirement, refund
eligibility, securement capacity, fleet sizing and segregation of duties.

Every test builds its own state through test_helpers, because the server is
restarted with an empty database before each test and the logical clock reads
2026-08-01T00:00:00Z until a recipe moves it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import pool_assignment_payload
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    DISPATCHER_HEADERS,
    FINANCE_ANALYST_HEADERS,
    ZONE_ADMIN_HEADERS,
    make_auditor_headers,
    make_rider_headers,
)

BLOCK_START = "2026-08-03T06:00:00Z"
BLOCK_END = "2026-08-03T10:00:00Z"


# ─── Local state builders ──────────────────────────────────────────────────


def _block_with_offered_and_onboard_trips() -> dict:
    """Zone RBM ACTIVE, block B1 OPEN over [06:00, 10:00) on the service day,
    trip T1 merely OFFERED and trip T2 boarded at 07:05Z."""
    fixtures.set_clock(BLOCK_START)
    zone = fixtures.create_active_zone(
        fare_cap_cents_daily=2000, fare_cap_cents_weekly=5000
    )
    stop_0 = fixtures.create_approved_stop(zone["id"], "S0", 0)
    stop_4 = fixtures.create_approved_stop(zone["id"], "S4", 4)
    vehicle = fixtures.create_vehicle(
        zone["id"], "V1", seat_capacity=6, wav_positions=2
    )
    driver = fixtures.create_driver(zone["id"], "D1", wav_certified=True)
    rider_1 = fixtures.create_rider(zone["id"], "R1")
    rider_2 = fixtures.create_rider(zone["id"], "R2")
    block = fixtures.create_open_block(
        zone["id"],
        vehicle["id"],
        driver["id"],
        block_type="BASE",
        start_utc=BLOCK_START,
        end_utc=BLOCK_END,
    )
    trip_1 = fixtures.create_trip(
        zone["id"],
        rider_1["id"],
        stop_0["id"],
        stop_4["id"],
        requested_pickup_utc="2026-08-03T07:00:00Z",
        party_size=1,
    )
    assignment_1 = fixtures.dispatch_trip(trip_1["id"], block["id"])
    trip_2 = fixtures.create_trip(
        zone["id"],
        rider_2["id"],
        stop_0["id"],
        stop_4["id"],
        requested_pickup_utc="2026-08-03T07:05:00Z",
        party_size=1,
    )
    assignment_2 = fixtures.dispatch_trip(trip_2["id"], block["id"])
    fixtures.accept_assignment(assignment_2["id"], driver["id"])
    fixtures.set_clock("2026-08-03T07:05:00Z")
    assignment_2 = fixtures.board_assignment(assignment_2["id"], driver["id"])
    return {
        "zone": zone,
        "driver": driver,
        "rider_2": rider_2,
        "block": block,
        "trip_1": trip_1,
        "trip_2": trip_2,
        "assignment_1": assignment_1,
        "assignment_2": assignment_2,
    }


def _zone_with_two_stops_and_a_received_trip() -> dict:
    """Zone RBM ACTIVE with stops S0 and S2 approved and one trip S0 -> S2 that
    is still in RECEIVED, so both of its stops are pinned."""
    fixtures.set_clock(BLOCK_START)
    zone = fixtures.create_active_zone()
    stop_0 = fixtures.create_approved_stop(zone["id"], "S0", 0)
    stop_2 = fixtures.create_approved_stop(zone["id"], "S2", 2)
    rider = fixtures.create_rider(zone["id"], "R1")
    trip = fixtures.create_trip(
        zone["id"],
        rider["id"],
        stop_0["id"],
        stop_2["id"],
        requested_pickup_utc="2026-08-03T07:00:00Z",
        party_size=1,
    )
    return {
        "zone": zone,
        "stop_0": stop_0,
        "stop_2": stop_2,
        "rider": rider,
        "trip": trip,
    }


def _two_base_blocks_and_a_forecast(window_start: str, window_end: str) -> dict:
    """Zone RBM ACTIVE with one published forecast over the given window and two
    BASE blocks over [06:00, 10:00) on distinct vehicles and drivers."""
    fixtures.set_clock("2026-08-03T05:00:00Z")
    zone = fixtures.create_active_zone()
    forecast = fixtures.create_forecast(
        zone["id"],
        window_start_utc=window_start,
        window_end_utc=window_end,
        forecast_trips=10,
        peak_factor=1.20,
    )
    vehicle_1 = fixtures.create_vehicle(
        zone["id"], "V1", seat_capacity=6, wav_positions=2
    )
    vehicle_2 = fixtures.create_vehicle(
        zone["id"], "V2", seat_capacity=6, wav_positions=2
    )
    driver_1 = fixtures.create_driver(zone["id"], "D1", wav_certified=True)
    driver_2 = fixtures.create_driver(zone["id"], "D2", wav_certified=True)
    block_1 = fixtures.create_block(
        zone["id"],
        vehicle_1["id"],
        driver_1["id"],
        block_type="BASE",
        start_utc=BLOCK_START,
        end_utc=BLOCK_END,
    )
    block_2 = fixtures.create_block(
        zone["id"],
        vehicle_2["id"],
        driver_2["id"],
        block_type="BASE",
        start_utc=BLOCK_START,
        end_utc=BLOCK_END,
    )
    return {
        "zone": zone,
        "forecast": forecast,
        "block_1": block_1,
        "block_2": block_2,
    }


def _submitted_report_on_an_empty_zone() -> dict:
    """Zone RBM ACTIVE with no blocks and no trips, plus a PROVISIONAL report for
    2026-08-03 filed by the FinanceAnalyst fa-1."""
    fixtures.set_clock("2026-08-04T06:00:00Z")
    zone = fixtures.create_active_zone()
    report = fixtures.create_report(
        zone["id"],
        headers=FINANCE_ANALYST_HEADERS,
        period_start_date="2026-08-03",
        period_end_date="2026-08-03",
        variant="PROVISIONAL",
    )
    report = fixtures.submit_report(report["id"], headers=FINANCE_ANALYST_HEADERS)
    return {"zone": zone, "report": report}


# ─── Vehicle-block close and cancel ────────────────────────────────────────


class TestBlockCloseAndCancelGuards:
    def test_close_is_refused_while_any_assignment_is_offered_accepted_or_onboard(
        self,
    ):
        """Closing a block fails while an offer or an onboard rider remains on it.

        PRD: "If any pool assignment on the block is still in `OFFERED`, `ACCEPTED` or `ONBOARD`, the close is rejected with `ERR_BLOCK_HAS_ACTIVE_ASSIGNMENTS`."

        Design: Corner/validations/close_is_blocked_by_any_live_assignment_but_cancel_only_by_an_onboard_one
        """
        state = _block_with_offered_and_onboard_trips()
        block_id = state["block"]["id"]

        # T1 is OFFERED and T2 is ONBOARD: the manifest is not quiet.
        refused = api_client.close_vehicle_block(block_id, DISPATCHER_HEADERS)
        validate_error(refused, ApiErrorId.ERR_BLOCK_HAS_ACTIVE_ASSIGNMENTS.value)
        assert refused.status_code == 409

        after_refusal = fixtures.refresh_block(block_id)
        assertions.assert_block_state(after_refusal, "OPEN")
        assertions.assert_null_fields(after_refusal, "closed_at")

        # The onboard ride finishes; the OFFERED sibling alone still blocks a close.
        fixtures.set_clock("2026-08-03T07:17:00Z")
        fixtures.complete_assignment(
            state["assignment_2"]["id"], state["driver"]["id"]
        )
        assertions.assert_assignment_state(
            fixtures.refresh_assignment(state["assignment_1"]["id"]), "OFFERED"
        )

        still_refused = api_client.close_vehicle_block(block_id, DISPATCHER_HEADERS)
        validate_error(
            still_refused, ApiErrorId.ERR_BLOCK_HAS_ACTIVE_ASSIGNMENTS.value
        )
        assert still_refused.status_code == 409

        final_block = fixtures.refresh_block(block_id)
        assertions.assert_block_state(final_block, "OPEN")
        assertions.assert_null_fields(final_block, "closed_at")

    def test_cancel_is_refused_only_while_a_rider_is_onboard(self):
        """Cancelling an open block fails only for an onboard rider, then releases the offer.

        PRD: "It is refused outright, with `ERR_BLOCK_HAS_ACTIVE_ASSIGNMENTS`, whenever any assignment on the block is `ONBOARD` — a rider already in the vehicle cannot be un-ridden."

        Design: Corner/validations/close_is_blocked_by_any_live_assignment_but_cancel_only_by_an_onboard_one
        """
        state = _block_with_offered_and_onboard_trips()
        block_id = state["block"]["id"]

        refused = api_client.cancel_vehicle_block(block_id, DISPATCHER_HEADERS)
        validate_error(refused, ApiErrorId.ERR_BLOCK_HAS_ACTIVE_ASSIGNMENTS.value)
        assert refused.status_code == 409
        assertions.assert_block_state(fixtures.refresh_block(block_id), "OPEN")

        # Once the onboard ride completes, the remaining OFFERED assignment does
        # not stand in the way of a cancellation.
        fixtures.set_clock("2026-08-03T07:17:00Z")
        fixtures.complete_assignment(
            state["assignment_2"]["id"], state["driver"]["id"]
        )

        cancelled = api_client.cancel_vehicle_block(block_id, DISPATCHER_HEADERS)
        block = validate_success(cancelled, 200)
        assertions.assert_block_state(block, "CANCELLED")
        assertions.assert_block_commitments(
            block,
            seats_committed=0,
            wav_positions_committed=0,
            committed_index_min=None,
            committed_index_max=None,
        )

        assertions.assert_assignment_state(
            fixtures.refresh_assignment(state["assignment_1"]["id"]), "RELEASED"
        )
        assertions.assert_assignment_state(
            fixtures.refresh_assignment(state["assignment_2"]["id"]), "COMPLETED"
        )

        # The completed trip keeps its settled fare: a 12-minute ride is MEDIUM
        # band, so 250 + 75 cents at the FULL multiplier.
        trip_2 = fixtures.refresh_trip(state["trip_2"]["id"])
        assertions.assert_trip_state(trip_2, "COMPLETED", "CHARGED")
        assertions.assert_fields(
            trip_2, ride_minutes=12, charged_fare_cents=325, applied_cap="NONE"
        )
        assertions.assert_instant_equals(
            trip_2["actual_dropoff_utc"], "2026-08-03T07:17:00Z"
        )

        # The released offer takes the fare axis back to UNPRICED and re-queues
        # the trip, whose match_attempt_count is 1 and so still under budget.
        trip_1 = fixtures.refresh_trip(state["trip_1"]["id"])
        assertions.assert_trip_state(trip_1, "MATCHING", "UNPRICED")
        assertions.assert_null_fields(
            trip_1,
            "quoted_fare_cents",
            "assigned_block_id",
            "projected_detour_minutes",
            "promised_pickup_utc",
            "promised_dropoff_utc",
        )


# ─── Virtual-stop retirement ───────────────────────────────────────────────


class TestStopRetirementGuard:
    def test_retirement_is_refused_for_either_stop_a_live_trip_names(self):
        """A stop named by a RECEIVED trip cannot be retired from either end of the trip.

        PRD: "Both branches carry the same guard: no trip request whose `status` is `RECEIVED`, `MATCHING`, `OFFERED`, `ASSIGNED` or `PICKED_UP` may name the stop as either its `origin_stop_id` or its `destination_stop_id`, and an attempt that violates this is rejected with `ERR_STOP_IN_USE`."

        Design: Corner/validations/stop_retirement_is_blocked_while_a_live_trip_references_it
        """
        state = _zone_with_two_stops_and_a_received_trip()

        destination_refused = api_client.retire_virtual_stop(
            state["stop_2"]["id"], ZONE_ADMIN_HEADERS
        )
        validate_error(destination_refused, ApiErrorId.ERR_STOP_IN_USE.value)
        assert destination_refused.status_code == 409

        origin_refused = api_client.retire_virtual_stop(
            state["stop_0"]["id"], ZONE_ADMIN_HEADERS
        )
        validate_error(origin_refused, ApiErrorId.ERR_STOP_IN_USE.value)
        assert origin_refused.status_code == 409

        # Both rejections leave the stops exactly as they were.
        assertions.assert_fields(
            fixtures.refresh_stop(state["stop_0"]["id"]), status="APPROVED"
        )
        assertions.assert_fields(
            fixtures.refresh_stop(state["stop_2"]["id"]), status="APPROVED"
        )
        assertions.assert_trip_state(
            fixtures.refresh_trip(state["trip"]["id"]), "RECEIVED"
        )

    def test_retirement_succeeds_once_the_trip_reaches_a_terminal_status(self):
        """A cancelled trip no longer pins its stops, so the retirement then succeeds.

        PRD: "Both branches carry the same guard: no trip request whose `status` is `RECEIVED`, `MATCHING`, `OFFERED`, `ASSIGNED` or `PICKED_UP` may name the stop as either its `origin_stop_id` or its `destination_stop_id`, and an attempt that violates this is rejected with `ERR_STOP_IN_USE`."

        Design: Corner/validations/stop_retirement_is_blocked_while_a_live_trip_references_it
        """
        state = _zone_with_two_stops_and_a_received_trip()
        rider_headers = make_rider_headers(state["rider"]["id"])

        cancelled = api_client.cancel_trip_request(
            state["trip"]["id"],
            rider_headers,
            {"note": "rider no longer travelling"},
        )
        trip = validate_success(cancelled, 200)
        assertions.assert_trip_state(trip, "CANCELLED")

        retired = api_client.retire_virtual_stop(
            state["stop_2"]["id"], ZONE_ADMIN_HEADERS
        )
        stop = validate_success(retired, 200)
        assertions.assert_fields(stop, status="RETIRED")
        assertions.assert_version_advanced(state["stop_2"], stop)


# ─── Refund eligibility on the fare axis ───────────────────────────────────


class TestRefundRequiresACharge:
    def test_refund_of_a_quoted_but_unsettled_trip_is_refused(self):
        """A quoted trip that never settled cannot be refunded and writes no ledger row.

        PRD: "It moves the fare axis `CHARGED → REFUNDED`, and a trip whose `fare_status` is anything other than `CHARGED` is rejected with `ERR_TRIP_NOT_CHARGED`."

        Design: Corner/validations/refund_requires_the_fare_axis_to_have_reached_charged
        """
        fixtures.set_clock(BLOCK_START)
        zone = fixtures.create_active_zone()
        stop_0 = fixtures.create_approved_stop(zone["id"], "S0", 0)
        stop_4 = fixtures.create_approved_stop(zone["id"], "S4", 4)
        vehicle = fixtures.create_vehicle(
            zone["id"], "V1", seat_capacity=6, wav_positions=2
        )
        driver = fixtures.create_driver(zone["id"], "D1", wav_certified=True)
        rider = fixtures.create_rider(zone["id"], "R1")
        block = fixtures.create_open_block(
            zone["id"],
            vehicle["id"],
            driver["id"],
            block_type="BASE",
            start_utc=BLOCK_START,
            end_utc=BLOCK_END,
        )
        trip = fixtures.create_trip(
            zone["id"],
            rider["id"],
            stop_0["id"],
            stop_4["id"],
            requested_pickup_utc="2026-08-03T07:00:00Z",
            party_size=1,
        )
        fixtures.dispatch_trip(trip["id"], block["id"])

        # The offer priced the trip provisionally: a 12-minute baseline direct
        # ride is MEDIUM band, so 250 + 75 cents for a FULL rider.
        quoted = fixtures.refresh_trip(trip["id"])
        assertions.assert_trip_state(quoted, "OFFERED", "QUOTED")
        assertions.assert_fields(quoted, quoted_fare_cents=325)

        refused = api_client.refund_trip_request(
            trip["id"],
            {"reason": "rider complained about the quote"},
            DISPATCHER_HEADERS,
        )
        validate_error(refused, ApiErrorId.ERR_TRIP_NOT_CHARGED.value)
        assert refused.status_code == 409

        after = fixtures.refresh_trip(trip["id"])
        assertions.assert_trip_state(after, "OFFERED", "QUOTED")
        assertions.assert_null_fields(after, "charged_fare_cents")

        rows, meta = validate_paginated(
            api_client.list_fare_transactions(
                DISPATCHER_HEADERS, params={"trip_request_id": trip["id"]}
            )
        )
        assert meta["total_count"] == 0, rows
        assertions.assert_row_count(rows, 0)

        assertions.assert_fields(
            fixtures.refresh_rider(rider["id"]),
            daily_fare_paid_cents=0,
            weekly_fare_paid_cents=0,
        )


# ─── Securement positions as a capacity of their own ───────────────────────


class TestSecurementCapacityIsSeparateFromSeats:
    def test_second_wheelchair_offer_is_refused_while_seats_still_admit_a_rider(self):
        """One securement position blocks a second wheelchair trip yet still seats an ambulatory one.

        PRD: "A wheelchair-accessible trip may only be placed on a block whose vehicle has at least one securement position and whose driver is `wav_certified`, with a failure reported as `ERR_WAV_UNAVAILABLE`, and separately the block's remaining securement headroom must still be at least 1, with exhaustion reported as `ERR_WAV_POSITION_UNAVAILABLE`."

        Design: Corner/validations/securement_positions_are_a_separate_capacity_from_seats
        """
        fixtures.set_clock(BLOCK_START)
        zone = fixtures.create_active_zone()
        stop_0 = fixtures.create_approved_stop(zone["id"], "S0", 0)
        stop_4 = fixtures.create_approved_stop(zone["id"], "S4", 4)
        vehicle = fixtures.create_vehicle(
            zone["id"], "V1", seat_capacity=6, wav_positions=1
        )
        driver = fixtures.create_driver(zone["id"], "D1", wav_certified=True)
        wheelchair_rider_1 = fixtures.create_rider(
            zone["id"], "RW1", mobility_device="WHEELCHAIR"
        )
        wheelchair_rider_2 = fixtures.create_rider(
            zone["id"], "RW2", mobility_device="WHEELCHAIR"
        )
        ambulatory_rider = fixtures.create_rider(
            zone["id"], "RN", mobility_device="NONE"
        )
        block = fixtures.create_open_block(
            zone["id"],
            vehicle["id"],
            driver["id"],
            block_type="BASE",
            start_utc=BLOCK_START,
            end_utc=BLOCK_END,
        )
        trip_wav_1 = fixtures.create_trip(
            zone["id"],
            wheelchair_rider_1["id"],
            stop_0["id"],
            stop_4["id"],
            requested_pickup_utc="2026-08-03T07:00:00Z",
            party_size=1,
        )
        trip_wav_2 = fixtures.create_trip(
            zone["id"],
            wheelchair_rider_2["id"],
            stop_0["id"],
            stop_4["id"],
            requested_pickup_utc="2026-08-03T07:05:00Z",
            party_size=1,
        )
        trip_ambulatory = fixtures.create_trip(
            zone["id"],
            ambulatory_rider["id"],
            stop_0["id"],
            stop_4["id"],
            requested_pickup_utc="2026-08-03T07:20:00Z",
            party_size=1,
        )

        first_offer = api_client.create_pool_assignment(
            pool_assignment_payload(
                trip_wav_1["id"], block["id"], fixtures.block_version(block["id"])
            ),
            DISPATCHER_HEADERS,
        )
        assignment_wav_1 = validate_success(first_offer, 201)
        assertions.assert_fields(assignment_wav_1, wav_positions_held=1, seats_held=1)

        # One version read serves both remaining attempts: a rejected offer
        # consumes nothing, so the block's version does not move.
        observed_version = fixtures.block_version(block["id"])

        second_offer = api_client.create_pool_assignment(
            pool_assignment_payload(trip_wav_2["id"], block["id"], observed_version),
            DISPATCHER_HEADERS,
        )
        validate_error(second_offer, ApiErrorId.ERR_WAV_POSITION_UNAVAILABLE.value)
        assert second_offer.status_code == 409

        ambulatory_offer = api_client.create_pool_assignment(
            pool_assignment_payload(
                trip_ambulatory["id"], block["id"], observed_version
            ),
            DISPATCHER_HEADERS,
        )
        assignment_ambulatory = validate_success(ambulatory_offer, 201)
        assertions.assert_fields(
            assignment_ambulatory, wav_positions_held=0, seats_held=1
        )

        block_after = fixtures.refresh_block(block["id"])
        assertions.assert_block_commitments(
            block_after, seats_committed=2, wav_positions_committed=1
        )

        refused_trip = fixtures.refresh_trip(trip_wav_2["id"])
        assertions.assert_trip_state(refused_trip, "RECEIVED", "UNPRICED")
        assertions.assert_null_fields(refused_trip, "assigned_block_id")
        assertions.assert_fields(refused_trip, wav_required=True)


# ─── Peak-surge fleet sizing on block open ─────────────────────────────────


class TestFleetSizingCeilingOnOpen:
    def test_opening_more_base_blocks_than_the_forecast_sizes_is_rejected(self):
        """A forecast sizing one BASE block refuses the second overlapping BASE open.

        PRD: "An open that would push the count above the applicable ceiling is rejected with `ERR_FLEET_SIZE_EXCEEDED`."

        Design: Corner/validations/opening_more_blocks_than_the_forecast_allows_is_rejected
        """
        state = _two_base_blocks_and_a_forecast(BLOCK_START, BLOCK_END)

        # 10 trips over a four-hour window at four trips per block-hour:
        # ceil(10 / 16) = 1 base block, and a peak factor of 1.20 needs no surge.
        assertions.assert_fields(
            state["forecast"],
            required_base_blocks=1,
            required_surge_blocks=0,
            state="PUBLISHED",
        )

        first_open = api_client.open_vehicle_block(
            state["block_1"]["id"], DISPATCHER_HEADERS
        )
        opened = validate_success(first_open, 200)
        assertions.assert_block_state(opened, "OPEN")
        assertions.assert_instant_equals(
            opened["opened_at"], "2026-08-03T05:00:00Z"
        )

        second_open = api_client.open_vehicle_block(
            state["block_2"]["id"], DISPATCHER_HEADERS
        )
        validate_error(second_open, ApiErrorId.ERR_FLEET_SIZE_EXCEEDED.value)
        assert second_open.status_code == 409

        refused_block = fixtures.refresh_block(state["block_2"]["id"])
        assertions.assert_block_state(refused_block, "SCHEDULED")
        assertions.assert_null_fields(refused_block, "opened_at")

        rows, meta = validate_paginated(
            api_client.list_vehicle_blocks(
                DISPATCHER_HEADERS,
                params={"zone_id": state["zone"]["id"], "state": "OPEN"},
            )
        )
        assert meta["total_count"] == 1, rows
        assertions.assert_contains_ids(rows, state["block_1"]["id"])
        assertions.assert_excludes_ids(rows, state["block_2"]["id"])

    def test_fleet_sizing_is_skipped_when_no_published_forecast_covers_the_window(
        self,
    ):
        """With the only forecast on a disjoint window, both overlapping BASE blocks open.

        PRD: "When no such published forecast exists, the check is skipped entirely and the block opens freely."

        Design: Corner/validations/fleet_size_check_is_skipped_when_no_forecast_covers_the_window
        """
        state = _two_base_blocks_and_a_forecast(
            "2026-08-03T10:00:00Z", "2026-08-03T14:00:00Z"
        )

        # The forecast exists and sizes one base block, but its window merely
        # touches [06:00, 10:00) and so does not overlap it.
        assertions.assert_fields(
            state["forecast"], required_base_blocks=1, required_surge_blocks=0
        )

        for block in (state["block_1"], state["block_2"]):
            response = api_client.open_vehicle_block(block["id"], DISPATCHER_HEADERS)
            opened = validate_success(response, 200)
            assertions.assert_block_state(opened, "OPEN")
            assertions.assert_instant_equals(
                opened["opened_at"], "2026-08-03T05:00:00Z"
            )

        rows, meta = validate_paginated(
            api_client.list_vehicle_blocks(
                DISPATCHER_HEADERS,
                params={"zone_id": state["zone"]["id"], "state": "OPEN"},
            )
        )
        assert meta["total_count"] == 2, rows
        assertions.assert_contains_ids(
            rows, state["block_1"]["id"], state["block_2"]["id"]
        )


# ─── Segregation of duties on certification ────────────────────────────────


class TestCertifierMustNotBeTheSubmitter:
    def test_certifying_ones_own_filing_is_refused(self):
        """The operator identifier that filed a report cannot certify it.

        PRD: "First, **segregation of duties**: the certifying `X-User-ID` must differ from the report's `submitted_by_user_id`, and an attempt by the filer to certify their own filing is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/certifier_must_not_be_the_submitter
        """
        state = _submitted_report_on_an_empty_zone()
        report_id = state["report"]["id"]
        assertions.assert_fields(state["report"], submitted_by_user_id="fa-1")

        refused = api_client.certify_subsidy_report(
            report_id,
            make_auditor_headers("fa-1"),
            {"note": "self-certifying my own filing"},
        )
        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        assert refused.status_code == 403

        after = fixtures.refresh_report(report_id)
        assertions.assert_report_state(after, "SUBMITTED")
        assertions.assert_null_fields(after, "certified_by_user_id")
        assertions.assert_fields(after, submitted_by_user_id="fa-1")

    def test_a_different_operator_identifier_certifies_the_same_filing(self):
        """The same request from a distinct operator identifier certifies the report.

        PRD: "One further access rule is structural rather than per-resource: the operator identifier that filed a subsidy report can never be the one that certifies it."

        Design: Corner/validations/certifier_must_not_be_the_submitter
        """
        state = _submitted_report_on_an_empty_zone()
        report_id = state["report"]["id"]

        certified = api_client.certify_subsidy_report(
            report_id,
            AUDITOR_HEADERS,
            {"note": "reviewed against the operator's ledger"},
        )
        report = validate_success(certified, 200)
        assertions.assert_report_state(report, "CERTIFIED")
        assertions.assert_fields(
            report,
            certified_by_user_id="aud-1",
            submitted_by_user_id="fa-1",
            total_trips=0,
            subsidy_per_trip_cents=0,
            total_operating_cost_cents=0,
            total_fare_revenue_cents=0,
        )
        assertions.assert_version_advanced(state["report"], report)
