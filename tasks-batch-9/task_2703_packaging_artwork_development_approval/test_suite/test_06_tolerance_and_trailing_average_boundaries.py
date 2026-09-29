"""Numeric edges: the inclusive colour verdict and the runout replay arithmetic."""

import pytest

from test_helpers import (
    append_depletion,
    approved_version,
    asset_with_obsolete_predecessor,
    decide_color,
    depletion,
    disposition_runout,
    new_printer,
    new_proof,
    new_runout,
    read_asset,
    read_runout,
    read_version,
)

BRAND_CRITICAL = {"brand_critical_color": True}


class TestDeltaEVerdictAtTheTightenedTolerance:
    """A brand-critical carton judged at 1.49, 1.50 and 1.51."""

    def _three_pending_proofs(self):
        _brief, _asset, version = approved_version(asset_overrides=BRAND_CRITICAL)
        printer = new_printer()
        proofs = [new_proof(version["id"], printer) for _ in range(3)]
        for proof in proofs:
            # 2.0 for a G7_MASTER vendor on COATED_PAPER, tightened by 0.5.
            assert proof["effective_tolerance"] == pytest.approx(1.5, abs=0.01)
            assert proof["color_status"] == "COLOR_PENDING"
            assert proof["substrate_status"] == "SUBSTRATE_PENDING"
        return proofs

    def test_a_measurement_equal_to_the_tightened_tolerance_still_passes(self):
        """The comparison is inclusive, so 1.50 against 1.5 is a pass.

        PRD §3.6: "The stored measurement is compared against `effective_tolerance`
        **inclusively**: a measurement less than or equal to the tolerance yields
        `color_status` `COLOR_PASS`, and a measurement exactly equal to the tolerance
        is therefore a pass, while anything greater yields `COLOR_FAIL`."

        Design: Difficulty/boundary_precision_check/delta_e_verdict_inclusive_at_1_50_after_brand_critical_tightening
        """
        low, equal, _high = self._three_pending_proofs()

        under = decide_color(low["id"], 1.49)
        assert under["color_status"] == "COLOR_PASS"
        assert under["measured_delta_e_max"] == pytest.approx(1.49, abs=0.01)

        on_the_line = decide_color(equal["id"], 1.5)
        assert on_the_line["color_status"] == "COLOR_PASS"
        assert on_the_line["measured_delta_e_max"] == pytest.approx(1.50, abs=0.01)
        assert on_the_line["effective_tolerance"] == pytest.approx(1.5, abs=0.01)
        assert on_the_line["proof_state"] == "PROOF_IN_REVIEW"

    def test_the_tightening_is_what_fails_a_measurement_of_one_five_one(self):
        """Against the untightened base of 2.0 the same measurement would pass.

        PRD §3.6: "When the owning asset carries `brand_critical_color`, the base
        tolerance is tightened by subtracting 0.5; when it does not, nothing is
        subtracted."

        Design: Difficulty/boundary_precision_check/delta_e_verdict_inclusive_at_1_50_after_brand_critical_tightening
        """
        _low, _equal, high = self._three_pending_proofs()

        failed = decide_color(high["id"], 1.51)

        assert failed["effective_tolerance"] == pytest.approx(1.5, abs=0.01)
        assert failed["effective_tolerance"] != pytest.approx(2.0, abs=0.01)
        assert failed["color_status"] == "COLOR_FAIL"
        assert failed["measured_delta_e_max"] == pytest.approx(1.51, abs=0.01)
        assert failed["substrate_status"] == "SUBSTRATE_PENDING"
        # PRD §3.6: "If `color_status` is `COLOR_FAIL` or `substrate_status` is
        # `SUBSTRATE_REJECTED`, the proof is `PROOF_REJECTED` — and this holds even
        # while another dimension is still pending, so a colour failure fixes the
        # outcome immediately without waiting for the substrate judgement."
        assert failed["proof_state"] == "PROOF_REJECTED"


