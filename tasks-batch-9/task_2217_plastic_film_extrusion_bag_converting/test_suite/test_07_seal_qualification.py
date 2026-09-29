"""Seal qualification: the two disagreeing variants and the three-way fork."""
import pytest

from test_helpers import (
    CONVERTER,
    EXTRUDER,
    ApiErrorId,
    ISSUING_MANAGER,
    append_seal_specimens,
    get_success_data,
    setup_bag_lot_testing,
    validate_error,
    validate_success,
)

FAILING_RETEST_PANEL = ((1, 25.0), (2, 23.0), (3, 18.0), (3, 17.0))
CONDITIONAL_PANEL = ((1, 22.0), (2, 22.0), (3, 19.0))
SHORT_PANEL = ((1, 26.0), (2, 25.0))


class TestProvisionalPassVersusFinalFail:
    """A worse retest is invisible to the provisional variant but decides the fork."""

    def test_provisional_variant_reads_first_passes_only(self, api):
        """The 18.0 first pass counts; the 17.0 retest does not.

        PRD: "The *provisional* variant is recomputed on every append and looks
        only at bottom-seal specimens whose `is_retest` is false — first passes
        only, retests entirely ignored."

        Design: Difficulty/dual_variant_calc/seal_provisional_pass_versus_final_fail_forks_lot_to_failed
        """
        world = setup_bag_lot_testing(api, specimens=FAILING_RETEST_PANEL)
        lot = world["bag_lot"]

        assert lot["seal_provisional_mean_n"] == pytest.approx(22.00, abs=0.01)
        assert lot["seal_provisional_verdict"] == "PASS"
        assert lot["bag_unit_weight_kg"] == pytest.approx(0.012520, abs=0.01)

    def test_specimen_log_derives_attempt_and_retest_flags(self, api):
        """The fourth append is attempt two on specimen index three.

        PRD: "The server derives the row's `attempt` as one plus the number of
        earlier specimens sharing the same `specimen_index`, derives `is_retest`
        as true exactly when that `attempt` is greater than one".

        Design: Difficulty/dual_variant_calc/seal_provisional_pass_versus_final_fail_forks_lot_to_failed
        """
        world = setup_bag_lot_testing(api, specimens=FAILING_RETEST_PANEL)
        specimens = world["bag_lot"]["seal_specimens"]

        assert [row["attempt"] for row in specimens] == [1, 1, 1, 2]
        assert [row["is_retest"] for row in specimens] == [False, False, False, True]

    def test_final_variant_reads_the_superseding_panel_and_fails_the_lot(self, api):
        """The 17.0 retest supersedes 18.0 and drops the lot below every floor.

        PRD: "the final verdict may be `PASS` where the provisional said `FAIL` —
        a good retest replaced a weak specimen — or `FAIL` where the provisional
        said `PASS`, when the retest came out worse."

        Design: Difficulty/dual_variant_calc/seal_provisional_pass_versus_final_fail_forks_lot_to_failed
        """
        world = setup_bag_lot_testing(api, specimens=FAILING_RETEST_PANEL)
        finalized = validate_success(
            api.finalize_seal_tests(world["bag_lot"]["id"], ISSUING_MANAGER), 200)

        assert finalized["seal_final_min_n"] == pytest.approx(17.00, abs=0.01)
        assert finalized["seal_final_mean_n"] == pytest.approx(21.67, abs=0.01)
        assert finalized["seal_final_verdict"] == "FAIL"
        assert finalized["status"] == "FAILED"

    def test_failed_branch_converts_the_whole_lot_into_pool_mass(self, api):
        """Every bag is scrapped and booked as lot scrap.

        PRD: "`bag_count_scrapped` is set equal to `bag_count_produced` and
        `bag_count_unpacked` is set to zero, and the entire lot is converted into
        pool mass by booking a regrind transaction".

        Design: Difficulty/dual_variant_calc/seal_provisional_pass_versus_final_fail_forks_lot_to_failed
        """
        world = setup_bag_lot_testing(api, specimens=FAILING_RETEST_PANEL)
        finalized = validate_success(
            api.finalize_seal_tests(world["bag_lot"]["id"], ISSUING_MANAGER), 200)

        assert finalized["bag_count_scrapped"] == 46000
        assert finalized["bag_count_unpacked"] == 0

        pool = get_success_data(api.get_regrind_pool(world["pool"]["id"], EXTRUDER))
        assert pool["generation_count"] == 2
        assert pool["cumulative_in_kg"] == pytest.approx(587.920, abs=0.01)
        assert pool["available_kg"] == pytest.approx(587.920, abs=0.01)
        assert pool["embedded_pcr_pct"] == pytest.approx(0.000, abs=0.01)


