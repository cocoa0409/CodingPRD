"""Two multi-step formulas whose evaluation order is part of the contract.

Planning a crop cycle rounds every weekly yield figure before anything is summed,
and mixing a fertigation batch chooses the recirculation cap from the blend the
technician asked for and never revisits it once the cap has clipped the volume.
"""

import pytest

from test_helpers import (
    api_client,
    assert_round_then_sum_baseline,
    create_fertigation_batch_payload,
    setup_planned_cycle,
    setup_transplanted_cycle,
    validate_success,
    TEST_USERS,
)

IT = TEST_USERS["irrigation_tech_headers"]

EXPECTED_WEEKLY_YIELD_LBS = [
    3595.16,
    7190.32,
    9886.68,
    11684.26,
    11684.26,
    10785.47,
    8987.90,
    8089.11,
    6291.53,
    4493.95,
]


def _mix_capped_batch():
    """Mix a batch asking for 8000 of 12000 litres back off a 4.6 mS reservoir."""
    state = setup_transplanted_cycle(clock="2026-08-06T00:00:00Z")
    payload = create_fertigation_batch_payload(
        state["zone"]["id"],
        state["cycle"]["id"],
        batch_date="2026-08-06",
        planned_volume_liters=12000,
        requested_recirculated_liters=8000,
        reservoir_ec_ms=4.6,
        target_ec_ms=3.0,
        drain_target_pct=30,
    )
    return validate_success(api_client.create_fertigation_batch(payload, IT), 201)


class TestExpectedYieldProjection:
    """The five-step yield projection run when a cycle is planned."""

    def test_density_factor_is_carried_to_four_decimal_places(self, api):
        """PRD §3.2: "Second, `density_factor` is `plants_transplanted` divided by that nominal population, rounded half up to four decimal places, and then capped at 1.2 — a grower who sets more plants than the nominal density supports gains no more than a twenty percent yield uplift from crowding."

        Design: Difficulty/combinatorial_formula/yield_curve_round_then_sum_beats_sum_then_round_by_one_cent
        """
        state = setup_planned_cycle()

        cycle = state["cycle"]

        assert cycle["density_factor"] == pytest.approx(0.9511, abs=0.00005), (
            f"2157 plants against a nominal 2268 give 0.9511, got "
            f"{cycle['density_factor']}"
        )

    def test_first_harvest_allowed_date_is_derived_from_the_cultivar(self, api):
        """PRD §3.2: "From the cultivar the server derives two dates: `planned_end_date` is the `transplant_date` advanced by `cycle_length_weeks` multiplied by seven days and then pulled back one day, and `first_harvest_allowed_date` is the `transplant_date` advanced by `first_harvest_week` minus one, multiplied by seven days."

        Design: Difficulty/combinatorial_formula/yield_curve_round_then_sum_beats_sum_then_round_by_one_cent
        """
        state = setup_planned_cycle()

        cycle = state["cycle"]

        assert cycle["first_harvest_allowed_date"] == "2026-08-24", (
            f"a 2026-08-03 transplant whose first harvest week is 4 may not be picked "
            f"before 2026-08-24, got {cycle['first_harvest_allowed_date']}"
        )

    def test_each_weekly_figure_is_rounded_before_anything_is_summed(self, api):
        """PRD §3.2: "Third, each element of `expected_weekly_yield_lbs` is the corresponding element of the cultivar's `yield_curve_lbs_per_sqft`, multiplied by `area_sqft`, multiplied by `density_factor`, and rounded half up to two decimal places — **each week is rounded before anything is summed**."

        Design: Difficulty/combinatorial_formula/yield_curve_round_then_sum_beats_sum_then_round_by_one_cent
        """
        state = setup_planned_cycle()

        weekly = state["cycle"]["expected_weekly_yield_lbs"]

        assert len(weekly) == len(EXPECTED_WEEKLY_YIELD_LBS), (
            f"expected {len(EXPECTED_WEEKLY_YIELD_LBS)} weekly figures, got {weekly}"
        )
        for index, expected in enumerate(EXPECTED_WEEKLY_YIELD_LBS):
            assert weekly[index] == pytest.approx(expected, abs=0.01), (
                f"week {index + 1} of the projection: expected {expected}, "
                f"got {weekly[index]}"
            )

    def test_baseline_total_sums_the_already_rounded_weekly_figures(self, api):
        """PRD §3.2: "Fourth, `baseline_total_yield_lbs` is the sum of those already-rounded weekly figures, itself rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/yield_curve_round_then_sum_beats_sum_then_round_by_one_cent
        """
        state = setup_planned_cycle()

        cycle = state["cycle"]

        assert cycle["baseline_total_yield_lbs"] == pytest.approx(82688.64, abs=0.005), (
            f"round-then-sum gives 82688.64, not the sum-then-round 82688.63; got "
            f"{cycle['baseline_total_yield_lbs']}"
        )
        assert_round_then_sum_baseline(cycle)

    def test_expected_total_equals_the_baseline_while_no_haircut_applies(self, api):
        """PRD §3.2: "Fifth, `expected_total_yield_lbs` is `baseline_total_yield_lbs` multiplied by the quantity one minus `pollination_haircut_pct` divided by one hundred, rounded half up to two decimal places; since `pollination_haircut_pct` is `0.00` until a pollination check moves it, a newly planned cycle's `expected_total_yield_lbs` equals its `baseline_total_yield_lbs`."

        Design: Difficulty/combinatorial_formula/yield_curve_round_then_sum_beats_sum_then_round_by_one_cent
        """
        state = setup_planned_cycle()

        cycle = state["cycle"]

        assert cycle["pollination_haircut_pct"] == pytest.approx(0.00, abs=0.01), (
            f"a newly planned cycle takes no haircut, got "
            f"{cycle['pollination_haircut_pct']}"
        )
        assert cycle["expected_total_yield_lbs"] == pytest.approx(82688.64, abs=0.005), (
            f"expected_total_yield_lbs must equal the baseline 82688.64, got "
            f"{cycle['expected_total_yield_lbs']}"
        )


