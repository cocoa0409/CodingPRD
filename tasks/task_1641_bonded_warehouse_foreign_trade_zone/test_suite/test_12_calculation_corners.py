"""Corner coverage for calculations: exposure recompute after manipulation,
reconciliation year-window filtering, and round-half-up precision."""
from test_helpers import (
    api_client,
    approve_manipulation_order,
    complete_manipulation_order,
    create_admission,
    create_filed_withdrawal,
    create_manipulation_order,
    create_reconciliation,
    create_zone,
    get_success_data,
    get_zone,
    make_zone_operator_headers,
    set_clock,
    setup_zone_with_lot,
    submit_admission,
    admit_admission,
    submit_reconciliation,
    validate_success,
)


class TestExposureRecomputeAfterManipulation:
    def test_exposure_tracks_lot_states_through_manipulation(self):
        """PRD §3.3: "The zone's `deferred_duty_exposure_cents` is the sum, taken
        over every lot of the zone whose status is `IN_ZONE`, of that lot's
        deferred-duty estimate: the lot's `quantity_on_hand` multiplied by its
        `unit_value_cents` and by its `duty_rate`, each lot's product rounded half
        up to integer cents before the products are summed."
        PRD §3.4: "Third, the zone's `active_lot_count` and
        `deferred_duty_exposure_cents` are recomputed."

        Design: Corner/calculations/c_exposure_recompute_after_manipulation
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=100, unit_value_cents=10000, hts_code="8542.31",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Exposure Zone", zone_code="Z-EXP",
        )
        # Before: round(100 x 10000 x 0.04) = 40000, one active lot.
        z_before = get_zone(zone["id"])
        assert z_before["deferred_duty_exposure_cents"] == 40000, (
            f"exposure after admission 40000, got {z_before['deferred_duty_exposure_cents']}"
        )
        assert z_before["active_lot_count"] == 1

        m = create_manipulation_order(
            zone["id"], lot["id"], input_quantity=100, output_hts_code="9503.00",
            output_quantity=50, value_added_cents=200000,
            output_description="Assembled toys", importer_id="imp-1",
        )
        approve_manipulation_order(m["id"])
        complete_manipulation_order(m["id"], importer_id="imp-1")

        # After: source DEPLETED contributes 0; output round(50 x 24000 x 0.12) = 144000.
        z_after = get_zone(zone["id"])
        assert z_after["deferred_duty_exposure_cents"] == 144000, (
            f"exposure after manipulation 144000, got {z_after['deferred_duty_exposure_cents']}"
        )
        assert z_after["active_lot_count"] == 1, (
            f"source DEPLETED + output IN_ZONE keeps count 1, got {z_after['active_lot_count']}"
        )


class TestReconWindowFiltersPriorYear:
    def test_prior_year_admission_excluded_from_book_receipts(self):
        """PRD §3.7: "The reconciliation window for a zone year runs from the first
        instant of January 1 of `zone_year` (inclusive) to the first instant of
        January 1 of the following year (exclusive)."
        PRD §3.7: "`book_receipts_value_cents` is the sum, over admissions in
        `ADMITTED` status whose `admission_date` falls inside the window, of each
        admission's `quantity` multiplied by its `unit_value_cents`"
        PRD §3.7: "when the book ending value is zero, the percentage is 0 if the
        physical count is also zero and 100 otherwise"

        Design: Corner/calculations/c_recon_window_filters_prior_year
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Window Zone", zone_code="Z-WIN")
        op = make_zone_operator_headers()
        # Admit under a 2025 clock — outside the 2026 window.
        set_clock("2025-06-01T00:00:00Z")
        a = create_admission(zone["id"], importer_id="imp-1", description="Old dairy",
                             hts_code="0401.10", quantity=4, unit_value_cents=2500,
                             zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a["id"], importer_id="imp-1")
        admitted = admit_admission(a["id"])
        assert admitted["admission_date"] == "2025-06-01T00:00:00Z"
        # Restore the clock to the 2026 default.
        set_clock("2026-08-01T00:00:00Z")

        recon = create_reconciliation(zone["id"], zone_year=2026,
                                      beginning_value_cents=0, physical_ending_value_cents=0)
        data = submit_reconciliation(recon["id"])
        # The 2025 admission (would be 10000) is outside the 2026 window.
        assert data["book_receipts_value_cents"] == 0, (
            f"prior-year admission excluded: expected 0, got {data['book_receipts_value_cents']}"
        )
        assert data["book_ending_value_cents"] == 0
        assert data["discrepancy_pct"] == 0, (
            f"zero-book rule with physical == 0 pins pct 0, got {data['discrepancy_pct']}"
        )
        assert data["audit_flagged"] is False


class TestDutyRoundingHalfUp:
    def test_exact_half_cent_rounds_up(self):
        """PRD §2.6: "all rounding is round half up to integer cents, applied at
        exactly the steps each calculation in §3 pins down"
        PRD §3.5: "Filing stamps `withdrawal_date` from the logical clock, computes
        the final `assessed_duty_cents` using the same formula as the estimate but
        against the merchandise as it stands at filing"

        Design: Corner/calculations/c_duty_rounding_half_up
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=1, unit_value_cents=1220, hts_code="8708.29",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Half Zone", zone_code="Z-HLF",
        )
        w = create_filed_withdrawal(zone["id"], lot["id"], quantity=1,
                                    withdrawal_type="CONSUMPTION", importer_id="imp-1")
        # 1 x 1220 x 0.025 = 30.5 -> 31 half-up (round-half-even would give 30)
        assert w["assessed_duty_cents"] == 31, (
            f"30.5 rounds half-up to 31, got {w['assessed_duty_cents']}"
        )
