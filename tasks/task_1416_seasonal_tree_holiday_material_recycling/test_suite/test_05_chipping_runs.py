"""Chipping runs: scheduling window and buffer, dual-variant yield
computation, and the variance review gate."""
import pytest

from test_helpers import (
    ADMIN,
    HAULER,
    ApiErrorId,
    api_client,
    assert_chipping_run,
    complete_run,
    create_active_program,
    get_program,
    open_site,
    record_intake,
    schedule_run,
    set_clock,
    site_stockpile,
    validate_error,
    validate_success,
)

RUN_CLOCK = "2027-01-17T08:30:00Z"


def _setup_open_site_with_stockpile(clock="2027-01-05T00:00:00Z"):
    """ACTIVE program, OPEN site with a 20-tree MEDIUM intake recorded."""
    ctx = create_active_program(clock=clock)
    open_site(ctx["site"])
    record_intake(ctx["site"]["id"], tree_count=20, size_class="MEDIUM")
    return ctx


class TestYieldDualVariant:

    def test_theoretical_computed_measured_stored_variance_reported(self):
        """PRD section 3.5: "The `theoretical_output_cy` is then the
        `measured_input_tons` multiplied by the material class's
        `YIELD_CY_PER_TON` factor, multiplied by one minus the contamination
        fraction, with the result rounded half-up to two decimal places. The
        raw variance is the absolute difference between the
        `measured_output_cy` and the `theoretical_output_cy`, divided by the
        `theoretical_output_cy`, and is deliberately left unrounded for the
        gate; the stored `variance_pct` is that raw variance rounded half-up
        to four decimal places."
        PRD section 2.8: "`MIXED_CONIFER` material yields 2.2 cubic yards per
        ton".

        Design: Difficulty/dual_variant_calc/chipping_yield_theoretical_vs_measured
        """
        ctx = _setup_open_site_with_stockpile()
        run = schedule_run(ctx["program"]["id"], ctx["site"]["id"],
                           material_class="MIXED_CONIFER")
        completed = complete_run(
            run, measured_input_tons=10.0, contaminated_input_tons=1.0,
            measured_output_cy=18.5)
        assert_chipping_run(completed)
        # theoretical = round2(10.0 * 2.2 * (1 - 1.0/10.0)) = 19.80
        assert completed["theoretical_output_cy"] == pytest.approx(19.8)
        assert completed["measured_output_cy"] == pytest.approx(18.5)
        # raw variance = 1.3 / 19.8 = 0.065656... -> round4 = 0.0657
        assert completed["variance_pct"] == pytest.approx(0.0657, abs=1e-6)
        assert completed["status"] == "COMPLETED"

        # Exact draw empties the pile; the pool is credited the measured
        # output.
        assert site_stockpile(ctx["site"]["id"]) == pytest.approx(0.0)
        program = get_program(ctx["program"]["id"])
        assert program["mulch_produced_cy"] == pytest.approx(18.5)

    def test_hardwood_yield_factor_variant(self):
        """PRD section 2.8: "`MIXED_CONIFER` material yields 2.2 cubic yards
        per ton, `HARDWOOD` yields 1.8, and `MIXED_LOAD` yields 2.0."
        PRD section 3.5: "The `theoretical_output_cy` is then the
        `measured_input_tons` multiplied by the material class's
        `YIELD_CY_PER_TON` factor, multiplied by one minus the contamination
        fraction, with the result rounded half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/chipping_yield_theoretical_vs_measured
        """
        ctx = _setup_open_site_with_stockpile()
        run = schedule_run(ctx["program"]["id"], ctx["site"]["id"],
                           material_class="HARDWOOD")
        completed = complete_run(
            run, measured_input_tons=4.0, contaminated_input_tons=1.0,
            measured_output_cy=5.0)
        # theoretical = round2(4.0 * 1.8 * (1 - 1.0/4.0)) = 5.40
        assert completed["theoretical_output_cy"] == pytest.approx(5.4)
        # raw variance = 0.4 / 5.4 = 0.074074... <= 0.08: no review needed
        assert completed["variance_pct"] == pytest.approx(0.0741, abs=1e-6)
        assert completed["status"] == "COMPLETED"
        program = get_program(ctx["program"]["id"])
        assert program["mulch_produced_cy"] == pytest.approx(5.0)


