"""Regulatory limits, temporal containment and referential guards.

Each rule here has two or more independent triggers behind a single error code,
or a bound whose inclusive edge decides between 201 and 422. The probes drive
every branch separately and then prove the accepted value at the boundary.
"""
import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    approve_claim_payload,
    clearing_result_payload,
    create_capacity_obligation_payload,
    create_capacity_test_payload,
    create_dispatch_instruction_payload,
    create_market_bid_payload,
    create_telemetry_sample_payload,
)
from test_helpers.fixtures import (
    ASSET_MANAGER,
    CLAIM_ADJUDICATOR,
    CLAIM_FILER,
    DISPATCH_DAY_CLOCK,
    MARKET_OPERATOR,
    TRADER,
    append_sample,
    cleared_bid,
    draft_bid,
    executing_dispatch,
    file_claim,
    finish_test,
    hold_reservation,
    lightly_cycled_plant,
    provision_asset,
    refresh_asset,
    refresh_bid,
    refresh_claim,
    refresh_dispatch,
    refresh_test,
    schedule_test,
    set_clock,
    start_test,
    submit_bid,
    submit_claim,
)
from test_helpers.test_users import make_site_controller_headers

WINDOW_START = "2026-08-10T12:00:00Z"
WINDOW_END = "2026-08-10T20:00:00Z"
DELIVERY_START = "2026-08-10T12:00:00Z"
DELIVERY_END = "2026-08-10T16:00:00Z"


