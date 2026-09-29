"""Depth coverage for the temporal boundaries that guard scheduling.

Three families live here, each pinned to one recipe:

* the inclusive peak-factor threshold that decides whether a published demand
  forecast needs surge blocks at all (PRD §3.3),
* the half-open vehicle-occupation exclusion, where exact adjacency is legal
  (PRD §3.4),
* the driver rest buffer, where the very same adjacency is illegal because both
  windows are shifted thirty minutes earlier before they are compared (PRD §3.4).

Every recipe is rebuilt from scratch inside each test: the harness restarts the
server and empties the database before each one, and the logical clock is always
moved explicitly.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import vehicle_block_payload
from test_helpers.fixtures import (
    create_active_zone,
    create_block,
    create_forecast,
    refresh_block,
    refresh_forecast,
    refresh_zone,
    set_clock,
    setup_scheduling_sandbox,
)
from test_helpers.test_users import DISPATCHER_HEADERS, ZONE_ADMIN_HEADERS

# ─── Pinned literals of the three recipes ──────────────────────────────────

CLOCK_BEFORE_SERVICE = "2026-08-03T05:00:00Z"

WINDOW_START = "2026-08-03T06:00:00Z"
WINDOW_END = "2026-08-03T10:00:00Z"

# The forecast window is four hours, so one block can serve
# TRIPS_PER_BLOCK_HOUR * 4 == 16 boarded trips over it.
FORECAST_TRIPS = 40
EXPECTED_BASE_BLOCKS = 3  # ceil(40 / 16)
PEAK_FACTOR_AT_THRESHOLD = 1.50  # required_surge_blocks == 0, inclusively
PEAK_FACTOR_ONE_STEP_PAST = 1.51  # ceil(40 * 1.51) == 61 -> ceil(21 / 16) == 2
EXPECTED_SURGE_BLOCKS_PAST_THRESHOLD = 2

ADJACENT_START = "2026-08-03T10:00:00Z"
ADJACENT_END = "2026-08-03T12:00:00Z"
ONE_MINUTE_OVERLAP_START = "2026-08-03T09:59:00Z"
ONE_MINUTE_OVERLAP_END = "2026-08-03T10:00:00Z"
NESTED_START = "2026-08-03T07:00:00Z"
NESTED_END = "2026-08-03T09:00:00Z"
THIRTY_MINUTE_GAP_START = "2026-08-03T10:30:00Z"
THIRTY_MINUTE_GAP_END = "2026-08-03T12:30:00Z"
TWENTY_NINE_MINUTE_GAP_START = "2026-08-03T10:29:00Z"
TWENTY_NINE_MINUTE_GAP_END = "2026-08-03T10:30:00Z"


# ─── Recipe composers ──────────────────────────────────────────────────────


def _forecast_ready_zone():
    """Clock parked before the service window, one ACTIVE zone and no other rows.

    Returns the zone as the activation response reported it, so its `version` is
    the token the first forecast create must present.
    """
    set_clock(CLOCK_BEFORE_SERVICE, headers=ZONE_ADMIN_HEADERS)
    return create_active_zone()


def _scheduled_block_recipe():
    """An ACTIVE zone whose vehicle V1 and driver D1 hold one SCHEDULED block over
    [06:00, 10:00), with spare vehicles V2-V4 and spare drivers D2-D4.

    A probe that reuses V1 but a fresh driver can only be answered by the
    vehicle-occupation exclusion; a probe that reuses D1 but a fresh vehicle can
    only be answered by the driver rest buffer. No demand forecast exists and
    nothing is opened, so fleet sizing never participates.
    """
    state = setup_scheduling_sandbox()
    set_clock(CLOCK_BEFORE_SERVICE, headers=ZONE_ADMIN_HEADERS)
    state["block_b1"] = create_block(
        state["zone"]["id"],
        state["vehicles"]["V1"]["id"],
        state["drivers"]["D1"]["id"],
        block_type="BASE",
        start_utc=WINDOW_START,
        end_utc=WINDOW_END,
    )
    return state


def _list_blocks(params):
    rows, meta = validate_paginated(
        api_client.list_vehicle_blocks(DISPATCHER_HEADERS, params=params)
    )
    return rows, meta


# ═══ Peak-factor threshold on fleet sizing ═════════════════════════════════


class TestSurgeThresholdInclusiveAtPeakFactor150:
    def test_peak_factor_exactly_one_point_five_zero_needs_no_surge_blocks(self):
        """A forecast whose peak factor sits exactly on the threshold publishes zero surge blocks.

        PRD: "If `peak_factor` is 1.50 or lower, `required_surge_blocks` is 0 — the threshold is inclusive, so a forecast with a peak factor of exactly 1.50 requires no surge blocks at all."

        Design: Difficulty/boundary_precision_check/surge_threshold_inclusive_at_peak_factor_one_point_five_zero
        """
        zone = _forecast_ready_zone()

        forecast = create_forecast(
            zone["id"],
            zone_version=zone["version"],
            window_start_utc=WINDOW_START,
            window_end_utc=WINDOW_END,
            forecast_trips=FORECAST_TRIPS,
            peak_factor=PEAK_FACTOR_AT_THRESHOLD,
        )

        assertions.assert_fields(
            forecast,
            state="PUBLISHED",
            forecast_trips=FORECAST_TRIPS,
            required_surge_blocks=0,
            version=1,
        )
        assert forecast["peak_factor"] == pytest.approx(
            PEAK_FACTOR_AT_THRESHOLD, abs=0.01
        )
        assertions.assert_versioned_entity(forecast)

    def test_base_block_count_is_identical_on_both_sides_of_the_threshold(self):
        """Forty trips over a four-hour window need three base blocks whether the peak factor is 1.50 or 1.51.

        PRD: "`required_base_blocks` is then the expected trip count divided by that per-block capacity, rounded **up** to the next whole block."

        Design: Difficulty/boundary_precision_check/surge_threshold_inclusive_at_peak_factor_one_point_five_zero
        """
        zone = _forecast_ready_zone()

        at_threshold = create_forecast(
            zone["id"],
            zone_version=zone["version"],
            window_start_utc=WINDOW_START,
            window_end_utc=WINDOW_END,
            forecast_trips=FORECAST_TRIPS,
            peak_factor=PEAK_FACTOR_AT_THRESHOLD,
        )
        reread = refresh_zone(zone["id"], headers=DISPATCHER_HEADERS)
        one_step_past = create_forecast(
            zone["id"],
            zone_version=reread["version"],
            window_start_utc=WINDOW_START,
            window_end_utc=WINDOW_END,
            forecast_trips=FORECAST_TRIPS,
            peak_factor=PEAK_FACTOR_ONE_STEP_PAST,
        )

        assert at_threshold["required_base_blocks"] == EXPECTED_BASE_BLOCKS
        assert one_step_past["required_base_blocks"] == EXPECTED_BASE_BLOCKS

    def test_peak_factor_one_step_past_the_threshold_needs_two_surge_blocks(self):
        """A peak factor of 1.51 lifts the peak count to 61 trips and so requires two surge blocks.

        PRD: "Otherwise `required_surge_blocks` is the surge trip count divided by the same per-block trip capacity and rounded up to the next whole block, but never more than 6 surge blocks however extreme the peak."

        Design: Difficulty/boundary_precision_check/surge_threshold_inclusive_at_peak_factor_one_point_five_zero
        """
        zone = _forecast_ready_zone()

        create_forecast(
            zone["id"],
            zone_version=zone["version"],
            window_start_utc=WINDOW_START,
            window_end_utc=WINDOW_END,
            forecast_trips=FORECAST_TRIPS,
            peak_factor=PEAK_FACTOR_AT_THRESHOLD,
        )
        reread = refresh_zone(zone["id"], headers=DISPATCHER_HEADERS)
        one_step_past = create_forecast(
            zone["id"],
            zone_version=reread["version"],
            window_start_utc=WINDOW_START,
            window_end_utc=WINDOW_END,
            forecast_trips=FORECAST_TRIPS,
            peak_factor=PEAK_FACTOR_ONE_STEP_PAST,
        )

        assertions.assert_fields(
            one_step_past,
            state="PUBLISHED",
            required_base_blocks=EXPECTED_BASE_BLOCKS,
            required_surge_blocks=EXPECTED_SURGE_BLOCKS_PAST_THRESHOLD,
            version=1,
        )

    def test_second_publication_supersedes_the_overlapping_first_one(self):
        """Republishing over the same window retires the earlier forecast and leaves exactly one PUBLISHED row.

        PRD: "A newly published forecast lands in `PUBLISHED` with `version` 1, and every existing forecast for the *same* zone that is currently `PUBLISHED` and whose window overlaps the incoming window moves to `SUPERSEDED`, with that forecast's own `version` advancing by 1."

        Design: Difficulty/boundary_precision_check/surge_threshold_inclusive_at_peak_factor_one_point_five_zero
        """
        zone = _forecast_ready_zone()

        first = create_forecast(
            zone["id"],
            zone_version=zone["version"],
            window_start_utc=WINDOW_START,
            window_end_utc=WINDOW_END,
            forecast_trips=FORECAST_TRIPS,
            peak_factor=PEAK_FACTOR_AT_THRESHOLD,
        )
        reread = refresh_zone(zone["id"], headers=DISPATCHER_HEADERS)
        second = create_forecast(
            zone["id"],
            zone_version=reread["version"],
            window_start_utc=WINDOW_START,
            window_end_utc=WINDOW_END,
            forecast_trips=FORECAST_TRIPS,
            peak_factor=PEAK_FACTOR_ONE_STEP_PAST,
        )

        settled_first = refresh_forecast(first["id"])
        settled_second = refresh_forecast(second["id"])
        assertions.assert_fields(settled_first, state="SUPERSEDED", version=2)
        assertions.assert_fields(settled_second, state="PUBLISHED", version=1)

        published, meta = validate_paginated(
            api_client.list_demand_forecasts(
                ZONE_ADMIN_HEADERS,
                params={"zone_id": zone["id"], "state": "PUBLISHED"},
            )
        )
        assert meta["total_count"] == 1
        assertions.assert_row_count(published, 1)
        assert published[0]["id"] == second["id"]

    def test_publication_advances_the_parent_zone_version(self):
        """Publishing a forecast bumps the zone row, which is why the second create needs a re-read token.

        PRD: "As a final effect of publication, the parent zone's `version` advances by 1, which is why a planner publishing two forecasts back to back must re-read the zone between them."

        Design: Difficulty/boundary_precision_check/surge_threshold_inclusive_at_peak_factor_one_point_five_zero
        """
        zone = _forecast_ready_zone()

        create_forecast(
            zone["id"],
            zone_version=zone["version"],
            window_start_utc=WINDOW_START,
            window_end_utc=WINDOW_END,
            forecast_trips=FORECAST_TRIPS,
            peak_factor=PEAK_FACTOR_AT_THRESHOLD,
        )

        reread = refresh_zone(zone["id"], headers=DISPATCHER_HEADERS)
        assert reread["version"] > zone["version"]
        assertions.assert_version_advanced(zone, reread)


# ═══ Vehicle occupation: half-open, no buffer ══════════════════════════════


class TestVehicleHalfOpenAdjacency:
    def test_block_starting_exactly_when_the_previous_one_ends_is_accepted(self):
        """The same vehicle may run [10:00, 12:00) directly after [06:00, 10:00) with no turnaround.

        PRD: "Exact adjacency is therefore allowed — a block ending at the same instant another begins is fine, because a vehicle needs no turnaround it does not have."

        Design: Difficulty/resource_temporal_overlap/vehicle_half_open_adjacency_allowed_one_minute_overlap_rejected
        """
        state = _scheduled_block_recipe()

        response = api_client.create_vehicle_block(
            vehicle_block_payload(
                state["zone"]["id"],
                state["vehicles"]["V1"]["id"],
                state["drivers"]["D2"]["id"],
                block_type="BASE",
                start_utc=ADJACENT_START,
                end_utc=ADJACENT_END,
            ),
            DISPATCHER_HEADERS,
        )
        adjacent = validate_success(response, 201)

        assertions.assert_block_state(adjacent, "SCHEDULED")
        assertions.assert_instant_equals(adjacent["start_utc"], ADJACENT_START)
        assertions.assert_instant_equals(adjacent["end_utc"], ADJACENT_END)
        assert adjacent["scheduled_revenue_hours"] == pytest.approx(2.00, abs=0.01)
        assertions.assert_block_commitments(
            adjacent,
            seats_committed=0,
            wav_positions_committed=0,
            committed_index_min=None,
            committed_index_max=None,
        )

    def test_one_minute_overlap_on_the_same_vehicle_is_rejected(self):
        """A window ending exactly at the incumbent's end still overlaps it by one minute and is refused.

        PRD: "**Vehicle occupation** treats the window as half-open: a create is rejected when some existing block naming the same `vehicle_id` and sitting in state `SCHEDULED` or `OPEN` has a start strictly earlier than the new block's end and a start on the new block that is strictly earlier than that existing block's end."

        Design: Difficulty/resource_temporal_overlap/vehicle_half_open_adjacency_allowed_one_minute_overlap_rejected
        """
        state = _scheduled_block_recipe()

        response = api_client.create_vehicle_block(
            vehicle_block_payload(
                state["zone"]["id"],
                state["vehicles"]["V1"]["id"],
                state["drivers"]["D3"]["id"],
                block_type="BASE",
                start_utc=ONE_MINUTE_OVERLAP_START,
                end_utc=ONE_MINUTE_OVERLAP_END,
            ),
            DISPATCHER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_VEHICLE_BLOCK_OVERLAP.value)

        untouched = refresh_block(state["block_b1"]["id"])
        assertions.assert_block_state(untouched, "SCHEDULED")
        assertions.assert_version_unchanged(state["block_b1"], untouched)

    def test_window_nested_inside_a_cancelled_block_is_accepted(self):
        """Once the incumbent is CANCELLED it no longer occupies the vehicle, so a nested window is legal.

        PRD: "`SCHEDULED → CANCELLED` is trivial: a scheduled block can hold no assignments, so nothing is released, `state` becomes `CANCELLED` and `version` advances by 1."

        Design: Difficulty/resource_temporal_overlap/vehicle_half_open_adjacency_allowed_one_minute_overlap_rejected
        """
        state = _scheduled_block_recipe()

        cancelled = validate_success(
            api_client.cancel_vehicle_block(
                state["block_b1"]["id"],
                DISPATCHER_HEADERS,
                {"note": "reassigning the morning run"},
            ),
            200,
        )
        assertions.assert_block_state(cancelled, "CANCELLED")
        assertions.assert_version_advanced(state["block_b1"], cancelled)

        nested = validate_success(
            api_client.create_vehicle_block(
                vehicle_block_payload(
                    state["zone"]["id"],
                    state["vehicles"]["V1"]["id"],
                    state["drivers"]["D4"]["id"],
                    block_type="BASE",
                    start_utc=NESTED_START,
                    end_utc=NESTED_END,
                ),
                DISPATCHER_HEADERS,
            ),
            201,
        )
        assertions.assert_block_state(nested, "SCHEDULED")
        assert nested["scheduled_revenue_hours"] == pytest.approx(2.00, abs=0.01)

    def test_listing_shows_only_the_three_persisted_blocks_for_the_vehicle(self):
        """The refused candidate was never written, so the vehicle carries three rows of which two are SCHEDULED.

        PRD: "The `meta` object of a list response carries `limit` (the effective page size), `offset` (the effective starting position), `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page)."

        Design: Difficulty/resource_temporal_overlap/vehicle_half_open_adjacency_allowed_one_minute_overlap_rejected
        """
        state = _scheduled_block_recipe()
        zone_id = state["zone"]["id"]
        vehicle_id = state["vehicles"]["V1"]["id"]

        adjacent = validate_success(
            api_client.create_vehicle_block(
                vehicle_block_payload(
                    zone_id,
                    vehicle_id,
                    state["drivers"]["D2"]["id"],
                    block_type="BASE",
                    start_utc=ADJACENT_START,
                    end_utc=ADJACENT_END,
                ),
                DISPATCHER_HEADERS,
            ),
            201,
        )
        validate_error(
            api_client.create_vehicle_block(
                vehicle_block_payload(
                    zone_id,
                    vehicle_id,
                    state["drivers"]["D3"]["id"],
                    block_type="BASE",
                    start_utc=ONE_MINUTE_OVERLAP_START,
                    end_utc=ONE_MINUTE_OVERLAP_END,
                ),
                DISPATCHER_HEADERS,
            ),
            ApiErrorId.ERR_VEHICLE_BLOCK_OVERLAP.value,
        )
        validate_success(
            api_client.cancel_vehicle_block(
                state["block_b1"]["id"],
                DISPATCHER_HEADERS,
                {"note": "reassigning the morning run"},
            ),
            200,
        )
        nested = validate_success(
            api_client.create_vehicle_block(
                vehicle_block_payload(
                    zone_id,
                    vehicle_id,
                    state["drivers"]["D4"]["id"],
                    block_type="BASE",
                    start_utc=NESTED_START,
                    end_utc=NESTED_END,
                ),
                DISPATCHER_HEADERS,
            ),
            201,
        )

        all_rows, all_meta = _list_blocks({"vehicle_id": vehicle_id})
        assert all_meta["total_count"] == 3
        assertions.assert_contains_ids(
            all_rows, state["block_b1"]["id"], adjacent["id"], nested["id"]
        )

        scheduled_rows, scheduled_meta = _list_blocks(
            {"vehicle_id": vehicle_id, "state": "SCHEDULED"}
        )
        assert scheduled_meta["total_count"] == 2
        assertions.assert_contains_ids(scheduled_rows, adjacent["id"], nested["id"])
        assertions.assert_excludes_ids(scheduled_rows, state["block_b1"]["id"])

        _, refused_meta = _list_blocks({"driver_id": state["drivers"]["D3"]["id"]})
        assert refused_meta["total_count"] == 0


# ═══ Driver rest buffer: shifted windows, closed comparison ════════════════


class TestDriverRestBufferBoundaries:
    def test_adjacent_shift_on_the_same_driver_is_rejected(self):
        """A driver may not start [10:00, 12:00) the instant their [06:00, 10:00) shift ends.

        PRD: "Under this arithmetic exact adjacency is rejected, and a gap of exactly thirty minutes between the two windows is allowed."

        Design: Difficulty/resource_temporal_overlap/driver_rest_buffer_rejects_adjacency_and_allows_exactly_thirty_minutes
        """
        state = _scheduled_block_recipe()

        response = api_client.create_vehicle_block(
            vehicle_block_payload(
                state["zone"]["id"],
                state["vehicles"]["V2"]["id"],
                state["drivers"]["D1"]["id"],
                block_type="BASE",
                start_utc=ADJACENT_START,
                end_utc=ADJACENT_END,
            ),
            DISPATCHER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_DRIVER_REST_BUFFER.value)

        untouched = refresh_block(state["block_b1"]["id"])
        assertions.assert_block_state(untouched, "SCHEDULED")
        assertions.assert_version_unchanged(state["block_b1"], untouched)

        _, meta = _list_blocks({"vehicle_id": state["vehicles"]["V2"]["id"]})
        assert meta["total_count"] == 0

    def test_gap_of_exactly_thirty_minutes_is_accepted(self):
        """A second shift starting thirty minutes after the first ends clears the rest buffer.

        PRD: "Under this arithmetic exact adjacency is rejected, and a gap of exactly thirty minutes between the two windows is allowed."

        Design: Difficulty/resource_temporal_overlap/driver_rest_buffer_rejects_adjacency_and_allows_exactly_thirty_minutes
        """
        state = _scheduled_block_recipe()

        rested = validate_success(
            api_client.create_vehicle_block(
                vehicle_block_payload(
                    state["zone"]["id"],
                    state["vehicles"]["V3"]["id"],
                    state["drivers"]["D1"]["id"],
                    block_type="SURGE",
                    start_utc=THIRTY_MINUTE_GAP_START,
                    end_utc=THIRTY_MINUTE_GAP_END,
                ),
                DISPATCHER_HEADERS,
            ),
            201,
        )

        assertions.assert_block_state(rested, "SCHEDULED")
        assertions.assert_fields(rested, block_type="SURGE", version=1)
        assertions.assert_instant_equals(rested["start_utc"], THIRTY_MINUTE_GAP_START)
        assertions.assert_instant_equals(rested["end_utc"], THIRTY_MINUTE_GAP_END)
        assert rested["scheduled_revenue_hours"] == pytest.approx(2.00, abs=0.01)

    def test_gap_of_twenty_nine_minutes_is_rejected(self):
        """One minute short of the buffer still leaves both shifted windows overlapping.

        PRD: "A create is rejected when some existing block naming the same `driver_id` and sitting in state `SCHEDULED` or `OPEN` satisfies both of these: that existing block's start, moved thirty minutes earlier, is strictly before the new block's end, and the new block's start, moved thirty minutes earlier, is strictly before the existing block's end."

        Design: Difficulty/resource_temporal_overlap/driver_rest_buffer_rejects_adjacency_and_allows_exactly_thirty_minutes
        """
        state = _scheduled_block_recipe()

        response = api_client.create_vehicle_block(
            vehicle_block_payload(
                state["zone"]["id"],
                state["vehicles"]["V4"]["id"],
                state["drivers"]["D1"]["id"],
                block_type="BASE",
                start_utc=TWENTY_NINE_MINUTE_GAP_START,
                end_utc=TWENTY_NINE_MINUTE_GAP_END,
            ),
            DISPATCHER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_DRIVER_REST_BUFFER.value)

        _, meta = _list_blocks({"vehicle_id": state["vehicles"]["V4"]["id"]})
        assert meta["total_count"] == 0

    def test_listing_shows_only_the_two_blocks_the_buffer_allowed(self):
        """Across all three probes the driver keeps exactly two rows: the incumbent and the rested shift.

        PRD: "The `meta` object of a list response carries `limit` (the effective page size), `offset` (the effective starting position), `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page)."

        Design: Difficulty/resource_temporal_overlap/driver_rest_buffer_rejects_adjacency_and_allows_exactly_thirty_minutes
        """
        state = _scheduled_block_recipe()
        zone_id = state["zone"]["id"]
        driver_id = state["drivers"]["D1"]["id"]

        validate_error(
            api_client.create_vehicle_block(
                vehicle_block_payload(
                    zone_id,
                    state["vehicles"]["V2"]["id"],
                    driver_id,
                    block_type="BASE",
                    start_utc=ADJACENT_START,
                    end_utc=ADJACENT_END,
                ),
                DISPATCHER_HEADERS,
            ),
            ApiErrorId.ERR_DRIVER_REST_BUFFER.value,
        )
        rested = validate_success(
            api_client.create_vehicle_block(
                vehicle_block_payload(
                    zone_id,
                    state["vehicles"]["V3"]["id"],
                    driver_id,
                    block_type="SURGE",
                    start_utc=THIRTY_MINUTE_GAP_START,
                    end_utc=THIRTY_MINUTE_GAP_END,
                ),
                DISPATCHER_HEADERS,
            ),
            201,
        )
        validate_error(
            api_client.create_vehicle_block(
                vehicle_block_payload(
                    zone_id,
                    state["vehicles"]["V4"]["id"],
                    driver_id,
                    block_type="BASE",
                    start_utc=TWENTY_NINE_MINUTE_GAP_START,
                    end_utc=TWENTY_NINE_MINUTE_GAP_END,
                ),
                DISPATCHER_HEADERS,
            ),
            ApiErrorId.ERR_DRIVER_REST_BUFFER.value,
        )

        rows, meta = _list_blocks({"driver_id": driver_id})
        assert meta["total_count"] == 2
        assertions.assert_contains_ids(rows, state["block_b1"]["id"], rested["id"])

        _, v2_meta = _list_blocks({"vehicle_id": state["vehicles"]["V2"]["id"]})
        assert v2_meta["total_count"] == 0
        _, v4_meta = _list_blocks({"vehicle_id": state["vehicles"]["V4"]["id"]})
        assert v4_meta["total_count"] == 0

        untouched = refresh_block(state["block_b1"]["id"])
        assertions.assert_block_state(untouched, "SCHEDULED")
