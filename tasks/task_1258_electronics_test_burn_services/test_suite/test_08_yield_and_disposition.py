"""Dual-variant yield reporting, the nested disposition branch lattice, the
inclusive ship threshold, the rework loop, and the one-PENDING-review aggregate
gate (PRD §3.4, §3.6)."""
import pytest

from test_helpers import (
    assert_lot_tally_invariant,
    authorize_retest,
    create_lot_with_units,
    record_hard_fail,
    record_pass,
    record_soft_fail,
    setup_awaiting_disposition_lot,
    setup_in_test_lot,
    setup_released_program_with_fixture,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ENG1, ENG2, OPS, QE, get_pending_review_id, list_reviews_for_lot


def _build_divergence_lot(api):
    """Lot of 4: SN-1 pass, SN-2 pass, SN-3 soft-fail retested to pass,
    SN-4 hard-fail — identical data read two ways by the yield variants."""
    ctx = setup_in_test_lot(quantity=4, part_number="PN-100")
    fixture_id = ctx["fixture"]["id"]
    u1, u2, u3, u4 = ctx["units"]
    record_pass(u1, fixture_id, ENG1)
    record_pass(u2, fixture_id, ENG1)
    record_soft_fail(u3, fixture_id, ENG1)
    record_hard_fail(u4, fixture_id, ENG1)
    authorize_retest(u3["id"], reason="marginal socket contact", engineer_headers=ENG2)
    record_pass(u3, fixture_id, ENG1)
    return ctx


class TestLotYieldDualVariants:
    def test_first_pass_and_final_yield_values(self, api):
        """PRD §3.6: "The `first_pass_yield` is the first-pass quality measure: its
        numerator counts the units whose first tally-effective result — the
        insertion at index 1 — passed, and its denominator counts only the units
        that have at least one tally-effective result at all; it is reported as zero
        when no unit has been tested."
        PRD §3.6: "The `final_yield` is the shippable quality measure after retests:
        its numerator counts the units currently standing `PASSED`, and its
        denominator is the lot's full `quantity`."

        Design: Difficulty/dual_variant_calc/lot_yield_first_pass_vs_final_diverge
        """
        ctx = _build_divergence_lot(api)
        report = validate_success(api.get_yield_report(ctx["lot"]["id"], ENG1), 200)
        # 2 first-insertion passes over 4 tested units.
        assert report["first_pass_yield"] == pytest.approx(0.5, abs=1e-9)
        # 3 currently PASSED over the full quantity of 4.
        assert report["final_yield"] == pytest.approx(0.75, abs=1e-9)

    def test_variants_diverge_and_tallies_and_bin_histogram(self, api):
        """PRD §3.6: "Because the two measures differ in both numerator and
        denominator, identical lot data produces different numbers whenever any unit
        failed its first insertion."
        PRD §3.6: "The report for a lot — recomputed at completion of test and again
        on every read of the yield report — carries the `lot_id`, both yield
        variants, the tallies `units_registered`, `units_passed`, `units_failed`,
        and `units_untested`, the `retested_unit_count`, the `escape_count`, a
        `bin_counts` histogram of effective results by bin, and the current
        `suggested_disposition`."

        Design: Difficulty/dual_variant_calc/lot_yield_first_pass_vs_final_diverge
        """
        ctx = _build_divergence_lot(api)
        report = validate_success(api.get_yield_report(ctx["lot"]["id"], ENG1), 200)
        assert report["first_pass_yield"] != pytest.approx(
            report["final_yield"], abs=1e-9
        ), "identical lot data must produce two different numbers here"
        assert report["units_registered"] == 4
        assert report["units_passed"] == 3
        assert report["units_failed"] == 1
        assert report["units_untested"] == 0
        assert report["retested_unit_count"] == 1
        assert report["escape_count"] == 0
        # Tally-effective results: bin 1 x3 (SN-1, SN-2, SN-3 retest), bin 2 x1,
        # bin 9 x1.
        assert report["bin_counts"] == {"1": 3, "2": 1, "9": 1}


def _complete_three_lots(api):
    """One released program; Lot A (4): 3 first-pass + 1 soft-fail retested to
    pass; Lot B (4): 2 first-pass + 2 hard-fail; Lot C (4): 1 pass + 3 hard-fail.
    Returns (ctx, lot_a, lot_b, lot_c) with all three lots AWAITING_DISPOSITION."""
    ctx = setup_released_program_with_fixture(part_number="PN-300")
    fixture_id = ctx["fixture"]["id"]

    def build_lot(serial_prefix, bins, retest_index=None):
        lot, units = create_lot_with_units(ctx, 4, serial_prefix=serial_prefix)
        validate_success(api.enqueue_lot(lot["id"], OPS), 200)
        validate_success(api.start_test_lot(lot["id"], OPS), 200)
        for unit, bin_code in zip(units, bins):
            if bin_code == 1:
                record_pass(unit, fixture_id, ENG1)
            elif bin_code == 2:
                record_soft_fail(unit, fixture_id, ENG1)
            else:
                record_hard_fail(unit, fixture_id, ENG1)
        if retest_index is not None:
            authorize_retest(units[retest_index]["id"], reason="socket retry",
                             engineer_headers=ENG2)
            record_pass(units[retest_index], fixture_id, ENG1)
        return validate_success(api.complete_test_lot(lot["id"], OPS), 200)

    lot_a = build_lot("A", [1, 1, 1, 2], retest_index=3)
    lot_b = build_lot("B", [1, 1, 9, 9])
    lot_c = build_lot("C", [1, 9, 9, 9])
    return ctx, lot_a, lot_b, lot_c


class TestDispositionBranchLattice:

    def test_ship_branch_at_exact_thresholds(self, api):
        """PRD §3.6: "Otherwise, when the first-pass yield is at least 0.75, the
        escape count is exactly zero, and the retest rate — `retested_unit_count`
        divided by `quantity` — is at most 0.25, the suggestion is `SHIP`."
        PRD §2.7: "Threshold comparisons — the disposition gates in particular —
        are always evaluated against the exact fraction before any serialization
        rounding, so a first-pass yield of exactly three quarters satisfies an
        at-least-0.75 threshold."
        PRD §3.4: "At that moment the system computes the lot's
        `suggested_disposition` per §3.6, and whenever the suggestion is anything
        other than `SHIP` the system automatically opens a lot disposition review in
        `PENDING` status with a snapshot of that suggestion."

        Design: Difficulty/combinatorial_formula/disposition_suggestion_three_branch_nested
        """
        _ctx, lot_a, _lot_b, _lot_c = _complete_three_lots(api)
        # FPY 3/4 == 0.75 >= 0.75, escapes 0, retest_rate 1/4 == 0.25 <= 0.25 —
        # both thresholds inclusive.
        assert lot_a["suggested_disposition"] == "SHIP"
        reviews = list_reviews_for_lot(lot_a["id"])
        assert len(reviews) == 0, "a SHIP suggestion auto-creates no review"

    def test_mrb_and_scrap_review_branches(self, api):
        """PRD §3.6: "Otherwise, when the first-pass yield is below 0.50 — fewer
        than half of tested units passing on their first insertion — the suggestion
        is also `SCRAP_REVIEW`."
        PRD §3.6: "Every other combination falls through to `MRB_REVIEW`."
        PRD §3.6: "The new review snapshots the lot's current
        `suggested_disposition` at creation, starts `PENDING`, and has `decision`,
        `rationale`, and `decided_by_user_id` all null. Reviews are also opened
        automatically: completing test with any non-`SHIP` suggestion creates one,
        and an RMA escape containment creates another."

        Design: Difficulty/combinatorial_formula/disposition_suggestion_three_branch_nested
        """
        _ctx, _lot_a, lot_b, lot_c = _complete_three_lots(api)
        # Lot B: FPY 0.5 — below the SHIP band, not below 0.50.
        assert lot_b["suggested_disposition"] == "MRB_REVIEW"
        # Lot C: FPY 0.25 < 0.50.
        assert lot_c["suggested_disposition"] == "SCRAP_REVIEW"

        reviews_b = list_reviews_for_lot(lot_b["id"])
        assert len(reviews_b) == 1
        assert reviews_b[0]["status"] == "PENDING"
        assert reviews_b[0]["suggested_disposition"] == "MRB_REVIEW", (
            "the auto-created review snapshots the lot's suggestion"
        )
        reviews_c = list_reviews_for_lot(lot_c["id"])
        assert len(reviews_c) == 1
        assert reviews_c[0]["suggested_disposition"] == "SCRAP_REVIEW"


class TestShipThresholdInclusive:
    def _build_ok_and_no_lots(self, api):
        """Lot OK: FPY exactly 3/4, retest rate 1/4, no escapes. Lot NO: FPY 1/2."""
        _ctx, lot_a, lot_b, _lot_c = _complete_three_lots(api)
        return lot_a, lot_b

    def test_ship_at_exact_fpy_threshold_succeeds(self, api):
        """PRD §2.7: "Threshold comparisons — the disposition gates in particular —
        are always evaluated against the exact fraction before any serialization
        rounding, so a first-pass yield of exactly three quarters satisfies an
        at-least-0.75 threshold."
        PRD §3.4: "Shipping moves the lot from `AWAITING_DISPOSITION` to `SHIPPED`,
        but a direct ship is permitted only when the lot's `suggested_disposition`
        is `SHIP` and no `PENDING` disposition review exists for the lot — otherwise
        the request is rejected with `ERR_DISPOSITION_REVIEW_REQUIRED` and the lot
        must instead pass through the MRB decision described in §3.6."

        Design: Difficulty/boundary_precision_check/ship_yield_threshold_inclusive
        """
        lot_ok, _lot_no = self._build_ok_and_no_lots(api)
        # FPY exactly 3/4 (inclusive), retest_rate exactly 1/4 (at most 0.25),
        # escapes exactly 0: every conjunct sits on its own boundary.
        assert lot_ok["suggested_disposition"] == "SHIP"
        shipped = validate_success(api.ship_lot(lot_ok["id"], OPS), 200)
        assert shipped["status"] == "SHIPPED"

    def test_ship_below_threshold_rejected(self, api):
        """PRD §3.4: "Shipping moves the lot from `AWAITING_DISPOSITION` to
        `SHIPPED`, but a direct ship is permitted only when the lot's
        `suggested_disposition` is `SHIP` and no `PENDING` disposition review exists
        for the lot — otherwise the request is rejected with
        `ERR_DISPOSITION_REVIEW_REQUIRED` and the lot must instead pass through the
        MRB decision described in §3.6."

        Design: Difficulty/boundary_precision_check/ship_yield_threshold_inclusive
        """
        _lot_ok, lot_no = self._build_ok_and_no_lots(api)
        # FPY 2/4 == 0.5 is below the 0.75 SHIP band.
        assert lot_no["suggested_disposition"] == "MRB_REVIEW"
        res = api.ship_lot(lot_no["id"], OPS)
        validate_error(res, "ERR_DISPOSITION_REVIEW_REQUIRED", expected_status=409)
        lot_after = validate_success(api.get_lot(lot_no["id"], OPS), 200)
        assert lot_after["status"] == "AWAITING_DISPOSITION"


class TestReworkLoop:
    def _setup_rework_ready(self, api):
        """Lot of 4: 2 pass, 2 hard-fail -> AWAITING_DISPOSITION with an
        auto-created PENDING MRB_REVIEW review."""
        ctx = setup_awaiting_disposition_lot([1, 1, 9, 9], part_number="PN-600")
        review_id = get_pending_review_id(ctx["lot"]["id"])
        assert review_id, "expected an auto-created PENDING review"
        return ctx, review_id

    def test_rework_decision_resets_lot_and_units(self, api):
        """PRD §3.6: "Rework is a full reset of the lot's test genealogy. Every unit
        of the lot returns to `UNTESTED` with `current_bin` null and `retest_count`
        reset to zero. Every non-voided test result of the lot is marked
        `excluded_from_tally`, so excluded rows no longer drive unit state or
        tallies — though they remain recorded history. The lot's tallies are
        recomputed with `units_untested` equal to `quantity`, ready for the lot to
        cycle through the queue, test, and disposition stages again; a lot may loop
        this way repeatedly."
        PRD §3.6: "For a lot in `AWAITING_DISPOSITION`: `SHIP` moves it to
        `SHIPPED`, `SCRAP` moves it to `SCRAPPED`, and `REWORK` loops it back to
        `QUEUED`."

        Design: Difficulty/non_linear_state_machine/lot_rework_loop_returns_to_queued
        """
        ctx, review_id = self._setup_rework_ready(api)
        decided = validate_success(
            api.decide_lot_disposition_review(
                review_id,
                {"decision": "REWORK", "rationale": "reflow solder and retest"},
                QE,
            ),
            200,
        )
        assert decided["status"] == "DECIDED"
        lot_mid = validate_success(api.get_lot(ctx["lot"]["id"], OPS), 200)
        assert lot_mid["status"] == "QUEUED"
        assert lot_mid["units_untested"] == 4, "units reset to UNTESTED"
        assert_lot_tally_invariant(lot_mid)
        for unit in ctx["units"]:
            unit_after = validate_success(api.get_unit(unit["id"], QE), 200)
            assert unit_after["test_status"] == "UNTESTED"
            assert unit_after["current_bin"] is None
            assert unit_after["retest_count"] == 0, "history reset"

    def test_reworked_lot_retraverses_pipeline_to_shipped(self, api):
        """PRD §3.6: "The lot's tallies are recomputed with `units_untested` equal
        to `quantity`, ready for the lot to cycle through the queue, test, and
        disposition stages again; a lot may loop this way repeatedly."
        PRD §3.6: "Otherwise, when the first-pass yield is at least 0.75, the escape
        count is exactly zero, and the retest rate — `retested_unit_count` divided
        by `quantity` — is at most 0.25, the suggestion is `SHIP`."

        Design: Difficulty/non_linear_state_machine/lot_rework_loop_returns_to_queued
        """
        ctx, review_id = self._setup_rework_ready(api)
        validate_success(
            api.decide_lot_disposition_review(
                review_id,
                {"decision": "REWORK", "rationale": "reflow solder and retest"},
                QE,
            ),
            200,
        )
        # Second pass: QUEUED -> IN_TEST -> all four pass -> AWAITING_DISPOSITION.
        validate_success(api.start_test_lot(ctx["lot"]["id"], OPS), 200)
        for unit in ctx["units"]:
            record_pass(unit, ctx["fixture"]["id"], ENG1)
        completed = validate_success(api.complete_test_lot(ctx["lot"]["id"], OPS), 200)
        assert completed["suggested_disposition"] == "SHIP", (
            "FPY 1.0, retested 0, escapes 0 after the reset"
        )
        shipped = validate_success(api.ship_lot(ctx["lot"]["id"], OPS), 200)
        assert shipped["status"] == "SHIPPED"


class TestReviewAggregateGate:
    def test_second_pending_review_rejected(self, api):
        """PRD §3.6: "Only one `PENDING` review may exist for a lot at a time —
        opening a second is rejected with `ERR_REVIEW_PENDING`."
        PRD §3.4: "At that moment the system computes the lot's
        `suggested_disposition` per §3.6, and whenever the suggestion is anything
        other than `SHIP` the system automatically opens a lot disposition review in
        `PENDING` status with a snapshot of that suggestion."

        Design: Corner/validations/second_pending_review_rejected
        """
        ctx = setup_awaiting_disposition_lot(
            [1, 9], part_number="PN-224", max_retests_per_unit=1
        )
        assert ctx["lot"]["suggested_disposition"] == "MRB_REVIEW"
        assert get_pending_review_id(ctx["lot"]["id"]), (
            "complete-test auto-created a PENDING review"
        )
        res = api.create_lot_disposition_review({"lot_id": ctx["lot"]["id"]}, QE)
        validate_error(res, "ERR_REVIEW_PENDING", expected_status=409)