def _cleared_position(cleared_mw=10.0, offer_mw=10.0, cleared_price_usd_per_mwh=45.00):
    """One plant with a cleared offer over the 12:00-16:00 delivery interval."""
    set_clock(DISPATCH_DAY_CLOCK)
    asset = provision_asset()
    reservation = hold_reservation(
        asset["id"],
        reserved_mwh=40.0,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    bid = cleared_bid(
        asset["id"],
        reservation["id"],
        cleared_price_usd_per_mwh=cleared_price_usd_per_mwh,
        cleared_mw=cleared_mw,
        offer_mw=offer_mw,
        delivery_start=DELIVERY_START,
        delivery_end=DELIVERY_END,
    )
    return asset, bid


def _executing_instruction(instructed_mw=10.0):
    """A 10 MW instruction executing over the 12:00-14:00 setpoint window."""
    asset, bid = _cleared_position(cleared_mw=instructed_mw, offer_mw=instructed_mw)
    dispatch = executing_dispatch(
        bid["id"],
        asset["id"],
        instructed_mw=instructed_mw,
        setpoint_start="2026-08-10T12:00:00Z",
        setpoint_end="2026-08-10T14:00:00Z",
    )
    return asset, dispatch


def _sample_response(asset_id, dispatch_id, index, sampled_at, mw, mvar):
    return api_client.create_telemetry_sample(
        create_telemetry_sample_payload(
            dispatch_id,
            index,
            sampled_at,
            measured_mw=mw,
            measured_mvar=mvar,
            soc_mwh_reading=70.0,
            max_cell_temp_c=40.0,
        ),
        make_site_controller_headers(asset_id),
    )


class TestInterconnectionLimitsHaveThreeSeparateBranches:
    """Two triggers share the POI code; the reactive code sits one rule lower."""

    def test_active_power_above_the_mw_limit_is_refused(self):
        """The raw MW comparison is the first of the two POI triggers.

        PRD: "`measured_mw` must be at most the asset's `poi_mw_limit` and `apparent_mva` must be at most its `poi_mva_limit`; both bounds are inclusive, so a measurement exactly at a limit is compliant and only a strictly greater one is refused, with `ERR_POI_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Corner/errors/interconnection_limit_probes_separate_poi_and_reactive_codes
        """
        asset, dispatch = _executing_instruction()

        validate_error(
            _sample_response(asset["id"], dispatch["id"], 1, "2026-08-10T13:00:00Z", 25.01, 0.0),
            "ERR_POI_LIMIT_EXCEEDED",
            expected_status=422,
        )
        assert refresh_dispatch(dispatch["id"])["telemetry_sample_count"] == 0

    def test_apparent_power_above_the_mva_limit_is_refused(self):
        """A legal MW value can still breach the apparent-power limit.

        PRD: "`apparent_mva` is the square root of the sum of the squares of `measured_mw` and `measured_mvar`, rounded half up to 3 decimal places."

        Design: Corner/errors/interconnection_limit_probes_separate_poi_and_reactive_codes
        """
        asset, dispatch = _executing_instruction()

        validate_error(
            _sample_response(asset["id"], dispatch["id"], 1, "2026-08-10T13:00:00Z", 25.0, 12.0),
            "ERR_POI_LIMIT_EXCEEDED",
            expected_status=422,
        )

    def test_reactive_magnitude_above_capability_reports_the_reactive_code(self):
        """With both POI comparisons passed, only the reactive rule can fire.

        PRD: "The magnitude of `measured_mvar`, ignoring its sign, must be at most the asset's `reactive_capability_mvar`, or the sample is refused with `ERR_REACTIVE_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Corner/errors/interconnection_limit_probes_separate_poi_and_reactive_codes
        """
        asset, dispatch = _executing_instruction()

        validate_error(
            _sample_response(asset["id"], dispatch["id"], 1, "2026-08-10T13:00:00Z", 10.0, 12.01),
            "ERR_REACTIVE_LIMIT_EXCEEDED",
            expected_status=422,
        )

    def test_a_measurement_exactly_at_the_mw_limit_is_stored(self):
        """The comparisons are inclusive, so the limit value itself is compliant.

        PRD: "The active-power and apparent-power check runs before the reactive-capability check, so a sample that breaches both reports the interconnection limit."

        Design: Corner/errors/interconnection_limit_probes_separate_poi_and_reactive_codes
        """
        asset, dispatch = _executing_instruction()

        sample = validate_success(
                _sample_response(
                    asset["id"], dispatch["id"], 1, "2026-08-10T13:00:00Z", 25.0, 0.0
                ),
                expected_status=201,
            )

        assert sample["apparent_mva"] == pytest.approx(25.0, abs=0.01)

    def test_a_signed_reactive_reading_at_the_limit_is_stored(self):
        """An absorbing plant reports a negative MVAr, policed on magnitude alone.

        PRD: "`measured_mvar` is measured reactive power at that point and is *signed*: a negative value, meaning the plant is absorbing reactive power, is a well-formed request, and its magnitude is policed by the reactive-capability rule below rather than by the body shape check."

        Design: Corner/errors/interconnection_limit_probes_separate_poi_and_reactive_codes
        """
        asset, dispatch = _executing_instruction()
        for mw, mvar, code in (
            (25.01, 0.0, "ERR_POI_LIMIT_EXCEEDED"),
            (25.0, 12.0, "ERR_POI_LIMIT_EXCEEDED"),
            (10.0, 12.01, "ERR_REACTIVE_LIMIT_EXCEEDED"),
        ):
            validate_error(
                _sample_response(
                    asset["id"], dispatch["id"], 1, "2026-08-10T13:00:00Z", mw, mvar
                ),
                code,
            )
        get_success_data(
            _sample_response(asset["id"], dispatch["id"], 1, "2026-08-10T13:00:00Z", 25.0, 0.0)
        )

        absorbing = validate_success(
                _sample_response(
                    asset["id"], dispatch["id"], 2, "2026-08-10T13:30:00Z", 10.0, -12.0
                ),
                expected_status=201,
            )

        assert absorbing["apparent_mva"] == pytest.approx(15.62, abs=0.01)
        assert refresh_dispatch(dispatch["id"])["telemetry_sample_count"] == 2


class TestTelemetryMustArriveInOrder:
    """Strictly later than the newest sample, and never before the setpoint opens."""

    def _streaming(self):
        asset, dispatch = _executing_instruction()
        first = append_sample(
            dispatch["id"],
            asset["id"],
            1,
            "2026-08-10T13:00:00Z",
            measured_mw=10.0,
            measured_mvar=4.0,
            soc_mwh_reading=74.0,
            max_cell_temp_c=40.0,
        )
        return asset, dispatch, first

    def test_the_first_sample_of_the_stream_is_stored(self):
        """The stream opens with index 1, which the later probes are measured against.

        PRD: "`sample_index` is a 1-based monotonic index inside the instruction: it must be at least 1 and strictly greater than the current maximum index for that instruction."

        Design: Corner/errors/telemetry_regression_and_pre_window_samples_are_rejected
        """
        _, _, first = self._streaming()

        assert first["sample_index"] == 1

    def test_a_sample_earlier_than_the_newest_instant_is_refused(self):
        """Telemetry may not walk backwards in time.

        PRD: "A sample's `sampled_at` must be strictly later than the `sampled_at` of the newest existing sample of the same instruction, and must not be earlier than the instruction's `setpoint_start`; either violation is refused with `ERR_TELEMETRY_OUT_OF_ORDER` (HTTP 409)."

        Design: Corner/errors/telemetry_regression_and_pre_window_samples_are_rejected
        """
        asset, dispatch, _ = self._streaming()

        validate_error(
            _sample_response(asset["id"], dispatch["id"], 2, "2026-08-10T12:30:00Z", 10.0, 4.0),
            "ERR_TELEMETRY_OUT_OF_ORDER",
            expected_status=409,
        )
        assert refresh_dispatch(dispatch["id"])["telemetry_sample_count"] == 1

    def test_a_sample_at_exactly_the_newest_instant_is_refused(self):
        """Strictly later means an exact repeat of the newest timestamp is refused.

        PRD: "A sample's `sampled_at` must be strictly later than the `sampled_at` of the newest existing sample of the same instruction, and must not be earlier than the instruction's `setpoint_start`; either violation is refused with `ERR_TELEMETRY_OUT_OF_ORDER` (HTTP 409)."

        Design: Corner/errors/telemetry_regression_and_pre_window_samples_are_rejected
        """
        asset, dispatch, _ = self._streaming()

        validate_error(
            _sample_response(asset["id"], dispatch["id"], 2, "2026-08-10T13:00:00Z", 10.0, 4.0),
            "ERR_TELEMETRY_OUT_OF_ORDER",
            expected_status=409,
        )

    def test_a_sample_before_the_setpoint_opens_is_refused(self):
        """The second half of the rule bites even though 11:30 precedes every stored instant.

        PRD: "A sample's `sampled_at` must be strictly later than the `sampled_at` of the newest existing sample of the same instruction, and must not be earlier than the instruction's `setpoint_start`; either violation is refused with `ERR_TELEMETRY_OUT_OF_ORDER` (HTTP 409)."

        Design: Corner/errors/telemetry_regression_and_pre_window_samples_are_rejected
        """
        asset, dispatch, _ = self._streaming()

        validate_error(
            _sample_response(asset["id"], dispatch["id"], 2, "2026-08-10T11:30:00Z", 10.0, 4.0),
            "ERR_TELEMETRY_OUT_OF_ORDER",
            expected_status=409,
        )

    def test_a_sample_after_the_setpoint_closes_is_late_not_out_of_order(self):
        """Late-arriving telemetry is stored and counted; only regression is refused.

        PRD: "A sample whose `sampled_at` is later than the instruction's `setpoint_end` is accepted, but it is *late-arriving*, and §3.6 explains what that costs."

        Design: Corner/errors/telemetry_regression_and_pre_window_samples_are_rejected
        """
        asset, dispatch, _ = self._streaming()
        for index, instant in ((2, "2026-08-10T12:30:00Z"), (2, "2026-08-10T13:00:00Z"), (2, "2026-08-10T11:30:00Z")):
            validate_error(
                _sample_response(asset["id"], dispatch["id"], index, instant, 10.0, 4.0),
                "ERR_TELEMETRY_OUT_OF_ORDER",
            )

        second = validate_success(
                _sample_response(
                    asset["id"], dispatch["id"], 2, "2026-08-10T13:30:00Z", 10.0, 4.0
                ),
                expected_status=201,
            )
        third = validate_success(
                _sample_response(
                    asset["id"], dispatch["id"], 3, "2026-08-10T14:30:00Z", 10.0, 4.0
                ),
                expected_status=201,
            )

        assert second["sample_index"] == 2
        assert third["sample_index"] == 3
        assert refresh_dispatch(dispatch["id"])["telemetry_sample_count"] == 3


class TestSetpointMustSitInsideTheDeliveryWindow:
    """Containment at both ends, not overlap, is what the rule asks for."""

    def _instruction_response(self, asset_id, bid_id, setpoint_start, setpoint_end):
        return api_client.create_dispatch_instruction(
            create_dispatch_instruction_payload(
                bid_id,
                asset_id,
                instructed_mw=10.0,
                setpoint_start=setpoint_start,
                setpoint_end=setpoint_end,
            ),
            MARKET_OPERATOR,
        )

    def test_a_setpoint_running_past_delivery_end_is_refused(self):
        """An interval that straddles the closing boundary is refused.

        PRD: "A setpoint window that escapes either is refused with `ERR_RESERVATION_WINDOW_MISMATCH` (HTTP 422)."

        Design: Corner/errors/setpoint_outside_the_delivery_window_returns_window_mismatch
        """
        asset, bid = _cleared_position()

        validate_error(
            self._instruction_response(
                asset["id"], bid["id"], "2026-08-10T15:00:00Z", "2026-08-10T17:00:00Z"
            ),
            "ERR_RESERVATION_WINDOW_MISMATCH",
            expected_status=422,
        )

    def test_a_setpoint_starting_before_delivery_start_is_refused(self):
        """The opening boundary is policed just as strictly as the closing one.

        PRD: "It must fall within the offer's closed delivery interval, and it must fall within the backing reservation's window, meaning the reservation's `window_start` is at or before `setpoint_start` and `setpoint_end` is at or before the reservation's `window_end`."

        Design: Corner/errors/setpoint_outside_the_delivery_window_returns_window_mismatch
        """
        asset, bid = _cleared_position()

        validate_error(
            self._instruction_response(
                asset["id"], bid["id"], "2026-08-10T11:00:00Z", "2026-08-10T13:00:00Z"
            ),
            "ERR_RESERVATION_WINDOW_MISMATCH",
            expected_status=422,
        )

    def test_a_fully_contained_setpoint_is_accepted(self):
        """Inside both intervals, the instruction is created and priced by duration.

        PRD: "The instruction's own energy footprint is `expected_energy_mwh`: `instructed_mw` multiplied by the setpoint interval's duration in hours, rounded half up to 3 decimal places."

        Design: Corner/errors/setpoint_outside_the_delivery_window_returns_window_mismatch
        """
        asset, bid = _cleared_position()

        dispatch = validate_success(
                self._instruction_response(
                    asset["id"], bid["id"], "2026-08-10T12:00:00Z", "2026-08-10T14:00:00Z"
                ),
                expected_status=201,
            )

        assert dispatch["expected_energy_mwh"] == pytest.approx(20.0, abs=0.01)

    def test_only_the_contained_instruction_exists(self):
        """Neither rejection left a row behind on the offer's instruction list.

        PRD: "Checks run in a fixed order, and the first failing check decides the response; no later check runs, and no partial write survives a rejection."

        Design: Corner/errors/setpoint_outside_the_delivery_window_returns_window_mismatch
        """
        asset, bid = _cleared_position()
        validate_error(
            self._instruction_response(
                asset["id"], bid["id"], "2026-08-10T15:00:00Z", "2026-08-10T17:00:00Z"
            ),
            "ERR_RESERVATION_WINDOW_MISMATCH",
        )
        validate_error(
            self._instruction_response(
                asset["id"], bid["id"], "2026-08-10T11:00:00Z", "2026-08-10T13:00:00Z"
            ),
            "ERR_RESERVATION_WINDOW_MISMATCH",
        )
        kept = get_success_data(
            self._instruction_response(
                asset["id"], bid["id"], "2026-08-10T12:00:00Z", "2026-08-10T14:00:00Z"
            )
        )

        data, meta = validate_paginated(
            api_client.list_dispatch_instructions(
                MARKET_OPERATOR, params={"bid_id": bid["id"]}
            )
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [kept["id"]]


class TestInstructionIsBoundedByTheAward:
    """`cleared_mw` is the bound — not `offer_mw`, and not the plant's rating."""

    def _partially_cleared(self):
        return _cleared_position(cleared_mw=6.0, offer_mw=10.0)

    def test_the_award_is_smaller_than_the_offer(self):
        """A partial award is what separates the three candidate bounds.

        PRD: "The supplied `cleared_mw` must be greater than 0 and at most `offer_mw`; an award larger than the offer is a malformed body rejected with `ERR_INVALID_REQUEST` at the shape check of §2.6 step 3, not a business rejection."

        Design: Corner/errors/instruction_one_hundredth_above_cleared_mw_is_rejected
        """
        _, bid = self._partially_cleared()

        assert bid["status"] == "CLEARED"
        assert bid["offer_mw"] == pytest.approx(10.0, abs=0.01)
        assert bid["cleared_mw"] == pytest.approx(6.0, abs=0.01)

    def test_one_hundredth_of_a_megawatt_above_the_award_is_refused(self):
        """The 10.0 MW offer and the 25.0 MW rating are irrelevant bounds here.

        PRD: "`instructed_mw` must be greater than 0 and must not exceed the offer's `cleared_mw`; instructing more power than the market actually cleared is refused with `ERR_INSTRUCTION_EXCEEDS_CLEARED` (HTTP 422)."

        Design: Corner/errors/instruction_one_hundredth_above_cleared_mw_is_rejected
        """
        asset, bid = self._partially_cleared()

        validate_error(
            api_client.create_dispatch_instruction(
                create_dispatch_instruction_payload(
                    bid["id"],
                    asset["id"],
                    instructed_mw=6.01,
                    setpoint_start="2026-08-10T12:00:00Z",
                    setpoint_end="2026-08-10T14:00:00Z",
                ),
                MARKET_OPERATOR,
            ),
            "ERR_INSTRUCTION_EXCEEDS_CLEARED",
            expected_status=422,
        )

    def test_an_instruction_exactly_at_the_award_is_accepted(self):
        """The bound is inclusive, so the full award may be instructed.

        PRD: "The instruction's own energy footprint is `expected_energy_mwh`: `instructed_mw` multiplied by the setpoint interval's duration in hours, rounded half up to 3 decimal places."

        Design: Corner/errors/instruction_one_hundredth_above_cleared_mw_is_rejected
        """
        asset, bid = self._partially_cleared()

        dispatch = validate_success(
                api_client.create_dispatch_instruction(
                    create_dispatch_instruction_payload(
                        bid["id"],
                        asset["id"],
                        instructed_mw=6.0,
                        setpoint_start="2026-08-10T12:00:00Z",
                        setpoint_end="2026-08-10T14:00:00Z",
                    ),
                    MARKET_OPERATOR,
                ),
                expected_status=201,
            )

        assert dispatch["instructed_mw"] == pytest.approx(6.0, abs=0.01)
        assert dispatch["expected_energy_mwh"] == pytest.approx(12.0, abs=0.01)


class TestAwardBelowTheOfferFloorIsRefused:
    """The floor is the offer's own computed price, so the code proves the model."""

    def _submitted_offer(self):
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        reservation = hold_reservation(
            asset["id"],
            reserved_mwh=40.0,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        )
        bid = draft_bid(
            asset["id"],
            reservation["id"],
            offer_mw=10.0,
            delivery_start=DELIVERY_START,
            delivery_end=DELIVERY_END,
        )
        return asset, submit_bid(bid["id"])

    def test_the_degradation_aware_floor_is_thirty_seven_dollars(self):
        """Grossed-up charge energy plus unweighted degradation, with no warranty adder.

        PRD: "The first term is the cost of the energy the plant must buy to have something to sell. Charge energy is priced at 22.00 dollars per megawatt-hour at the meter, and because a round trip loses energy, that price is grossed up: the charge-cost term is 22.00 multiplied by 100 and divided by the asset's `round_trip_efficiency_pct`."

        Design: Corner/errors/award_one_cent_below_the_offer_floor_is_refused
        """
        _, bid = self._submitted_offer()

        assert bid["status"] == "SUBMITTED"
        assert bid["offer_price_usd_per_mwh"] == pytest.approx(37.00, abs=0.01)

    def test_an_award_one_cent_below_the_floor_is_refused(self):
        """Selling wear below cost is refused and the offer stays in the market.

        PRD: "The supplied `cleared_price_usd_per_mwh` must be at least the offer's `offer_price_usd_per_mwh`: the offer price *is* the floor, so an award at exactly the offer price is accepted and one a cent below it is refused with `ERR_CLEARING_PRICE_BELOW_FLOOR` (HTTP 422)."

        Design: Corner/errors/award_one_cent_below_the_offer_floor_is_refused
        """
        _, bid = self._submitted_offer()

        validate_error(
            api_client.post_clearing_result(
                bid["id"],
                clearing_result_payload(
                    "CLEARED", cleared_price_usd_per_mwh=36.99, cleared_mw=10.0
                ),
                MARKET_OPERATOR,
            ),
            "ERR_CLEARING_PRICE_BELOW_FLOOR",
            expected_status=422,
        )

        after = refresh_bid(bid["id"])
        assert after["status"] == "SUBMITTED"
        assert after["cleared_price_usd_per_mwh"] is None

    def test_an_award_exactly_at_the_floor_clears(self):
        """The comparison is inclusive, so an award at the floor is economic.

        PRD: "The `CLEARED` branch requires both `cleared_price_usd_per_mwh` and `cleared_mw` in the body and produces `SUBMITTED → CLEARED`."

        Design: Corner/errors/award_one_cent_below_the_offer_floor_is_refused
        """
        _, bid = self._submitted_offer()
        validate_error(
            api_client.post_clearing_result(
                bid["id"],
                clearing_result_payload(
                    "CLEARED", cleared_price_usd_per_mwh=36.99, cleared_mw=10.0
                ),
                MARKET_OPERATOR,
            ),
            "ERR_CLEARING_PRICE_BELOW_FLOOR",
        )

        cleared = validate_success(
                api_client.post_clearing_result(
                    bid["id"],
                    clearing_result_payload(
                        "CLEARED", cleared_price_usd_per_mwh=37.00, cleared_mw=10.0
                    ),
                    MARKET_OPERATOR,
                )
            )

        assert cleared["status"] == "CLEARED"
        assert cleared["cleared_price_usd_per_mwh"] == pytest.approx(37.00, abs=0.01)


class TestBaselineReferenceIsAThreePartConjunction:
    """Existence passes the reference check; completion and chronology are extra."""

    def _scheduled_baseline(self):
        set_clock()
        asset = provision_asset()
        return asset, schedule_test(asset["id"], scheduled_date="2026-08-05T00:00:00Z")

    def _schedule_response(self, asset_id, scheduled_date, baseline_test_id):
        return api_client.create_capacity_test(
            create_capacity_test_payload(
                asset_id,
                scheduled_date=scheduled_date,
                baseline_test_id=baseline_test_id,
            ),
            ASSET_MANAGER,
        )

    def test_a_baseline_that_has_not_run_is_invalid(self):
        """The row exists, so the reference check passes and the model check rejects.

        PRD: "When supplied, the baseline must name a capacity test of the *same* asset whose `status` is `COMPLETED` and whose `scheduled_date` is strictly earlier than this test's `scheduled_date`, and it must not name the test itself; any of those violations is refused with `ERR_BASELINE_TEST_INVALID` (HTTP 422)."

        Design: Corner/errors/baseline_test_reference_must_be_completed_and_strictly_earlier
        """
        asset, baseline = self._scheduled_baseline()

        assert baseline["status"] == "SCHEDULED"
        validate_error(
            self._schedule_response(
                asset["id"], "2026-08-20T00:00:00Z", baseline["id"]
            ),
            "ERR_BASELINE_TEST_INVALID",
            expected_status=422,
        )

    def test_the_baseline_becomes_completed_by_running_it(self):
        """The legitimate run is what makes the reference admissible at all.

        PRD: "The owning `SiteController` moves the test `IN_PROGRESS → COMPLETED`, supplying `measured_capacity_mwh`, the energy the test discharge actually delivered, which must be greater than 0."

        Design: Corner/errors/baseline_test_reference_must_be_completed_and_strictly_earlier
        """
        asset, baseline = self._scheduled_baseline()

        start_test(baseline["id"], asset["id"])
        finished = finish_test(baseline["id"], asset["id"], measured_capacity_mwh=92.0)

        assert finished["status"] == "COMPLETED"

    def test_a_completed_but_later_baseline_is_invalid(self):
        """Strictly earlier, so a same-day or later baseline is refused.

        PRD: "When supplied, the baseline must name a capacity test of the *same* asset whose `status` is `COMPLETED` and whose `scheduled_date` is strictly earlier than this test's `scheduled_date`, and it must not name the test itself; any of those violations is refused with `ERR_BASELINE_TEST_INVALID` (HTTP 422)."

        Design: Corner/errors/baseline_test_reference_must_be_completed_and_strictly_earlier
        """
        asset, baseline = self._scheduled_baseline()
        start_test(baseline["id"], asset["id"])
        finish_test(baseline["id"], asset["id"], measured_capacity_mwh=92.0)

        validate_error(
            self._schedule_response(
                asset["id"], "2026-08-01T00:00:00Z", baseline["id"]
            ),
            "ERR_BASELINE_TEST_INVALID",
            expected_status=422,
        )

    def test_a_completed_and_earlier_baseline_is_accepted(self):
        """Both halves satisfied, and the new test stores the reference.

        PRD: "`baseline_test_id` is optional and names the earlier completed test this one is measured against; it is null for an asset's first test."

        Design: Corner/errors/baseline_test_reference_must_be_completed_and_strictly_earlier
        """
        asset, baseline = self._scheduled_baseline()
        start_test(baseline["id"], asset["id"])
        finish_test(baseline["id"], asset["id"], measured_capacity_mwh=92.0)

        follow_up = validate_success(
                self._schedule_response(
                    asset["id"], "2026-08-20T00:00:00Z", baseline["id"]
                ),
                expected_status=201,
            )

        assert follow_up["baseline_test_id"] == baseline["id"]
        assert refresh_test(follow_up["id"])["status"] == "SCHEDULED"


class TestAncillaryOffersCarryTheTighterBound:
    """The half-rating bound applies only to the three ancillary products."""

    def _held(self):
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        reservation = hold_reservation(
            asset["id"],
            reserved_mwh=40.0,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        )
        return asset, reservation

    def _draft_response(self, asset_id, reservation_id, **overrides):
        return api_client.create_market_bid(
            create_market_bid_payload(
                asset_id,
                reservation_id,
                delivery_start=DELIVERY_START,
                delivery_end=DELIVERY_END,
                **overrides,
            ),
            TRADER,
        )

    def test_an_energy_offer_above_the_rating_is_refused(self):
        """The energy ceiling is the smaller of the rating and the interconnection limit.

        PRD: "`offer_mw` must not exceed the smaller of the asset's `power_rating_mw` and its `poi_mw_limit`."

        Design: Corner/errors/ancillary_offer_above_half_the_rating_is_rejected
        """
        asset, reservation = self._held()

        validate_error(
            self._draft_response(
                asset["id"],
                reservation["id"],
                market_type="DAY_AHEAD",
                product="ENERGY",
                direction="DISCHARGE",
                offer_mw=25.01,
            ),
            "ERR_OFFER_MW_EXCEEDS_RATING",
            expected_status=422,
        )

    def test_a_spinning_reserve_offer_above_half_the_rating_is_refused(self):
        """13.0 MW is far below the 25.0 MW rating and still above the reserve bound.

        PRD: "For a `REG_UP`, `REG_DOWN` or `SPIN` product `offer_mw` must additionally not exceed half of `power_rating_mw`, because a regulation or reserve product requires the plant to be able to move in both directions from its operating point."

        Design: Corner/errors/ancillary_offer_above_half_the_rating_is_rejected
        """
        asset, reservation = self._held()

        validate_error(
            self._draft_response(
                asset["id"],
                reservation["id"],
                market_type="REAL_TIME",
                product="SPIN",
                direction="DISCHARGE",
                offer_mw=13.0,
            ),
            "ERR_OFFER_MW_EXCEEDS_RATING",
            expected_status=422,
        )

    def test_the_tighter_bound_applies_to_the_charging_direction_too(self):
        """A regulation-down offer absorbs energy and is bounded identically.

        PRD: "Either breach is rejected with `ERR_OFFER_MW_EXCEEDS_RATING` (HTTP 422)."

        Design: Corner/errors/ancillary_offer_above_half_the_rating_is_rejected
        """
        asset, reservation = self._held()

        validate_error(
            self._draft_response(
                asset["id"],
                reservation["id"],
                market_type="REAL_TIME",
                product="REG_DOWN",
                direction="CHARGE",
                offer_mw=12.51,
            ),
            "ERR_OFFER_MW_EXCEEDS_RATING",
            expected_status=422,
        )

    def test_a_reserve_offer_exactly_at_half_the_rating_is_priced_and_kept(self):
        """The bound is inclusive, and the reserve weighting prices the floor at 20.35.

        PRD: "The fourth element is the product weighting: 1.00 for `ENERGY`, 0.70 for `REG_UP`, 0.55 for `SPIN` and 0.35 for `REG_DOWN`."

        Design: Corner/errors/ancillary_offer_above_half_the_rating_is_rejected
        """
        asset, reservation = self._held()

        bid = validate_success(
                self._draft_response(
                    asset["id"],
                    reservation["id"],
                    market_type="REAL_TIME",
                    product="SPIN",
                    direction="DISCHARGE",
                    offer_mw=12.5,
                ),
                expected_status=201,
            )

        assert bid["status"] == "DRAFT"
        assert bid["offer_price_usd_per_mwh"] == pytest.approx(20.35, abs=0.01)


class TestCapacityCommitmentBoundsShareOneCode:
    """One code, two unrelated dimensions, both inclusive at the boundary."""

    def _enrolment_response(self, asset_id, committed_mw, availability_hours_required):
        return api_client.create_capacity_obligation(
            create_capacity_obligation_payload(
                asset_id,
                program_name="Desert RA 2027",
                program_year=2027,
                committed_mw=committed_mw,
                availability_hours_required=availability_hours_required,
                penalty_rate_usd_per_mw_hour=3000.0,
            ),
            ASSET_MANAGER,
        )

    def test_a_commitment_above_the_rating_is_refused(self):
        """Power is measured against the plant's nameplate rating.

        PRD: "A `committed_mw` above the asset's `power_rating_mw`, or an `availability_hours_required` above 8760, is refused with `ERR_COMMITMENT_EXCEEDS_RATING` (HTTP 422)."

        Design: Corner/errors/capacity_commitment_above_rating_or_annual_hours_is_rejected
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()

        validate_error(
            self._enrolment_response(asset["id"], 25.01, 7884.0),
            "ERR_COMMITMENT_EXCEEDS_RATING",
            expected_status=422,
        )

    def test_required_hours_above_the_year_are_refused(self):
        """The same code, the other dimension: a year has 8760 hours.

        PRD: "`availability_hours_required` is the annual availability the programme demands, greater than 0 and at most 8760."

        Design: Corner/errors/capacity_commitment_above_rating_or_annual_hours_is_rejected
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()

        validate_error(
            self._enrolment_response(asset["id"], 20.0, 8760.01),
            "ERR_COMMITMENT_EXCEEDS_RATING",
            expected_status=422,
        )

    def test_a_full_rating_full_year_enrolment_is_accepted(self):
        """Both bounds are inclusive, so the aggressive enrolment is legal.

        PRD: "A new obligation is created with `status` `ACTIVE`, `unavailable_hours` 0.0, `accrual_started_at` null, `measured_available_hours` 0.0, `availability_pct` null, `shortfall_hours` 0.0, `penalty_exposure_usd` 0.0, `assessment_mode` null and `derated_committed_mw` null, and returns HTTP 201."

        Design: Corner/errors/capacity_commitment_above_rating_or_annual_hours_is_rejected
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()

        obligation = validate_success(
                self._enrolment_response(asset["id"], 25.0, 8760.0), expected_status=201
            )

        assert obligation["status"] == "ACTIVE"
        assert obligation["committed_mw"] == pytest.approx(25.0, abs=0.01)
        assert obligation["availability_hours_required"] == pytest.approx(8760.0, abs=0.01)

    def test_the_rejections_never_consumed_the_programme_slot(self):
        """The uniqueness slot is still free after two refusals, so the third enrols.

        PRD: "At most one obligation may exist for a given combination of `asset_id`, `program_name` and `program_year`, whatever its status, and a second enrolment for the same triple is refused with `ERR_DUPLICATE_OBLIGATION` (HTTP 409) rather than merged into the first."

        Design: Corner/errors/capacity_commitment_above_rating_or_annual_hours_is_rejected
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        validate_error(
            self._enrolment_response(asset["id"], 25.01, 7884.0),
            "ERR_COMMITMENT_EXCEEDS_RATING",
        )
        validate_error(
            self._enrolment_response(asset["id"], 20.0, 8760.01),
            "ERR_COMMITMENT_EXCEEDS_RATING",
        )
        kept = get_success_data(self._enrolment_response(asset["id"], 25.0, 8760.0))

        data, meta = validate_paginated(
            api_client.list_capacity_obligations(
                ASSET_MANAGER, params={"asset_id": asset["id"]}
            )
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [kept["id"]]


class TestWarrantyClaimActionsCarryTheirOwnCodes:
    """Three codes guard three consecutive steps, all reachable from one DRAFT."""

    def _drafted_claim(self):
        set_clock()
        asset = lightly_cycled_plant()
        test = schedule_test(asset["id"], scheduled_date="2026-08-01T00:00:00Z")
        start_test(test["id"], asset["id"])
        finished = finish_test(test["id"], asset["id"], measured_capacity_mwh=90.0)
        return asset, finished, file_claim(asset["id"], finished["id"])

    def test_the_cited_test_is_triggered_and_the_claim_starts_as_a_draft(self):
        """A triggered test is the claim's evidence, and filing lands in DRAFT.

        PRD: "A drafted claim copies `claimed_shortfall_pct` from the cited test's `soh_deficit_pct`, starts with `status` `DRAFT`, records `created_by_user_id` as the acting identifier, leaves `submitted_by_user_id`, `adjudicated_by_user_id`, `remedy_energy_add_mwh`, `remedy_install_date`, `remedy_outage_days` and `denial_reason` null, and returns HTTP 201."

        Design: Corner/errors/warranty_claim_actions_out_of_order_return_their_own_codes
        """
        _, test, claim = self._drafted_claim()

        assert test["warranty_claim_triggered"] is True
        assert test["soh_deficit_pct"] == pytest.approx(2.10, abs=0.01)
        assert claim["status"] == "DRAFT"
        assert claim["claimed_shortfall_pct"] == pytest.approx(2.10, abs=0.01)
        assert claim["remedy_energy_add_mwh"] is None

    def test_adjudicating_a_draft_claim_reports_not_submitted(self):
        """Issued by a non-filer, so the segregation check passes and the state guard answers.

        PRD: "Adjudication is a `PlatformAdmin`'s act on a `SUBMITTED` claim — refused with `ERR_CLAIM_NOT_SUBMITTED` otherwise — and the field `decision` selects one of two branches with disjoint side effects."

        Design: Corner/errors/warranty_claim_actions_out_of_order_return_their_own_codes
        """
        _, _, claim = self._drafted_claim()

        validate_error(
            api_client.adjudicate_warranty_claim(
                claim["id"],
                approve_claim_payload(
                    remedy_install_date="2026-09-15T00:00:00Z", remedy_outage_days=5
                ),
                CLAIM_ADJUDICATOR,
            ),
            "ERR_CLAIM_NOT_SUBMITTED",
            expected_status=409,
        )
        assert refresh_claim(claim["id"])["status"] == "DRAFT"

    def test_installing_a_remedy_on_a_draft_claim_reports_not_approved(self):
        """Only `APPROVED` admits a remedy, and a draft is two steps away.

        PRD: "An `AssetManager` moves an `APPROVED` claim to `REMEDIED` once the current logical instant is at or after the claim's `remedy_install_date`, and while the asset's `safety_state` is not `LOCKOUT`; an attempt on a claim whose `status` is not `APPROVED` is refused with `ERR_CLAIM_NOT_APPROVED`."

        Design: Corner/errors/warranty_claim_actions_out_of_order_return_their_own_codes
        """
        _, _, claim = self._drafted_claim()

        validate_error(
            api_client.install_warranty_remedy(claim["id"], CLAIM_FILER),
            "ERR_CLAIM_NOT_APPROVED",
            expected_status=409,
        )

    def test_submission_still_works_after_the_two_rejections(self):
        """The legal step is untouched by the refusals that preceded it.

        PRD: "An `AssetManager` then files the claim with the provider, moving it `DRAFT → SUBMITTED`; the cited test must still be `COMPLETED` with `warranty_claim_triggered` true, and the current logical instant must still be at or before the cited test's `scheduled_date` plus 30 days."

        Design: Corner/errors/warranty_claim_actions_out_of_order_return_their_own_codes
        """
        _, _, claim = self._drafted_claim()
        validate_error(
            api_client.install_warranty_remedy(claim["id"], CLAIM_FILER),
            "ERR_CLAIM_NOT_APPROVED",
        )

        submitted = submit_claim(claim["id"], headers=CLAIM_FILER)

        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == "am_filer"

    def test_a_second_submission_reports_not_draft(self):
        """Filing is once-only, and the recorded filer is not overwritten.

        PRD: "Submitting a claim whose `status` is not `DRAFT` is refused with `ERR_CLAIM_NOT_DRAFT`."

        Design: Corner/errors/warranty_claim_actions_out_of_order_return_their_own_codes
        """
        _, _, claim = self._drafted_claim()
        submit_claim(claim["id"], headers=CLAIM_FILER)

        validate_error(
            api_client.submit_warranty_claim(claim["id"], CLAIM_FILER),
            "ERR_CLAIM_NOT_DRAFT",
            expected_status=409,
        )

        after = refresh_claim(claim["id"])
        assert after["status"] == "SUBMITTED"
        assert after["submitted_by_user_id"] == "am_filer"

    def test_no_rejected_call_moved_any_energy(self):
        """A remedy on a submitted claim is still refused, and the plant has not grown.

        PRD: "The asset's `rated_energy_mwh` does *not* change yet; only the `REMEDIED` status admits augmentation energy."

        Design: Corner/errors/warranty_claim_actions_out_of_order_return_their_own_codes
        """
        asset, _, claim = self._drafted_claim()
        submit_claim(claim["id"], headers=CLAIM_FILER)

        validate_error(
            api_client.install_warranty_remedy(claim["id"], CLAIM_FILER),
            "ERR_CLAIM_NOT_APPROVED",
            expected_status=409,
        )

        assert refresh_claim(claim["id"])["remedy_energy_add_mwh"] is None
        assert refresh_asset(asset["id"])["rated_energy_mwh"] == pytest.approx(100.0, abs=0.01)
