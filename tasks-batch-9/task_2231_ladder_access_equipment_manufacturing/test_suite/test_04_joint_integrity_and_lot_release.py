"""Joint pull sampling, the conformance index and the lot release gates."""

from test_helpers import (
    ApiErrorId,
    add_joint_samples,
    add_passing_joint_samples,
    api_client,
    assert_instant_equals,
    assert_lot_units_conserved,
    disposition_payload,
    get_lot_data,
    open_lot,
    quarantine_payload,
    setup_frozen_product,
    start_lot_production,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

TECHNICIAN = TEST_USERS["test_lab_technician_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]

# A fiberglass TYPE_IA model: rated load 300 lb, so every joint sample is
# measured against a 450.00 lbf pull requirement.
MODEL = {
    "product_type": "EXTENSION_LADDER",
    "material": "FIBERGLASS_PULTRUSION",
    "duty_rating": "TYPE_IA",
    "working_length_ft": 24.0,
}


def _lot_in_process(produced_units=400):
    ctx = setup_frozen_product(**MODEL)
    assert float(ctx["product"]["required_pull_force_lbf"]) == 450.00
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], produced_units)
    return ctx, lot


class TestPerSampleMarginRounding:
    # Four pulls whose exact margins are 4.44, 2.67, 1.78 and 1.33 percent.
    PULLS = [470.00, 462.00, 458.00, 456.00]

    def test_each_sample_margin_is_rounded_to_a_whole_percent_on_insert(self):
        """PRD §3.6: "Each sample's `margin_pct` is the measured `pull_force_lbf`
        minus its snapshot requirement, divided by that snapshot requirement,
        expressed as a percentage, rounded half up to a whole number."
        PRD §3.6: "Each sample snapshots the model's `required_pull_force_lbf` at
        insert time into its own `required_pull_force_lbf`, so later changes
        elsewhere cannot rewrite history, and its `result` is `PASS` when the
        measured `pull_force_lbf` is greater than or equal to that snapshot and
        `FAIL` otherwise."

        Design: Difficulty/combinatorial_formula/joint_margin_rounded_per_sample_then_averaged
        """
        _, lot = _lot_in_process()

        samples = add_joint_samples(lot["id"], self.PULLS)

        assert [int(sample["margin_pct"]) for sample in samples] == [4, 3, 2, 1]
        for sample in samples:
            assert float(sample["required_pull_force_lbf"]) == 450.00, (
                "every sample snapshots the model requirement at insert time"
            )
            assert sample["result"] == "PASS"

    def test_conformance_index_averages_the_already_rounded_whole_percents(self):
        """PRD §3.6: "The lot's `conformance_index` is then the arithmetic mean of
        those whole-percent integers across every sample on the lot, rounded half
        up to two decimal places."
        PRD §2.6: "each joint sample's already-rounded whole-percent `margin_pct`
        is what enters the lot average — the lot average is never taken over
        unrounded margins."

        Design: Difficulty/combinatorial_formula/joint_margin_rounded_per_sample_then_averaged
        """
        _, lot = _lot_in_process()
        add_joint_samples(lot["id"], self.PULLS)

        reread = get_lot_data(lot["id"])

        # Mean of 4, 3, 2, 1 is 2.50; averaging the unrounded margins first and
        # rounding once at the end would read 2.56 instead.
        assert float(reread["conformance_index"]) == 2.50
        assert float(reread["conformance_index"]) != 2.56
        assert reread["joint_sample_count"] == 4
        assert reread["joint_fail_count"] == 0
        assert reread["required_joint_sample_count"] == 4


