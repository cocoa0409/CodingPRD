"""Formulas whose terms interact: quality pricing, per-line rounding and the waterfall."""

from __future__ import annotations

import pytest

from test_helpers import (
    GOLDEN_FIGURES,
    TEST_DEFAULTS,
    assert_advance_conserved,
    assert_instant_equals,
    assert_grower_settlement,
    assert_lot_sample,
    assert_seed_lot,
    bagged_lot_state,
    certify_cleanout,
    compute_settlement,
    create_harvest_event_payload,
    draw_sample,
    expected_adjusted_price_cents,
    expected_price_adjustment_pct,
    get_success_data,
    harvested_lot_state,
    issue_tag,
    make_conditioning_manager_headers,
    make_program_admin_headers,
    make_settlement_accountant_headers,
    passed_lot_state,
    post_results,
    run_stage,
    validate_success,
)

LOW_MOISTURE_PCT = 13.0
LOW_QUALITY_RESULTS = {
    "germination_pct": 91.0,
    "purity_pct": 97.5,
    "inert_pct": 2.0,
    "weed_seed_count_per_kg": 6,
}


class TestPriceAdjustmentNonlinearQualityInteraction:
    def test_mixed_bonus_and_penalty_terms_combine_into_one_adjusted_price(self, api):
        """A germination bonus, a purity penalty, a weed penalty and moisture dockage all fold in.

        PRD: "The raw adjustment percentage is the germination adjustment plus the purity
        adjustment plus the weed penalty, minus the moisture dockage percentage; bonuses are
        additions and penalties are subtractions."

        Design: Difficulty/combinatorial_formula/price_adjustment_nonlinear_quality_interaction
        """
        state = passed_lot_state(
            api,
            harvest_overrides={"moisture_pct": LOW_MOISTURE_PCT},
            result_overrides=dict(LOW_QUALITY_RESULTS),
        )
        lot = state["seed_lot"]
        assert_seed_lot(lot)

        assert lot["intake_moisture_pct"] == pytest.approx(LOW_MOISTURE_PCT, abs=0.01)
        assert lot["adjusted_price_per_unit_cents"] == 1730

        adjustment_pct = expected_price_adjustment_pct(
            LOW_QUALITY_RESULTS["germination_pct"],
            LOW_QUALITY_RESULTS["purity_pct"],
            LOW_QUALITY_RESULTS["weed_seed_count_per_kg"],
            LOW_MOISTURE_PCT,
        )
        assert adjustment_pct == pytest.approx(-6.5, abs=0.01)
        assert lot["adjusted_price_per_unit_cents"] == expected_adjusted_price_cents(
            TEST_DEFAULTS["BASE_PRICE_PER_UNIT_CENTS"], adjustment_pct
        )

    def test_the_lot_passes_and_copies_the_penalised_findings_forward(self, api):
        """Penalties do not fail a lot: the verdict is a separate conjunction against the floors.

        PRD: "The sample passes when its germination percentage is at least the variety's
        `germination_min_pct`, *and* its purity percentage is at least the variety's
        `purity_min_pct`, *and* its weed seed count per kilogram is at most 30."

        Design: Difficulty/combinatorial_formula/price_adjustment_nonlinear_quality_interaction
        """
        state = passed_lot_state(
            api,
            harvest_overrides={"moisture_pct": LOW_MOISTURE_PCT},
            result_overrides=dict(LOW_QUALITY_RESULTS),
        )
        sample = state["sample"]
        assert_lot_sample(sample)
        assert sample["result"] == "PASS"

        lot = state["seed_lot"]
        assert lot["certification_status"] == "PASSED"
        assert lot["germination_pct"] == pytest.approx(LOW_QUALITY_RESULTS["germination_pct"], abs=0.01)
        assert lot["purity_pct"] == pytest.approx(LOW_QUALITY_RESULTS["purity_pct"], abs=0.01)
        assert lot["weed_seed_count_per_kg"] == LOW_QUALITY_RESULTS["weed_seed_count_per_kg"]
        assert_instant_equals(lot["germination_valid_until"], GOLDEN_FIGURES["GERMINATION_VALID_UNTIL"])
        assert lot["conditioning_status"] == "BAGGED"

    def test_moisture_term_reads_intake_moisture_and_not_the_sample(self, api):
        """The fourth term comes from the lot's inherited intake moisture, never from the lab.

        PRD: "A fourth term is a moisture dockage percentage, derived from the lot's
        `intake_moisture_pct` — the moisture measured at harvest intake, inherited by the lot
        and never re-derived from any later sample — as that intake moisture minus a 12.0
        percent base moisture, multiplied by a factor of 1.5, floored at zero."

        Design: Difficulty/combinatorial_formula/price_adjustment_nonlinear_quality_interaction
        """
        state = passed_lot_state(api, result_overrides=dict(LOW_QUALITY_RESULTS))
        lot = state["seed_lot"]

        # Intake moisture of 14.5 docks 3.75 points, where 13.0 would dock only 1.5.
        assert lot["intake_moisture_pct"] == pytest.approx(TEST_DEFAULTS["MOISTURE_PCT"], abs=0.01)
        assert lot["adjusted_price_per_unit_cents"] == 1688
        assert lot["adjusted_price_per_unit_cents"] != 1730
        assert expected_price_adjustment_pct(
            LOW_QUALITY_RESULTS["germination_pct"],
            LOW_QUALITY_RESULTS["purity_pct"],
            LOW_QUALITY_RESULTS["weed_seed_count_per_kg"],
            TEST_DEFAULTS["MOISTURE_PCT"],
        ) == pytest.approx(-8.75, abs=0.01)


