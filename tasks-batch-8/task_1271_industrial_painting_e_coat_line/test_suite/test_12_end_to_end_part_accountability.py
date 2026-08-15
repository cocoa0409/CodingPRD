"""End-to-end rework cycle: part-accountability invariant and charge finalization."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_lot_qc_pending, setup_lot_requeued_after_rework,
    record_quality_test, run_lot_through_second_pass,
    get_lot, assert_lot_part_accountability,
    TEST_USERS, make_quality_manager_headers,
)

QM = TEST_USERS["qm_headers"]


class TestPartAccountabilityAcrossReworkCycle:
    def test_full_rework_cycle_conserves_accounted_parts(self, api):
        """PRD §3.6: "One invariant holds across the entire lifecycle, through every
        rework cycle: `part_quantity` always equals `passed_quantity` plus
        `scrapped_quantity` plus `outstanding_quantity`. Every part is accounted for,
        always — released, scrapped, or still outstanding."
        PRD §3.6: "A successful release finalizes the lot's economics in the same
        request: `passed_quantity` is set to `part_quantity` minus `scrapped_quantity`,
        and `total_charge_cents` is fixed as `base_charge_cents` plus
        `purge_alloc_cents` plus `rework_charge_cents`."

        Design: Difficulty/compensating_invariant/part_accountability_rework_cycle_conserved
        """
        # First pass: cure passes, adhesion fails, strip with 5 scrapped of 100.
        ctx = setup_lot_requeued_after_rework(scrapped_quantity=5)
        lot_mid = ctx["lot"]
        assert lot_mid["status"] == "QUEUED"
        assert lot_mid["rework_count"] == 1
        assert lot_mid["scrapped_quantity"] == 5
        assert_lot_part_accountability(lot_mid)

        # Second pass: repaint, cure passes, both evidence legs pass, release.
        run_lot_through_second_pass(ctx)
        record_quality_test(ctx["lot"]["id"], "ADHESION", 3)
        record_quality_test(ctx["lot"]["id"], "IMPACT", 50.0)
        released = validate_success(
            api.release_lot(ctx["lot"]["id"], make_quality_manager_headers("qm-1")), 200
        )

        assert released["status"] == "RELEASED"
        assert released["passed_quantity"] == 95
        assert released["scrapped_quantity"] == 5
        assert released["outstanding_quantity"] == 0
        assert_lot_part_accountability(released)
        # 132000 base + 0 purge + 183915 rework (55000 strip + 128915 repaint).
        assert released["total_charge_cents"] == 315915

    def test_rework_charge_accumulates_onto_lot_economics(self, api):
        """PRD §3.7: "In either outcome the order moves to the terminal `COMPLETED`,
        the lot's `scrapped_quantity` grows by the reported amount, the `rework_count`
        increments by one, the order's `total_charge_cents` — its strip cost plus its
        repaint charge — is added to the lot's `rework_charge_cents`, and a
        `STRIP_SOLVENT` emission entry is posted for the stripped part count:
        `parts_to_rework` minus `scrapped_quantity` parts, each consuming 0.5 liters of
        strip solvent at 900 grams of VOC per liter, so the entry's `voc_kg` is the
        stripped count multiplied by 0.5, multiplied by 900, divided by 1000, and
        rounded half-up to three decimal places."

        Design: Difficulty/compensating_invariant/part_accountability_rework_cycle_conserved
        """
        ctx = setup_lot_requeued_after_rework(scrapped_quantity=5)
        lot_mid = ctx["lot"]
        # Order total (55000 strip + 128915 repaint) lands on the lot accumulator.
        assert lot_mid["rework_charge_cents"] == 183915
        assert lot_mid["base_charge_cents"] == 132000
        assert_lot_part_accountability(lot_mid)