class TestEmptySampleSetOnRelease:
    def test_release_of_a_lot_with_no_samples_is_rejected(self):
        """PRD §3.6: "The lot must have at least one sample, or the release is
        rejected with `ERR_NO_JOINT_SAMPLES` — this is the empty-collection edge,
        where `conformance_index` is null rather than zero."

        Design: Difficulty/boundary_precision_check/release_with_empty_joint_sample_set_rejected
        """
        _, lot = _lot_in_process()

        response = api_client.release_production_lot(lot["id"], SUPERVISOR)
        validate_error(response, ApiErrorId.ERR_NO_JOINT_SAMPLES.value, 422)

        reread = get_lot_data(lot["id"])
        assert reread["status"] == "IN_PROCESS", "the rejected release changes nothing"
        assert reread["released_at"] is None

    def test_conformance_index_of_an_unsampled_lot_is_null_and_not_zero(self):
        """PRD §3.6: "When a lot has no samples at all, `conformance_index` is
        **null**, not 0.00."
        PRD §3.6: "`required_joint_sample_count` is derived as the larger of four
        samples and the lot's `produced_units` divided by 250 units per sample
        rounded **up** to a whole number"

        Design: Difficulty/boundary_precision_check/release_with_empty_joint_sample_set_rejected
        """
        _, lot = _lot_in_process()

        reread = get_lot_data(lot["id"])
        assert reread["conformance_index"] is None
        assert reread["joint_sample_count"] == 0
        assert reread["required_joint_sample_count"] == 4

        rows, meta = validate_paginated(
            api_client.list_joint_samples(lot["id"], TECHNICIAN)
        )
        assert rows == []
        assert meta["total_count"] == 0


class TestReleaseErrorPrecedence:
    # The fourth pull is far below the 450.00 lbf requirement, so it FAILs with a
    # margin of minus eleven percent and drags the index to -0.50.
    PULLS = [470.00, 462.00, 458.00, 400.00]

    def _lot_with_one_failed_sample(self):
        _, lot = _lot_in_process()
        add_joint_samples(lot["id"], self.PULLS)
        reread = get_lot_data(lot["id"])
        assert reread["joint_fail_count"] == 1
        assert float(reread["conformance_index"]) == -0.50
        return reread

    def test_quarantined_lot_release_reports_the_state_error_not_the_safety_error(self):
        """PRD §2.5: "Requests are evaluated against a fixed priority ladder, and
        the **first** failing check determines the response. Later checks never
        mask an earlier one."
        PRD §3.6: "A lot in the wrong state for the requested step — anything but
        `OPEN` for starting production, anything but `IN_PROCESS` for recording
        joint samples or releasing, anything but `IN_PROCESS` or `RELEASED` for
        quarantine, anything but `QUARANTINED` for disposition — is rejected with
        `ERR_LOT_STATE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/release_state_error_outranks_joint_safety_error
        """
        lot = self._lot_with_one_failed_sample()
        validate_success(
            api_client.quarantine_production_lot(
                lot["id"], quarantine_payload("JOINT_INTEGRITY"), SUPERVISOR
            )
        )

        response = api_client.release_production_lot(lot["id"], SUPERVISOR)
        validate_error(response, ApiErrorId.ERR_LOT_STATE_INVALID.value, 409)

        reread = get_lot_data(lot["id"])
        assert reread["status"] == "QUARANTINED"
        assert reread["joint_fail_count"] == 1
        assert float(reread["conformance_index"]) == -0.50
        assert reread["released_at"] is None

    def test_the_same_lot_in_process_reports_the_joint_integrity_failure(self):
        """PRD §3.6: "Its `joint_fail_count` must be exactly 0, or the release is
        rejected with `ERR_JOINT_INTEGRITY_FAILURE`."
        PRD §2.5: "26. through 31. Manufacturing and labelling safety gates, in
        this order: `ERR_NO_JOINT_SAMPLES`, `ERR_JOINT_SAMPLE_COUNT_SHORT`,
        `ERR_JOINT_INTEGRITY_FAILURE`, `ERR_CONFORMANCE_BELOW_MINIMUM`,
        `ERR_LABEL_SET_INCOMPLETE`, `ERR_LABEL_PLACEMENT_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/release_state_error_outranks_joint_safety_error
        """
        lot = self._lot_with_one_failed_sample()

        # Same violated safety predicates, but the lot is still IN_PROCESS, so
        # the state check no longer fires ahead of them.
        response = api_client.release_production_lot(lot["id"], SUPERVISOR)
        validate_error(response, ApiErrorId.ERR_JOINT_INTEGRITY_FAILURE.value, 422)

        assert get_lot_data(lot["id"])["status"] == "IN_PROCESS"