class TestFertigationSinglePassBlend:
    """The recirculation cap is chosen once, from the blend that was requested."""

    def test_cap_tier_is_selected_from_the_provisional_blend(self, api):
        """PRD §3.5: "Step two selects `recirc_cap_pct` from that provisional figure alone: 60 when `provisional_blend_ec_ms` is at most 2.5, otherwise 40 when it is at most 3.2, otherwise 0."

        Design: Difficulty/combinatorial_formula/fertigation_recirc_cap_stays_pinned_to_the_provisional_blend_ec
        """
        batch = _mix_capped_batch()

        assert batch["provisional_blend_ec_ms"] == pytest.approx(3.200, abs=0.0005), (
            f"expected provisional_blend_ec_ms 3.200, got "
            f"{batch['provisional_blend_ec_ms']}"
        )
        assert batch["recirc_cap_pct"] == 40, (
            f"a provisional blend of 3.200 sits in the 40 percent tier, got "
            f"{batch['recirc_cap_pct']}"
        )

    def test_cap_clips_the_requested_recirculation_volume(self, api):
        """PRD §3.5: "Step three applies the cap: `recirculated_liters_applied` is the lesser of `requested_recirculated_liters` and the whole number obtained by taking `planned_volume_liters` multiplied by `recirc_cap_pct`, divided by one hundred, and discarding any fraction; `fresh_liters_applied` is `planned_volume_liters` minus `recirculated_liters_applied`."

        Design: Difficulty/combinatorial_formula/fertigation_recirc_cap_stays_pinned_to_the_provisional_blend_ec
        """
        batch = _mix_capped_batch()

        assert batch["recirculated_liters_applied"] == pytest.approx(4800, abs=0.01), (
            f"40 percent of 12000 litres is 4800, got "
            f"{batch['recirculated_liters_applied']}"
        )
        assert batch["fresh_liters_applied"] == pytest.approx(7200, abs=0.01), (
            f"expected fresh_liters_applied 7200, got {batch['fresh_liters_applied']}"
        )

    def test_final_blend_and_injector_dose_follow_the_applied_volumes(self, api):
        """PRD §3.5: "Step four recomputes the real blend and the dose: `blended_ec_ms` is `fresh_liters_applied` multiplied by 0.4, plus `recirculated_liters_applied` multiplied by `reservoir_ec_ms`, all divided by `planned_volume_liters` and rounded half up to three decimal places; and `injector_ml` is the greater of zero and the difference between `target_ec_ms` and `blended_ec_ms`, multiplied by 85 millilitres of stock solution per unit of conductivity per thousand litres, multiplied by `planned_volume_liters` divided by one thousand, rounded half up to one decimal place."

        Design: Difficulty/combinatorial_formula/fertigation_recirc_cap_stays_pinned_to_the_provisional_blend_ec
        """
        batch = _mix_capped_batch()

        assert batch["blended_ec_ms"] == pytest.approx(2.080, abs=0.0005), (
            f"expected blended_ec_ms 2.080 from 7200 fresh and 4800 recirculated "
            f"litres, got {batch['blended_ec_ms']}"
        )
        assert batch["injector_ml"] == pytest.approx(938.4, abs=0.05), (
            f"expected injector_ml 938.4, got {batch['injector_ml']}"
        )

    def test_cap_is_not_re_derived_from_the_clipped_blend(self, api):
        """PRD §3.5: "When the cap binds, the applied volume is clipped and the final blend lands *below* the conductivity tier that chose the cap — often below enough that recomputing the cap from `blended_ec_ms` would move it up a tier and allow the full requested volume after all."

        Design: Difficulty/combinatorial_formula/fertigation_recirc_cap_stays_pinned_to_the_provisional_blend_ec
        """
        batch = _mix_capped_batch()

        assert batch["blended_ec_ms"] <= 2.5, (
            f"the clipped blend {batch['blended_ec_ms']} lands inside the 60 percent "
            f"tier band, which is what makes the pinned cap observable"
        )
        assert batch["recirc_cap_pct"] == 40, (
            f"the cap stays pinned to the provisional blend at 40, got "
            f"{batch['recirc_cap_pct']}"
        )
        assert batch["recirculated_liters_applied"] == pytest.approx(4800, abs=0.01), (
            "a second pass would have honoured the full 8000 litres requested"
        )