class TestRunSchedulingRules:

    def test_run_half_hour_gap_rejected(self):
        """PRD section 3.5: "Runs at the same site must not overlap and must
        keep a two-hour buffer from one another; a gap of exactly two hours
        between runs is allowed, and any tighter packing is rejected with
        `ERR_RUN_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/chipping_run_buffer_gap
        """
        ctx = create_active_program()
        site = ctx["site"]
        run_a = schedule_run(ctx["program"]["id"], site["id"],
                             scheduled_start="2027-01-17T08:00:00Z",
                             scheduled_end="2027-01-17T10:00:00Z")

        resp = api_client.create_chipping_run(
            {"program_id": ctx["program"]["id"], "site_id": site["id"],
             "scheduled_start": "2027-01-17T10:30:00Z",
             "scheduled_end": "2027-01-17T12:00:00Z",
             "material_class": "HARDWOOD"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_RUN_OVERLAP)
        run_a_after = api_client.get_chipping_run(run_a["id"], ADMIN)
        assert run_a_after.json()["data"]["status"] == "SCHEDULED"

    def test_run_exactly_two_hour_gap_admitted(self):
        """PRD section 3.5: "Runs at the same site must not overlap and must
        keep a two-hour buffer from one another; a gap of exactly two hours
        between runs is allowed, and any tighter packing is rejected with
        `ERR_RUN_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/chipping_run_buffer_gap
        """
        ctx = create_active_program()
        site = ctx["site"]
        schedule_run(ctx["program"]["id"], site["id"],
                     scheduled_start="2027-01-17T08:00:00Z",
                     scheduled_end="2027-01-17T10:00:00Z")

        # Exactly two hours after the first run's end: admitted.
        run_c = schedule_run(ctx["program"]["id"], site["id"],
                             scheduled_start="2027-01-17T12:00:00Z",
                             scheduled_end="2027-01-17T14:00:00Z",
                             material_class="HARDWOOD")
        assert run_c["status"] == "SCHEDULED"

    def test_run_outside_processing_tail_rejected(self):
        """PRD section 3.5: "The schedule must sit inside the processing
        window — from the program's `window_start` through fourteen days after
        `window_end` — and the end must be later than the start; either
        failure is rejected with `ERR_RUN_WINDOW_INVALID`."

        Design: Corner/validations/run_outside_processing_tail_rejected
        """
        ctx = create_active_program()
        resp = api_client.create_chipping_run(
            {"program_id": ctx["program"]["id"], "site_id": ctx["site"]["id"],
             "scheduled_start": "2027-02-15T08:00:00Z",
             "scheduled_end": "2027-02-15T10:00:00Z",
             "material_class": "HARDWOOD"},
            ADMIN,
        )
        # window_end is 2027-01-16T23:59:59Z; +14 days ends 2027-01-30.
        validate_error(resp, ApiErrorId.ERR_RUN_WINDOW_INVALID)


class TestYieldVarianceGate:

    def test_yield_variance_exactly_at_threshold_allowed(self):
        """PRD section 3.5: "When the raw variance is strictly greater than
        0.08, completion is blocked unless `yield_review_confirmed` is true,
        in which case the supervisor's override is recorded on the run;
        without the flag the completion is rejected with
        `ERR_YIELD_VARIANCE_REVIEW_REQUIRED`. A raw variance of exactly 0.08
        needs no confirmation."

        Design: Corner/calculations/yield_variance_exactly_at_threshold_allowed
        """
        ctx = _setup_open_site_with_stockpile()
        run = schedule_run(ctx["program"]["id"], ctx["site"]["id"],
                           material_class="MIXED_LOAD")
        # theoretical = round2(10.0 * 2.0 * 1) = 20.00; raw variance =
        # |18.4 - 20.0| / 20.0 = 0.08 exactly -> admitted without the flag.
        completed = complete_run(
            run, measured_input_tons=10.0, contaminated_input_tons=0,
            measured_output_cy=18.4)
        assert completed["theoretical_output_cy"] == pytest.approx(20.0)
        assert completed["variance_pct"] == pytest.approx(0.08, abs=1e-6)
        assert completed["status"] == "COMPLETED"

    def test_yield_variance_over_threshold_requires_flag(self):
        """PRD section 3.5: "When the raw variance is strictly greater than
        0.08, completion is blocked unless `yield_review_confirmed` is true,
        in which case the supervisor's override is recorded on the run;
        without the flag the completion is rejected with
        `ERR_YIELD_VARIANCE_REVIEW_REQUIRED`."

        Design: Corner/calculations/yield_variance_over_threshold_requires_flag
        """
        ctx = _setup_open_site_with_stockpile()
        run = schedule_run(ctx["program"]["id"], ctx["site"]["id"],
                           material_class="MIXED_LOAD")
        stockpile_before = site_stockpile(ctx["site"]["id"])
        payload = {
            "input_cy": stockpile_before,
            "measured_input_tons": 10.0,
            "contaminated_input_tons": 0,
            "measured_output_cy": 18.0,  # raw variance 2.0/20.0 = 0.1 > 0.08
        }

        set_clock(RUN_CLOCK)
        rejected = api_client.complete_chipping_run(run["id"], payload, HAULER)
        validate_error(rejected, ApiErrorId.ERR_YIELD_VARIANCE_REVIEW_REQUIRED)
        run_after = api_client.get_chipping_run(run["id"], ADMIN)
        assert run_after.json()["data"]["status"] == "SCHEDULED"
        assert site_stockpile(ctx["site"]["id"]) == \
            pytest.approx(stockpile_before)

        # The supervisor's override admits the same payload.
        payload["yield_review_confirmed"] = True
        completed = api_client.complete_chipping_run(run["id"], payload,
                                                     HAULER)
        data = validate_success(completed, 200)
        assert data["status"] == "COMPLETED"
        assert data["variance_pct"] == pytest.approx(0.1, abs=1e-6)
        assert site_stockpile(ctx["site"]["id"]) == pytest.approx(0.0)