class TestLotUnitConservation:
    def _released_lot(self):
        ctx, lot = _lot_in_process()
        add_passing_joint_samples(lot["id"], ctx["product"]["required_pull_force_lbf"], 4)
        lot = validate_success(
            api_client.release_production_lot(lot["id"], SUPERVISOR)
        )
        assert lot["units_released"] == 400
        assert_instant_equals(lot["released_at"], "2026-08-01T00:00:00Z", "released_at")
        return ctx, lot

    def test_quarantine_moves_every_unit_into_the_quarantine_bucket(self):
        """PRD §2.9: "A production lot's five unit counters satisfy the identity
        that `units_wip` plus `units_quarantined` plus `units_released` plus
        `units_scrapped` always equals `produced_units`."
        PRD §3.6: "Whichever from-state the lot was in, both `units_wip` and
        `units_released` move into `units_quarantined`, leaving the conserved sum
        unchanged, and `quarantine_reason_code` is set to the supplied
        `reason_code`"

        Design: Difficulty/compensating_invariant/lot_unit_count_conserved_across_quarantine_and_release
        """
        _, lot = self._released_lot()

        quarantined = validate_success(
            api_client.quarantine_production_lot(
                lot["id"], quarantine_payload("LABEL_DEFECT"), SUPERVISOR
            )
        )

        assert quarantined["status"] == "QUARANTINED"
        assert quarantined["quarantine_reason_code"] == "LABEL_DEFECT"
        assert quarantined["units_quarantined"] == 400
        assert quarantined["units_released"] == 0
        assert quarantined["units_wip"] == 0
        assert quarantined["units_scrapped"] == 0
        assert quarantined["produced_units"] == 400
        assert_lot_units_conserved(quarantined)

    def test_release_disposition_restores_the_pre_quarantine_bucket_split(self):
        """PRD §3.6: "Choosing `RELEASE` is the compensating action for
        quarantine: it moves the lot `QUARANTINED` → `RELEASED`, moves the whole
        `units_quarantined` bucket back into `units_released` and so restores the
        pre-quarantine bucket split exactly, sets `disposition` to `RELEASE`,
        clears `quarantine_reason_code` to null"
        PRD §3.6: "`released_at` is stamped with the logical clock if it is
        currently null and is otherwise left alone, so it survives later
        quarantine cycles as the lot's first-shipment instant"

        Design: Difficulty/compensating_invariant/lot_unit_count_conserved_across_quarantine_and_release
        """
        _, lot = self._released_lot()
        validate_success(
            api_client.quarantine_production_lot(
                lot["id"], quarantine_payload("LABEL_DEFECT"), SUPERVISOR
            )
        )

        disposed = validate_success(
            api_client.disposition_production_lot(
                lot["id"], disposition_payload("RELEASE"), SUPERVISOR
            )
        )

        assert disposed["status"] == "RELEASED"
        assert disposed["disposition"] == "RELEASE"
        assert disposed["quarantine_reason_code"] is None
        assert disposed["units_released"] == 400
        assert disposed["units_quarantined"] == 0
        assert disposed["units_wip"] == 0
        assert disposed["units_scrapped"] == 0
        assert disposed["produced_units"] == 400
        assert_lot_units_conserved(disposed)
        assert_instant_equals(
            disposed["released_at"], "2026-08-01T00:00:00Z", "released_at"
        )