def _two_tagged_lots_state(api):
    """One contract carrying two independently conditioned and tagged lots."""
    state = bagged_lot_state(api)
    contract_id = state["contract"]["id"]
    line_id = state["line"]["id"]

    # The machine was dirtied by the first load, so it is certified again for the same variety.
    certify_cleanout(
        api, state["equipment"]["id"], state["variety"]["id"], cleaned_at="2026-09-11T06:00:00Z"
    )
    second_event = get_success_data(
        api.create_harvest_event(
            create_harvest_event_payload(
                contract_id,
                state["equipment"]["id"],
                window_start="2026-09-11T08:00:00Z",
                window_end="2026-09-11T16:00:00Z",
                gross_weight_kg=28000.0,
                moisture_pct=14.5,
            ),
            make_conditioning_manager_headers(),
        )
    )
    lot_b_id = second_event["seed_lot_id"]

    run_stage(
        api, lot_b_id, line_id, "CLEANING", 25800.0,
        window_start="2026-09-13T11:00:00Z", window_end="2026-09-13T15:00:00Z", input_kg=28000.0,
    )
    run_stage(
        api, lot_b_id, line_id, "SIZING", 24000.0,
        window_start="2026-09-13T16:00:00Z", window_end="2026-09-13T20:00:00Z", input_kg=25800.0,
    )
    run_stage(
        api, lot_b_id, line_id, "BAGGING", 23501.25,
        window_start="2026-09-13T21:00:00Z", window_end="2026-09-13T23:00:00Z", input_kg=24000.0,
    )

    lot_a_id = state["seed_lot"]["id"]
    for lot_id, bag_count in ((lot_a_id, 1380), (lot_b_id, 940)):
        sample = draw_sample(api, lot_id)
        post_results(api, sample["id"])
        issue_tag(api, lot_id, sample["id"], bag_count=bag_count)

    state["seed_lot"] = get_success_data(api.get_seed_lot(lot_a_id, make_conditioning_manager_headers()))
    state["second_seed_lot"] = get_success_data(api.get_seed_lot(lot_b_id, make_conditioning_manager_headers()))
    state["contract"] = get_success_data(
        api.get_production_contract(contract_id, make_program_admin_headers())
    )
    return state


class TestSettlementPerLineRoundingBeforeSummation:
    def test_each_line_is_rounded_to_cents_before_the_lines_are_summed(self, api):
        """Two lines each ending in half a cent must round up individually, not once at the end.

        PRD: "Each line is rounded to whole cents *first*, and only then are the rounded line
        values summed."

        Design: Difficulty/combinatorial_formula/settlement_per_line_rounding_before_summation
        """
        state = _two_tagged_lots_state(api)
        assert state["seed_lot"]["final_clean_units"] == pytest.approx(1380.05, abs=0.01)
        assert state["second_seed_lot"]["final_clean_units"] == pytest.approx(940.05, abs=0.01)
        assert state["seed_lot"]["adjusted_price_per_unit_cents"] == 1929
        assert state["second_seed_lot"]["adjusted_price_per_unit_cents"] == 1929

        settlement = compute_settlement(api, state["contract"]["id"])
        assert_grower_settlement(settlement)

        assert settlement["line_count"] == 2
        assert settlement["settled_units_total"] == pytest.approx(2320.10, abs=0.01)
        assert settlement["gross_payable_cents"] == 4475472
        assert settlement["gross_payable_cents"] != 4475473
        assert settlement["conditioning_charges_cents"] == 510422

    def test_waterfall_runs_on_the_already_rounded_totals(self, api):
        """The provisional net, the cap tier and the recovery all read the rounded sums.

        PRD: "Step one computes `provisional_net_cents` as `gross_payable_cents` minus
        `conditioning_charges_cents`; a negative provisional net is refused with
        `ERR_NET_PAYABLE_NEGATIVE`."

        Design: Difficulty/combinatorial_formula/settlement_per_line_rounding_before_summation
        """
        state = _two_tagged_lots_state(api)
        settlement = compute_settlement(api, state["contract"]["id"])

        assert settlement["provisional_net_cents"] == 3965050
        assert settlement["recovery_cap_pct"] == pytest.approx(60.0, abs=0.01)
        assert settlement["advance_recovery_cents"] == 1200000
        assert settlement["net_payable_cents"] == 2765050
        assert settlement["status"] == "COMPUTED"
        assert settlement["quality_hold"] is False