class TestConditionalBranchOfTheFork:
    """The middle branch keeps the lot packable but tightens its release gate."""

    def test_provisional_fail_can_still_finalize_conditional(self, api):
        """A 21.00 mean fails the provisional check yet clears the middle band.

        PRD: "otherwise `CONDITIONAL` when `seal_final_min_n` is at least the
        conditional floor **and** `seal_final_mean_n` is at least the conditional
        mean; otherwise `FAIL`."

        Design: Difficulty/non_linear_state_machine/bag_lot_three_way_fork_conditional_branch_tightens_release_gate
        """
        world = setup_bag_lot_testing(api, specimens=CONDITIONAL_PANEL)
        assert world["bag_lot"]["seal_provisional_mean_n"] == pytest.approx(21.00,
                                                                           abs=0.01)
        assert world["bag_lot"]["seal_provisional_verdict"] == "FAIL"

        finalized = validate_success(
            api.finalize_seal_tests(world["bag_lot"]["id"], ISSUING_MANAGER), 200)
        assert finalized["seal_final_min_n"] == pytest.approx(19.00, abs=0.01)
        assert finalized["seal_final_mean_n"] == pytest.approx(21.00, abs=0.01)
        assert finalized["seal_final_verdict"] == "CONDITIONAL"
        assert finalized["status"] == "CONDITIONAL"

    def test_conditional_branch_scraps_nothing(self, api):
        """Unlike the FAIL branch, the bags survive and the pool is untouched.

        PRD: "On a final verdict of `CONDITIONAL`, the lot moves `TESTING →
        CONDITIONAL` with the same three fields written; the lot remains packable
        and shippable, but its release gate is tightened".

        Design: Difficulty/non_linear_state_machine/bag_lot_three_way_fork_conditional_branch_tightens_release_gate
        """
        world = setup_bag_lot_testing(api, specimens=CONDITIONAL_PANEL)
        finalized = validate_success(
            api.finalize_seal_tests(world["bag_lot"]["id"], ISSUING_MANAGER), 200)

        assert finalized["bag_count_scrapped"] == 0
        assert finalized["bag_count_unpacked"] == 46000
        assert finalized["count_accuracy_pct"] == pytest.approx(99.99, abs=0.01)
        assert finalized["count_accuracy_conforming"] is True

        pool = get_success_data(api.get_regrind_pool(world["pool"]["id"], EXTRUDER))
        assert pool["generation_count"] == 1
        assert pool["cumulative_in_kg"] == pytest.approx(12.000, abs=0.01)


class TestSealPanelMinimumSize:
    """Three distinct specimen indices is the floor for both variants."""

    def test_two_specimens_leave_the_provisional_variant_pending(self, api):
        """One index short, nothing is published.

        PRD: "While fewer than three such first-pass specimens exist,
        `seal_provisional_mean_n` is null and `seal_provisional_verdict` reads
        `PENDING`."

        Design: Difficulty/boundary_precision_check/seal_panel_size_at_minimum_versus_one_below
        """
        world = setup_bag_lot_testing(api, specimens=SHORT_PANEL)
        lot = world["bag_lot"]

        assert lot["status"] == "TESTING"
        assert lot["seal_provisional_verdict"] == "PENDING"
        assert lot["seal_provisional_mean_n"] is None

    def test_finalization_refused_one_index_short(self, api):
        """Finalizing a two-index panel is refused outright.

        PRD: "If that panel holds fewer than three distinct specimen indices,
        finalization is refused with `ERR_INSUFFICIENT_SEAL_PANEL`."

        Design: Difficulty/boundary_precision_check/seal_panel_size_at_minimum_versus_one_below
        """
        world = setup_bag_lot_testing(api, specimens=SHORT_PANEL)
        validate_error(api.finalize_seal_tests(world["bag_lot"]["id"], ISSUING_MANAGER),
                       ApiErrorId.ERR_INSUFFICIENT_SEAL_PANEL, 422)

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["status"] == "TESTING"
        assert lot["seal_provisional_verdict"] == "PENDING"
        assert lot["seal_provisional_mean_n"] is None

    def test_third_specimen_unlocks_both_variants(self, api):
        """At exactly three indices the panel qualifies the lot.

        PRD: "`seal_final_verdict` is `PASS` when `seal_final_min_n` is at least
        the pass floor **and** `seal_final_mean_n` is at least the raw
        specification".

        Design: Difficulty/boundary_precision_check/seal_panel_size_at_minimum_versus_one_below
        """
        world = setup_bag_lot_testing(api, specimens=SHORT_PANEL)
        validate_error(api.finalize_seal_tests(world["bag_lot"]["id"], ISSUING_MANAGER),
                       ApiErrorId.ERR_INSUFFICIENT_SEAL_PANEL, 422)
        append_seal_specimens(api, world["bag_lot"]["id"], ((3, 24.0),))

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["seal_provisional_mean_n"] == pytest.approx(25.00, abs=0.01)
        assert lot["seal_provisional_verdict"] == "PASS"

        finalized = validate_success(
            api.finalize_seal_tests(world["bag_lot"]["id"], ISSUING_MANAGER), 200)
        assert finalized["seal_final_min_n"] == pytest.approx(24.00, abs=0.01)
        assert finalized["seal_final_mean_n"] == pytest.approx(25.00, abs=0.01)
        assert finalized["seal_final_verdict"] == "PASS"
        assert finalized["status"] == "QUALIFIED"
        assert finalized["bag_count_unpacked"] == 46000
