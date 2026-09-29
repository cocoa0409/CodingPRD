"""Two-pass performance scoring and two-variant capacity assessment.

The same stored telemetry scores twice, and the same stored availability record
assesses twice; both pairs must diverge exactly as the contract says.
"""
import pytest

from test_helpers.fixtures import (
    DISPATCH_DAY_CLOCK,
    NOMINAL_DELIVERY_SAMPLES,
    append_sample,
    assess_obligation,
    delivered_position,
    enrol_obligation,
    record_unavailability,
    refresh_dispatch,
    refresh_obligation,
    reference_plant,
    set_clock,
    settle_score,
)


class TestProvisionalVersusSettledScore:
    def test_provisional_score_admits_only_on_time_telemetry(self):
        """A completed hour of nominal delivery scores 91.10 on its four on-time samples.

        PRD: "The provisional pass runs inside completion and admits only samples whose `sampled_at` is at or before `setpoint_end`."

        Design: Difficulty/dual_variant_calc/dispatch_performance_provisional_versus_settled_score
        """
        set_clock(DISPATCH_DAY_CLOCK)
        position = delivered_position()
        dispatch = position["dispatch"]

        assert dispatch["scoring_status"] == "PROVISIONAL"
        assert dispatch["execution_status"] == "COMPLETED"
        assert dispatch["delivered_mwh"] == pytest.approx(19.8, abs=0.01)
        assert dispatch["accuracy_score"] == pytest.approx(98.00, abs=0.01)
        assert dispatch["deadband_pct"] == pytest.approx(75.00, abs=0.01)
        assert dispatch["composite_score"] == pytest.approx(91.10, abs=0.01)
        assert dispatch["telemetry_sample_count"] == 4

    def test_provisional_pass_never_charges_the_operator(self):
        """Completion records a score but bills nothing, whatever the score.

        PRD: "Its `non_performance_charge_usd` is forced to 0.0 regardless of how poor the composite score is — the provisional pass never charges."

        Design: Difficulty/dual_variant_calc/dispatch_performance_provisional_versus_settled_score
        """
        set_clock(DISPATCH_DAY_CLOCK)
        position = delivered_position()

        assert position["dispatch"]["non_performance_charge_usd"] == pytest.approx(
            0.00, abs=0.01
        )

    def test_late_sample_is_admitted_by_settlement_and_drags_the_score_below_the_floor(
        self,
    ):
        """A 2 MW reading arriving after the setpoint ended costs 57.60 dollars at settlement.

        PRD: "The settled pass admits *every* sample of the instruction, including the late-arriving ones whose `sampled_at` is after `setpoint_end`; those drag both the accuracy average and the deadband percentage down, because a sample recorded after the setpoint ended is measured against a setpoint the plant was no longer holding."

        Design: Difficulty/dual_variant_calc/dispatch_performance_provisional_versus_settled_score
        """
        set_clock(DISPATCH_DAY_CLOCK)
        position = delivered_position()
        asset_id = position["asset"]["id"]
        dispatch_id = position["dispatch"]["id"]

        append_sample(
            dispatch_id,
            asset_id,
            5,
            "2026-08-10T15:10:00Z",
            measured_mw=2.0,
            soc_mwh_reading=59.7,
        )
        settled = settle_score(dispatch_id)

        assert settled["scoring_status"] == "SETTLED"
        assert settled["execution_status"] == "COMPLETED"
        assert settled["telemetry_sample_count"] == 5
        assert settled["accuracy_score"] == pytest.approx(80.40, abs=0.01)
        assert settled["deadband_pct"] == pytest.approx(60.00, abs=0.01)
        assert settled["composite_score"] == pytest.approx(74.28, abs=0.01)
        assert settled["non_performance_charge_usd"] == pytest.approx(57.60, abs=0.01)

    def test_a_late_sample_alone_does_not_restate_the_provisional_figures(self):
        """The provisional score stands until the market operator settles it.

        PRD: "A sample may be appended only while the instruction's `execution_status` is `EXECUTING` or `COMPLETED`; appending to an instruction in any other execution state is refused with `ERR_DISPATCH_NOT_EXECUTING`."

        Design: Difficulty/dual_variant_calc/dispatch_performance_provisional_versus_settled_score
        """
        set_clock(DISPATCH_DAY_CLOCK)
        position = delivered_position()
        asset_id = position["asset"]["id"]
        dispatch_id = position["dispatch"]["id"]

        late = append_sample(
            dispatch_id,
            asset_id,
            5,
            "2026-08-10T15:10:00Z",
            measured_mw=2.0,
            soc_mwh_reading=59.7,
        )
        after = refresh_dispatch(dispatch_id)

        assert late["sample_index"] == 5
        assert after["scoring_status"] == "PROVISIONAL"
        assert after["telemetry_sample_count"] == 5
        assert after["composite_score"] == pytest.approx(91.10, abs=0.01)
        assert after["non_performance_charge_usd"] == pytest.approx(0.00, abs=0.01)
        assert len(NOMINAL_DELIVERY_SAMPLES) == 4