def _high_advance_tagged_state(api):
    """A contract carrying an 1,800,000 cent advance and one lot bagged at 30720.0 kg."""
    state = harvested_lot_state(
        api,
        advance_total_cents=1800000,
        harvest_overrides={"gross_weight_kg": 36000.0, "moisture_pct": 14.5},
    )
    lot_id = state["seed_lot"]["id"]
    line_id = state["line"]["id"]

    run_stage(
        api, lot_id, line_id, "CLEANING", 33000.0,
        window_start=TEST_DEFAULTS["CLEANING_WINDOW_START"],
        window_end=TEST_DEFAULTS["CLEANING_WINDOW_END"],
        input_kg=36000.0,
    )
    run_stage(
        api, lot_id, line_id, "SIZING", 31000.0,
        window_start=TEST_DEFAULTS["SIZING_WINDOW_START"],
        window_end=TEST_DEFAULTS["SIZING_WINDOW_END"],
        input_kg=33000.0,
    )
    run_stage(
        api, lot_id, line_id, "BAGGING", 30720.0,
        window_start=TEST_DEFAULTS["BAGGING_WINDOW_START"],
        window_end=TEST_DEFAULTS["BAGGING_WINDOW_END"],
        input_kg=31000.0,
    )

    sample = draw_sample(api, lot_id)
    post_results(api, sample["id"])
    state["sample"] = sample
    state["tag"] = issue_tag(api, lot_id, sample["id"], bag_count=1228)
    state["seed_lot"] = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
    state["contract"] = get_success_data(
        api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
    )
    return state


class TestAdvanceRecoveryCapEvaluationOrder:
    def test_cap_is_keyed_on_the_provisional_net_and_applied_before_the_net_payable(self, api):
        """The tier is selected from the provisional net, then the capped recovery is subtracted.

        PRD: "Step two selects `recovery_cap_pct` from a tier table keyed on
        `provisional_net_cents` and on nothing else — not on the net payable, and not on the
        gross payable."

        Design: Difficulty/combinatorial_formula/advance_recovery_cap_evaluation_order
        """
        state = _high_advance_tagged_state(api)
        lot = state["seed_lot"]
        assert lot["final_clean_units"] == pytest.approx(1228.80, abs=0.01)
        assert lot["bag_count"] == 1228
        assert lot["dockage_pct"] == pytest.approx(14.67, abs=0.01)

        settlement = compute_settlement(api, state["contract"]["id"])
        assert_grower_settlement(settlement)

        assert settlement["gross_payable_cents"] == 2370355
        assert settlement["conditioning_charges_cents"] == 270336
        assert settlement["provisional_net_cents"] == 2100019
        assert settlement["recovery_cap_pct"] == pytest.approx(60.0, abs=0.01)
        assert settlement["advance_recovery_cents"] == 1260011
        assert settlement["net_payable_cents"] == 840008
        assert settlement["net_payable_cents"] != 1365012

    def test_approval_books_only_the_capped_recovery_against_the_advance(self, api):
        """The outstanding advance falls by the capped recovery, not by the whole advance.

        PRD: "On success the settlement moves `COMPUTED → APPROVED`, `approved_by_user_id` is
        set from the approving accountant's identifier, the settlement's
        `advance_recovery_cents` is subtracted from the contract's `advance_outstanding_cents`,
        the contract advances `HARVESTED → SETTLED`, the settlement's `version` increments by 1
        and the contract's `version` increments by 1."

        Design: Difficulty/combinatorial_formula/advance_recovery_cap_evaluation_order
        """
        state = _high_advance_tagged_state(api)
        settlement = compute_settlement(api, state["contract"]["id"], accountant_user_id="acct-1")

        approved = validate_success(
            api.approve_settlement(settlement["id"], {}, make_settlement_accountant_headers("acct-2")),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "acct-2"
        assert approved["advance_recovery_cents"] == 1260011

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["advance_outstanding_cents"] == 539989
        assert contract["status"] == "SETTLED"
        assert_advance_conserved(contract, [approved])