class TestTrailingAverageAndExhaustionEdges:
    """One replay that walks a tie, an exact division and an exact zero."""

    def _monitored_runout(self):
        _brief, asset, v1, _v2 = asset_with_obsolete_predecessor()
        runout = new_runout(asset, v1, on_hand_qty=20004, weekly_usage_qty=3000)
        # ceil(20004 / 3000) = 7 whole weeks from 2026-08-03.
        assert runout["projected_runout_date"] == "2026-09-21"
        assert runout["state"] == "PLANNED"
        assert runout["remaining_qty"] == 20004
        assert runout["trailing_avg_usage_qty"] is None
        return asset, v1, runout

    def test_an_exact_division_does_not_buy_a_spare_week(self):
        """16670 over 3334 is exactly 5.0, so the ceiling adds five weeks, not six.

        PRD §3.8: "When the replay finishes with stock still remaining and at least
        one record exists, `actual_runout_date` is extrapolated instead of observed:
        the number of extra whole weeks is `remaining_qty` divided by
        `trailing_avg_usage_qty` rounded **up**, the anchor is the calendar date of
        the last stored record's `week_start_utc` advanced by seven days, and
        `actual_runout_date` is that anchor advanced by a further seven days for each
        extra week."

        Design: Difficulty/boundary_precision_check/trailing_average_half_up_tie_and_exact_division_ceil_on_runout_replay
        """
        _asset, _v1, runout = self._monitored_runout()

        first = append_depletion(
            runout["id"], [depletion("2026-08-03T00:00:00Z", 3334)]
        )

        assert first["remaining_qty"] == 16670
        assert first["trailing_avg_usage_qty"] == 3334
        assert first["actual_runout_date"] == "2026-09-14"
        assert first["actual_runout_date"] != "2026-09-21"
        assert first["projected_runout_date"] == "2026-09-21"
        assert first["state"] == "MONITORING"

    def test_the_trailing_mean_rounds_half_up_and_never_truncates(self):
        """A mean of 3334.5 stores 3335, and a mean of 3334.666... also stores 3335.

        PRD §3.8: "`trailing_avg_usage_qty` is null while `depletion_records` is
        empty; otherwise it is the arithmetic mean of the `units_consumed` of the last
        three records in ascending order — or of all of them when fewer than three
        exist — rounded half up to a whole number of units and then floored at 1, so
        it can never be zero."

        Design: Difficulty/boundary_precision_check/trailing_average_half_up_tie_and_exact_division_ceil_on_runout_replay
        """
        _asset, _v1, runout = self._monitored_runout()

        append_depletion(runout["id"], [depletion("2026-08-03T00:00:00Z", 3334)])
        second = append_depletion(
            runout["id"], [depletion("2026-08-10T00:00:00Z", 3335)]
        )

        # (3334 + 3335) / 2 = 3334.5, which rounds half up to 3335, not 3334.
        assert second["trailing_avg_usage_qty"] == 3335
        assert second["remaining_qty"] == 13335
        assert second["actual_runout_date"] == "2026-09-14"

        third = append_depletion(
            runout["id"], [depletion("2026-08-17T00:00:00Z", 3335)]
        )

        # 10004 / 3 = 3334.666..., which rounds up to 3335 rather than truncating.
        assert third["trailing_avg_usage_qty"] == 3335
        assert third["remaining_qty"] == 10000
        assert third["actual_runout_date"] == "2026-09-14"
        assert third["projected_runout_date"] == "2026-09-21"

    def test_hitting_exactly_zero_observes_the_date_and_unlocks_the_runout_form(self):
        """The window slides, stock lands on nothing, and RUNOUT becomes legal.

        PRD §3.8: "A `RUNOUT` disposition asserts that the stock is fully depleted
        and therefore requires `remaining_qty` to be exactly 0; a residual balance is
        `ERR_UNIT_CONSERVATION_VIOLATION`."

        Design: Difficulty/boundary_precision_check/trailing_average_half_up_tie_and_exact_division_ceil_on_runout_replay
        """
        asset, v1, runout = self._monitored_runout()

        append_depletion(runout["id"], [depletion("2026-08-03T00:00:00Z", 3334)])
        append_depletion(runout["id"], [depletion("2026-08-10T00:00:00Z", 3335)])
        append_depletion(runout["id"], [depletion("2026-08-17T00:00:00Z", 3335)])
        fourth = append_depletion(
            runout["id"], [depletion("2026-08-24T00:00:00Z", 1)]
        )

        # The first record has slid out of the window: (3335 + 3335 + 1) / 3 = 2223.666...
        assert fourth["trailing_avg_usage_qty"] == 2224
        assert fourth["remaining_qty"] == 9999
        assert fourth["actual_runout_date"] == "2026-10-05"

        fifth = append_depletion(
            runout["id"], [depletion("2026-08-31T00:00:00Z", 9999)]
        )

        assert fifth["remaining_qty"] == 0
        # The exhaustion branch observes the week of the exhausting record plus seven days.
        assert fifth["actual_runout_date"] == "2026-09-07"
        assert fifth["trailing_avg_usage_qty"] == 4445
        assert fifth["projected_runout_date"] == "2026-09-21"
        assert fifth["state"] == "MONITORING"
        assert len(fifth["depletion_records"]) == 5

        closed = disposition_runout(runout["id"], "RUNOUT")
        assert closed["state"] == "RUNOUT_COMPLETE"
        assert closed["disposition"] == "RUNOUT"
        assert closed["units_scrapped"] == 0
        assert closed["units_reworked"] == 0
        assert closed["total_changeover_cost_cents"] == 0

        assert read_version(v1["id"])["state"] == "OBSOLETE"
        assert read_asset(asset["id"])["obsolescence_state"] == "SUPERSEDED"
        assert read_runout(runout["id"])["projected_runout_date"] == "2026-09-21"
