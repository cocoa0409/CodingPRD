"""Result voids and the unit tally projection: compensating record/void pairs,
replay after voiding a retest, and voided rows leaving the yield input set
(PRD §3.5, §3.6)."""
import pytest

from test_helpers import (
    assert_lot_tally_invariant,
    authorize_retest,
    record_pass,
    record_soft_fail,
    setup_in_test_lot,
    validate_success,
)
from test_helpers.fixtures import ENG1, ENG2, QE


class TestRecordVoidInvariant:
    def test_tallies_before_and_after_compensating_void(self, api):
        """PRD §3.5: "Every insertion recomputes this projection for the unit and
        recomputes the lot's tallies — `units_untested`, `units_passed`, and
        `units_failed` count the units in each status, and the three always sum to
        the lot's `quantity`, before and after any record, void, rework, or escape
        mutation."
        PRD §3.5: "The void flips the result's `voided` flag to true and replays the
        unit's remaining effective results: the unit's `test_status` and
        `current_bin` are recomputed from the new latest result, or return to
        `UNTESTED` and null when none remain."

        Design: Difficulty/compensating_invariant/lot_unit_tally_record_void_invariant
        """
        ctx = setup_in_test_lot(quantity=3, part_number="PN-161")
        fixture_id = ctx["fixture"]["id"]
        t1, t2, _t3 = ctx["units"]
        record_pass(t1, fixture_id, ENG1)
        r2 = record_soft_fail(t2, fixture_id, ENG1)

        lot_mid = validate_success(api.get_lot(ctx["lot"]["id"], QE), 200)
        assert lot_mid["units_passed"] == 1
        assert lot_mid["units_failed"] == 1
        assert lot_mid["units_untested"] == 1
        assert_lot_tally_invariant(lot_mid)

        validate_success(
            api.void_test_result(r2["id"], {"reason": "mis-keyed bin entry"}, QE), 200
        )
        lot_after = validate_success(api.get_lot(ctx["lot"]["id"], QE), 200)
        assert lot_after["units_passed"] == 1
        assert lot_after["units_failed"] == 0
        assert lot_after["units_untested"] == 2, (
            "the void returned the tallies to their exact pre-record values for unit T-2"
        )
        assert_lot_tally_invariant(lot_after)

    def test_void_returns_unit_to_untested_and_row_stays_queryable(self, api):
        """PRD §3.5: "The void flips the result's `voided` flag to true and replays
        the unit's remaining effective results: the unit's `test_status` and
        `current_bin` are recomputed from the new latest result, or return to
        `UNTESTED` and null when none remain."
        PRD §2.4: "A **TestResult** is the deliberate exception: as an immutable
        event record it carries only `id` and `created_at`. Both `updated_at` and
        `version` are absent from a test result, even after the result is later
        voided."

        Design: Difficulty/compensating_invariant/lot_unit_tally_record_void_invariant
        """
        ctx = setup_in_test_lot(quantity=3, part_number="PN-161")
        fixture_id = ctx["fixture"]["id"]
        t1, t2, _t3 = ctx["units"]
        record_pass(t1, fixture_id, ENG1)
        r2 = record_soft_fail(t2, fixture_id, ENG1)

        voided = validate_success(
            api.void_test_result(r2["id"], {"reason": "mis-keyed bin entry"}, QE), 200
        )
        assert voided["voided"] is True
        t2_after = validate_success(api.get_unit(t2["id"], QE), 200)
        assert t2_after["test_status"] == "UNTESTED", (
            "replay over the remaining non-voided results is empty"
        )
        assert t2_after["current_bin"] is None
        # The append-only row remains queryable after the void.
        fetched = validate_success(api.get_test_result(r2["id"], QE), 200)
        assert fetched["voided"] is True
        assert "updated_at" not in fetched and "version" not in fetched


class TestReplayAfterVoid:
    def test_yield_report_excludes_voided_results(self, api):
        """PRD §3.6: "The report for a lot — recomputed at completion of test and
        again on every read of the yield report — carries the `lot_id`, both yield
        variants, the tallies `units_registered`, `units_passed`, `units_failed`,
        and `units_untested`, the `retested_unit_count`, the `escape_count`, a
        `bin_counts` histogram of effective results by bin, and the current
        `suggested_disposition`."
        PRD §3.6: "The `first_pass_yield` is the first-pass quality measure: its
        numerator counts the units whose first tally-effective result — the
        insertion at index 1 — passed, and its denominator counts only the units
        that have at least one tally-effective result at all; it is reported as zero
        when no unit has been tested."
        PRD §3.5: "Its `insertion_index` is assigned chronologically as the
        one-based count of the unit's tally-effective results including this one —
        so a unit's first effective insertion is index 1."

        Design: Corner/calculations/yield_report_excludes_voided_results
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-212")
        unit = ctx["units"][0]
        fixture_id = ctx["fixture"]["id"]
        r_pass = record_pass(unit, fixture_id, ENG1)
        validate_success(
            api.void_test_result(r_pass["id"], {"reason": "wrong unit scanned"}, QE), 200
        )
        # The voided pass left the replay set: the soft-fail is insertion 1 and is
        # a first insertion, not a retest (no authorization needed).
        soft_fail = record_soft_fail(unit, fixture_id, ENG1)
        assert soft_fail["insertion_index"] == 1

        report = validate_success(api.get_yield_report(ctx["lot"]["id"], QE), 200)
        assert report["first_pass_yield"] == pytest.approx(0.0, abs=1e-9), (
            "the first effective insertion failed"
        )
        assert report["bin_counts"] == {"2": 1}, "the voided pass is excluded"
        unit_after = validate_success(api.get_unit(unit["id"], QE), 200)
        assert unit_after["test_status"] == "FAILED"
        assert unit_after["retest_count"] == 0, "a void does not manufacture a retest"

    def test_unit_projection_replay_after_retest_void(self, api):
        """PRD §3.5: "The void flips the result's `voided` flag to true and replays
        the unit's remaining effective results: the unit's `test_status` and
        `current_bin` are recomputed from the new latest result, or return to
        `UNTESTED` and null when none remain."
        PRD §3.5: "The lot's tallies are recomputed, but the unit's `retest_count`
        is deliberately not decremented — authorization history is preserved even
        when the result it enabled is struck from the tally."

        Design: Corner/calculations/unit_projection_replay_after_retest_void
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-213",
                                bin_map={"1": "PASS", "2": "SOFT_FAIL"})
        unit = ctx["units"][0]
        fixture_id = ctx["fixture"]["id"]
        record_soft_fail(unit, fixture_id, ENG1)
        authorize_retest(unit["id"], reason="retry", engineer_headers=ENG2)
        r_pass = record_pass(unit, fixture_id, ENG1)

        validate_success(
            api.void_test_result(r_pass["id"], {"reason": "operator misread"}, QE), 200
        )
        unit_after = validate_success(api.get_unit(unit["id"], QE), 200)
        assert unit_after["test_status"] == "FAILED", (
            "replay over remaining results lands on the soft-fail"
        )
        assert unit_after["current_bin"] == 2
        assert unit_after["retest_count"] == 1, (
            "retest history is preserved even though its result was voided"
        )