class TestPreliminaryVersusFinalAssessment:
    """A 120-hour forced outage assessed mid-year and again at year end."""

    PROGRAMME = {
        "program_name": "ISO Capacity Auction",
        "program_year": 2026,
        "committed_mw": 20.0,
        "availability_hours_required": 8600.0,
        "penalty_rate_usd_per_mw_hour": 45.00,
    }

    def _obligation_with_outage(self):
        set_clock("2026-08-06T00:00:00Z")
        asset = reference_plant()
        obligation = enrol_obligation(asset["id"], **self.PROGRAMME)
        record_unavailability(obligation["id"], 120.0, reason="FORCED_OUTAGE")
        return obligation

    def test_preliminary_assessment_prorates_the_requirement(self):
        """Six months into the year, 120 lost hours leave a 24.88 hour shortfall.

        PRD: "Under the `PRELIMINARY` variant — an in-year interim assessment — the assessed period runs from that instant to the current logical instant, and the requirement is pro-rated: the scaled requirement is `availability_hours_required` multiplied by the period's hours divided by 8760.0, rounded half up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/capacity_obligation_preliminary_versus_final_penalty
        """
        obligation = self._obligation_with_outage()

        assessed = assess_obligation(obligation["id"], "PRELIMINARY")

        assert assessed["assessment_mode"] == "PRELIMINARY"
        assert assessed["measured_available_hours"] == pytest.approx(5088.00, abs=0.01)
        assert assessed["availability_pct"] == pytest.approx(97.70, abs=0.01)
        assert assessed["shortfall_hours"] == pytest.approx(24.88, abs=0.01)
        assert assessed["penalty_exposure_usd"] == pytest.approx(22392.00, abs=0.01)
        assert assessed["status"] == "SHORTFALL"

    def test_final_assessment_measures_the_whole_programme_year(self):
        """The same 120 lost hours clear entirely against an unscaled 8600 hour requirement.

        PRD: "Under the `FINAL` variant — the end-of-programme-year settlement — the assessed period is the full 8760.0 hours of the year and the requirement is `availability_hours_required` unscaled."

        Design: Difficulty/dual_variant_calc/capacity_obligation_preliminary_versus_final_penalty
        """
        obligation = self._obligation_with_outage()

        assessed = assess_obligation(obligation["id"], "FINAL")

        assert assessed["assessment_mode"] == "FINAL"
        assert assessed["measured_available_hours"] == pytest.approx(8640.00, abs=0.01)
        assert assessed["availability_pct"] == pytest.approx(98.63, abs=0.01)
        assert assessed["shortfall_hours"] == pytest.approx(0.00, abs=0.01)
        assert assessed["penalty_exposure_usd"] == pytest.approx(0.00, abs=0.01)
        assert assessed["status"] == "FULFILLED"

    def test_both_variants_read_the_same_stored_unavailability(self):
        """Assessing twice never consumes or restates the recorded outage hours.

        PRD: "An assessment producing no shortfall hours settles the obligation as `FULFILLED` when the mode is `FINAL`; as `ACTIVE` when the mode is `PRELIMINARY` and `derated_committed_mw` is null; and as `SHORTFALL` when `derated_committed_mw` is not null, because a capacity-derated plant is in shortfall even with a perfect availability record."

        Design: Difficulty/dual_variant_calc/capacity_obligation_preliminary_versus_final_penalty
        """
        obligation = self._obligation_with_outage()

        preliminary = assess_obligation(obligation["id"], "PRELIMINARY")
        final = assess_obligation(obligation["id"], "FINAL")
        stored = refresh_obligation(obligation["id"])

        assert preliminary["unavailable_hours"] == pytest.approx(120.0, abs=0.01)
        assert final["unavailable_hours"] == pytest.approx(120.0, abs=0.01)
        assert stored["unavailable_hours"] == pytest.approx(120.0, abs=0.01)
        assert stored["status"] == "FULFILLED"
        assert preliminary["penalty_exposure_usd"] == pytest.approx(22392.00, abs=0.01)
        assert stored["penalty_exposure_usd"] == pytest.approx(0.00, abs=0.01)
