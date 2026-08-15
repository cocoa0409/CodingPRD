"""Boundary precision: the MPF dollar cap boundary and the lot integer-units
depletion boundary."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_filed_withdrawal,
    create_weekly_entry,
    create_withdrawal,
    create_zone,
    file_withdrawal,
    get_lot,
    get_success_data,
    make_importer_headers,
    make_zone_operator_headers,
    set_clock,
    setup_zone_with_lot,
    submit_admission,
    admit_admission,
    create_admission,
    validate_error,
    validate_success,
)


class TestMpfMaxCapExactBoundary:
    """MPF cap boundary: entered value 17321000 rounds the raw fee to exactly
    MPF_MAX_CENTS 60000 (cap NOT engaged); 17321300 rounds to 60001 and IS capped."""

    def _setup_entries_at_cap(self):
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Cap Zone", zone_code="Z-CAP")
        op = make_zone_operator_headers()

        a1 = create_admission(zone["id"], importer_id="imp-1", description="Bulk parts A",
                              hts_code="8708.29", quantity=1, unit_value_cents=17321000,
                              zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a1["id"], importer_id="imp-1")
        admit_admission(a1["id"])
        lot1 = get_success_data(api_client.list_lots(op, params={"admission_id": a1["id"]}))[0]

        a2 = create_admission(zone["id"], importer_id="imp-1", description="Bulk parts B",
                              hts_code="8708.29", quantity=1, unit_value_cents=17321300,
                              zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a2["id"], importer_id="imp-1")
        admit_admission(a2["id"])
        lot2 = get_success_data(api_client.list_lots(op, params={"admission_id": a2["id"]}))[0]

        # Half-open adjacency: E1 [08-03, 08-10), E2 [08-10, 08-17).
        e1 = create_weekly_entry(zone["id"], week_start_date="2026-08-03T00:00:00Z",
                                 importer_id="imp-1")
        e2 = create_weekly_entry(zone["id"], week_start_date="2026-08-10T00:00:00Z",
                                 importer_id="imp-1")

        # File each withdrawal inside its entry's week via the logical clock.
        set_clock("2026-08-04T00:00:00Z")
        create_filed_withdrawal(zone["id"], lot1["id"], quantity=1,
                                weekly_entry_id=e1["id"], importer_id="imp-1")
        set_clock("2026-08-11T00:00:00Z")
        create_filed_withdrawal(zone["id"], lot2["id"], quantity=1,
                                weekly_entry_id=e2["id"], importer_id="imp-1")
        return zone, e1, e2

    def test_raw_fee_exactly_at_max_is_not_capped(self):
        """PRD §3.6: "The consolidated `mpf_cents` then applies the statutory floor
        and ceiling: it is the uncapped fee raised to at least 3,000 cents (that is,
        $30.00) and capped at at most 60,000 cents ($600.00)."
        PRD §3.6: "`mpf_uncapped_cents` is `entered_value_cents` multiplied by that
        rate, rounded half up to integer cents."

        Design: Difficulty/boundary_precision_check/mpf_max_cap_exact_boundary
        """
        _zone, e1, _e2 = self._setup_entries_at_cap()
        imp = make_importer_headers("imp-1")
        data = validate_success(api_client.file_weekly_entry(e1["id"], imp))
        # raw 17321000 x 0.003464 = 59999.944 -> round half up -> exactly 60000
        assert data["mpf_uncapped_cents"] == 60000, (
            f"raw 59999.944 rounds to exactly MAX 60000, got {data['mpf_uncapped_cents']}"
        )
        assert data["mpf_cents"] == 60000, (
            f"raw == MAX is not above the cap: mpf stays 60000, got {data['mpf_cents']}"
        )

    def test_raw_fee_one_cent_over_max_is_capped(self):
        """PRD §3.6: "The consolidated `mpf_cents` then applies the statutory floor
        and ceiling: it is the uncapped fee raised to at least 3,000 cents (that is,
        $30.00) and capped at at most 60,000 cents ($600.00)."

        Design: Difficulty/boundary_precision_check/mpf_max_cap_exact_boundary
        """
        _zone, _e1, e2 = self._setup_entries_at_cap()
        imp = make_importer_headers("imp-1")
        data = validate_success(api_client.file_weekly_entry(e2["id"], imp))
        # raw 17321300 x 0.003464 = 60000.9832 -> round -> 60001 -> capped to 60000
        assert data["mpf_uncapped_cents"] == 60001, (
            f"raw 60000.9832 rounds to 60001, got {data['mpf_uncapped_cents']}"
        )
        assert data["mpf_cents"] == 60000, (
            f"60001 exceeds the cap: mpf capped to 60000, got {data['mpf_cents']}"
        )

    def test_duty_totals_at_the_cap_boundary(self):
        """PRD §3.6: "Each line's duty is that line value multiplied by the lot's
        `duty_rate`, rounded half up to integer cents per line first."
        PRD §2.6: "all rounding is round half up to integer cents"

        Design: Difficulty/boundary_precision_check/mpf_max_cap_exact_boundary
        """
        _zone, e1, e2 = self._setup_entries_at_cap()
        imp = make_importer_headers("imp-1")
        d1 = validate_success(api_client.file_weekly_entry(e1["id"], imp))
        d2 = validate_success(api_client.file_weekly_entry(e2["id"], imp))
        # round(17321000 x 0.025) = 433025
        assert d1["duty_total_cents"] == 433025, (
            f"duty round(17321000 x 0.025) == 433025, got {d1['duty_total_cents']}"
        )
        # round(17321300 x 0.025) = round(433032.5) = 433033 (half-up)
        assert d2["duty_total_cents"] == 433033, (
            f"duty round(433032.5) half-up == 433033, got {d2['duty_total_cents']}"
        )


class TestLotExactDepletionBoundary:
    """Availability rule is inclusive: quantity == on_hand - reserved files and
    depletes; quantity == available + 1 is rejected."""

    def _setup(self):
        return setup_zone_with_lot(
            quantity=5, unit_value_cents=1000, hts_code="0401.10",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Edge Zone", zone_code="Z-EDG",
        )

    def test_over_available_filing_rejected(self):
        """PRD §3.5: "Availability is checked at this moment, not at creation: the
        `quantity` must be at most the lot's `quantity_on_hand` minus its
        `reserved_quantity`, with exact equality permitted (otherwise
        `ERR_INSUFFICIENT_QUANTITY`)."

        Design: Difficulty/boundary_precision_check/lot_exact_depletion_boundary
        """
        zone, _a, lot = self._setup()
        imp = make_importer_headers("imp-1")
        w_over = get_success_data(api_client.create_withdrawal(
            {"zone_id": zone["id"], "lot_id": lot["id"], "withdrawal_type": "CONSUMPTION",
             "quantity": 6}, imp,
        ))
        resp = api_client.file_withdrawal(w_over["id"], imp)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_QUANTITY, expected_status=422)

        lot_after = get_lot(lot["id"])
        assert lot_after["quantity_on_hand"] == 5, (
            f"the failed over-quantity filing must leave the lot untouched, "
            f"got on_hand {lot_after['quantity_on_hand']}"
        )

    def test_exact_available_filing_succeeds_and_depletes(self):
        """PRD §3.5: "the `quantity` must be at most the lot's `quantity_on_hand`
        minus its `reserved_quantity`, with exact equality permitted (otherwise
        `ERR_INSUFFICIENT_QUANTITY`)."
        PRD §3.5: "a lot left at zero on hand transitions from `IN_ZONE` to
        `DEPLETED`"

        Design: Difficulty/boundary_precision_check/lot_exact_depletion_boundary
        """
        zone, _a, lot = self._setup()
        imp = make_importer_headers("imp-1")
        w_exact = create_filed_withdrawal(zone["id"], lot["id"], quantity=5,
                                          withdrawal_type="CONSUMPTION", importer_id="imp-1")
        assert w_exact["status"] == "FILED", (
            f"exact-equality filing must succeed, got {w_exact['status']}"
        )
        lot_after = get_lot(lot["id"])
        assert lot_after["quantity_on_hand"] == 0
        assert lot_after["status"] == "DEPLETED"
        assert lot_after["cumulative_withdrawn"] == 5
