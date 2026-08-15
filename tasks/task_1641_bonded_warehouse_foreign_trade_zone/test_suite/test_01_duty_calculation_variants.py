"""Duty assessment variants: privileged-foreign vs non-privileged-foreign,
DOMESTIC short-circuit, and round-half-up precision."""
import pytest

from test_helpers import (
    ApiErrorId,
    admit_admission,
    api_client,
    create_admission,
    create_filed_withdrawal,
    create_manipulation_order,
    approve_manipulation_order,
    complete_manipulation_order,
    create_weekly_entry,
    create_zone,
    get_success_data,
    make_importer_headers,
    make_zone_operator_headers,
    setup_zone_with_lot,
    submit_admission,
    validate_success,
)


class TestManipulatedDutyPfVsNpfVariant:
    """Identical merchandise and manipulation diverge: the PRIVILEGED_FOREIGN
    variant locks the component rate/basis while the NON_PRIVILEGED_FOREIGN
    variant re-derives rate and value-added basis at the output code."""

    def _setup_pf_npf_output_lots(self):
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Variant Zone", zone_code="Z-VAR")
        op = make_zone_operator_headers()
        imp = make_importer_headers("imp-1")

        # PRIVILEGED_FOREIGN leg: 100 units @ 10000 of HTS 8542.31 (rate 0.04)
        a_pf = create_admission(zone["id"], importer_id="imp-1", description="Processors PF",
                                hts_code="8542.31", quantity=100, unit_value_cents=10000,
                                zone_status="PRIVILEGED_FOREIGN")
        submit_admission(a_pf["id"], importer_id="imp-1")
        admit_admission(a_pf["id"])
        lot_pf = get_success_data(api_client.list_lots(op, params={"admission_id": a_pf["id"]}))[0]

        # NON_PRIVILEGED_FOREIGN leg: identical physical merchandise
        a_npf = create_admission(zone["id"], importer_id="imp-1", description="Processors NPF",
                                 hts_code="8542.31", quantity=100, unit_value_cents=10000,
                                 zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a_npf["id"], importer_id="imp-1")
        admit_admission(a_npf["id"])
        lot_npf = get_success_data(api_client.list_lots(op, params={"admission_id": a_npf["id"]}))[0]

        # Identical manipulation on both: 100 -> 50 units of HTS 9503.00, value added 200000
        m_pf = create_manipulation_order(zone["id"], lot_pf["id"], input_quantity=100,
                                         output_hts_code="9503.00", output_quantity=50,
                                         value_added_cents=200000,
                                         output_description="Assembled toys ex-PF",
                                         importer_id="imp-1")
        approve_manipulation_order(m_pf["id"])
        complete_manipulation_order(m_pf["id"], importer_id="imp-1")
        ol_pf = get_success_data(
            api_client.list_lots(op, params={"source_manipulation_id": m_pf["id"]}))[0]

        m_npf = create_manipulation_order(zone["id"], lot_npf["id"], input_quantity=100,
                                          output_hts_code="9503.00", output_quantity=50,
                                          value_added_cents=200000,
                                          output_description="Assembled toys ex-NPF",
                                          importer_id="imp-1")
        approve_manipulation_order(m_npf["id"])
        complete_manipulation_order(m_npf["id"], importer_id="imp-1")
        ol_npf = get_success_data(
            api_client.list_lots(op, params={"source_manipulation_id": m_npf["id"]}))[0]

        return zone, ol_pf, ol_npf

    def test_manipulated_pf_variant_locks_source_rate(self):
        """PRD §3.3: "for a lot produced by in-zone manipulation, the locked rate
        and the components' value basis carry over from the source lot, making
        privileged merchandise insensitive to value change inside the zone."
        PRD §3.5: "Filing stamps `withdrawal_date` from the logical clock, computes
        the final `assessed_duty_cents` using the same formula as the estimate but
        against the merchandise as it stands at filing"

        Design: Difficulty/dual_variant_calc/manipulated_duty_pf_vs_npf_variant
        """
        zone, ol_pf, _ol_npf = self._setup_pf_npf_output_lots()
        # Both output lots carry the pinned manipulation valuation
        assert ol_pf["unit_value_cents"] == 24000, (
            f"output unit value: round((round(100x10000)+200000)/50) == 24000, got {ol_pf['unit_value_cents']}"
        )
        assert ol_pf["zone_status"] == "PRIVILEGED_FOREIGN"

        w = create_filed_withdrawal(zone["id"], ol_pf["id"], quantity=50,
                                    withdrawal_type="CONSUMPTION", importer_id="imp-1")
        # 50 x 24000 x 0.04 (locked source rate) = 48000
        assert w["assessed_duty_cents"] == 48000, (
            f"PF variant must use locked source rate 0.04: expected 48000, got {w['assessed_duty_cents']}"
        )

    def test_manipulated_npf_variant_uses_finished_good_rate_and_basis(self):
        """PRD §3.3: "A `NON_PRIVILEGED_FOREIGN` lot is re-derived as merchandise
        stands when withdrawn: its `duty_rate` comes from the tariff schedule at the
        lot's current `hts_code`, and a manipulated output lot's value basis
        includes the value added in the zone."

        Design: Difficulty/dual_variant_calc/manipulated_duty_pf_vs_npf_variant
        """
        zone, ol_pf, ol_npf = self._setup_pf_npf_output_lots()
        assert ol_npf["unit_value_cents"] == 24000
        assert ol_npf["zone_status"] == "NON_PRIVILEGED_FOREIGN"

        w = create_filed_withdrawal(zone["id"], ol_npf["id"], quantity=50,
                                    withdrawal_type="CONSUMPTION", importer_id="imp-1")
        # 50 x 24000 x 0.12 (finished-good rate on value-added basis) = 144000
        assert w["assessed_duty_cents"] == 144000, (
            f"NPF variant must use finished-good rate 0.12: expected 144000, got {w['assessed_duty_cents']}"
        )

    def test_manipulated_variants_diverge_for_identical_transformation(self):
        """PRD §3.3: "A `PRIVILEGED_FOREIGN` lot keeps the rate and per-unit value
        basis locked in when its merchandise was admitted" versus "A
        `NON_PRIVILEGED_FOREIGN` lot is re-derived as merchandise stands when
        withdrawn" — the same physical transformation yields different duty.

        Design: Difficulty/dual_variant_calc/manipulated_duty_pf_vs_npf_variant
        """
        zone, ol_pf, ol_npf = self._setup_pf_npf_output_lots()
        w_pf = create_filed_withdrawal(zone["id"], ol_pf["id"], quantity=50,
                                       withdrawal_type="CONSUMPTION", importer_id="imp-1")
        w_npf = create_filed_withdrawal(zone["id"], ol_npf["id"], quantity=50,
                                        withdrawal_type="CONSUMPTION", importer_id="imp-1")
        assert w_pf["assessed_duty_cents"] == 48000
        assert w_npf["assessed_duty_cents"] == 144000
        assert w_pf["assessed_duty_cents"] != w_npf["assessed_duty_cents"], (
            "identical quantities and identical physical transformation must still diverge "
            "across the PF/NPF duty variants"
        )


class TestDutyBranchingByZoneStatus:
    """Combinatorial duty branches by lot zone_status (DOMESTIC short-circuits
    to zero; PF and NPF take the ad valorem branch)."""

    def _file_ten_units(self, zone_status):
        zone, _a, lot = setup_zone_with_lot(
            quantity=10, unit_value_cents=5000, hts_code="9503.00",
            zone_status=zone_status, bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Branch Zone", zone_code="Z-BR",
        )
        w = create_filed_withdrawal(zone["id"], lot["id"], quantity=10,
                                    withdrawal_type="CONSUMPTION", importer_id="imp-1")
        return w

    def test_domestic_branch_short_circuits_to_zero(self):
        """PRD §3.3: "A `DOMESTIC` lot always carries a `duty_rate` of zero."

        Design: Difficulty/combinatorial_formula/duty_branching_by_zone_status
        """
        w = self._file_ten_units("DOMESTIC")
        assert w["assessed_duty_cents"] == 0, (
            f"DOMESTIC branch must yield 0 regardless of HTS rate, got {w['assessed_duty_cents']}"
        )

    def test_privileged_foreign_branch_ad_valorem(self):
        """PRD §3.3: "A `PRIVILEGED_FOREIGN` lot keeps the rate and per-unit value
        basis locked in when its merchandise was admitted" — duty is
        round(quantity x unit_value x rate).

        Design: Difficulty/combinatorial_formula/duty_branching_by_zone_status
        """
        w = self._file_ten_units("PRIVILEGED_FOREIGN")
        # 10 x 5000 x 0.12 = 6000
        assert w["assessed_duty_cents"] == 6000, (
            f"PF ad valorem branch: expected 6000, got {w['assessed_duty_cents']}"
        )

    def test_non_privileged_foreign_branch_ad_valorem(self):
        """PRD §3.3: "A `NON_PRIVILEGED_FOREIGN` lot is re-derived as merchandise
        stands when withdrawn: its `duty_rate` comes from the tariff schedule at
        the lot's current `hts_code`" — here 9503.00 at 0.12.

        Design: Difficulty/combinatorial_formula/duty_branching_by_zone_status
        """
        w = self._file_ten_units("NON_PRIVILEGED_FOREIGN")
        assert w["assessed_duty_cents"] == 6000, (
            f"NPF ad valorem branch: expected 6000, got {w['assessed_duty_cents']}"
        )


class TestWeeklySettlementLineRoundingOrder:
    """Nested rounding: per-line duty rounded half-up FIRST then summed; MPF
    separately rounds the consolidated value once then applies min/max caps."""

    def _setup_two_line_entry(self):
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Round Zone", zone_code="Z-RND")
        op = make_zone_operator_headers()

        a1 = create_admission(zone["id"], importer_id="imp-1", description="Auto parts A",
                              hts_code="8708.29", quantity=10, unit_value_cents=1221,
                              zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a1["id"], importer_id="imp-1")
        admit_admission(a1["id"])
        lot1 = get_success_data(api_client.list_lots(op, params={"admission_id": a1["id"]}))[0]

        a2 = create_admission(zone["id"], importer_id="imp-1", description="Auto parts B",
                              hts_code="8708.29", quantity=10, unit_value_cents=1421,
                              zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a2["id"], importer_id="imp-1")
        admit_admission(a2["id"])
        lot2 = get_success_data(api_client.list_lots(op, params={"admission_id": a2["id"]}))[0]

        entry = create_weekly_entry(zone["id"], week_start_date="2026-07-27T00:00:00Z",
                                    importer_id="imp-1")
        w1 = create_filed_withdrawal(zone["id"], lot1["id"], quantity=1,
                                     weekly_entry_id=entry["id"], importer_id="imp-1")
        w2 = create_filed_withdrawal(zone["id"], lot2["id"], quantity=1,
                                     weekly_entry_id=entry["id"], importer_id="imp-1")
        return zone, entry, w1, w2

    def test_per_line_rounding_then_sum(self):
        """PRD §3.6: "Each line's duty is that line value multiplied by the lot's
        `duty_rate`, rounded half up to integer cents per line first."
        PRD §3.6: "The `duty_total_cents` is the sum of the per-line rounded duties
        — summing the exact duties and rounding once at the end yields different
        cents and is non-conformant."

        Design: Difficulty/combinatorial_formula/weekly_settlement_line_rounding_order
        """
        _zone, entry, _w1, _w2 = self._setup_two_line_entry()
        imp = make_importer_headers("imp-1")
        data = validate_success(api_client.file_weekly_entry(entry["id"], imp))
        # line values 1221 and 1421 -> entered value 2642
        assert data["entered_value_cents"] == 2642, (
            f"entered value 1221 + 1421 == 2642, got {data['entered_value_cents']}"
        )
        # per-line: round(1221 x 0.025)=round(30.525)=31; round(1421 x 0.025)=round(35.525)=36 -> 67
        assert data["duty_total_cents"] == 67, (
            f"duty total must be 31 + 36 == 67 (per-line rounding); sum-then-round of 66.05 "
            f"would give 66 and is non-conformant; got {data['duty_total_cents']}"
        )

    def test_mpf_floor_and_savings(self):
        """PRD §3.6: "`mpf_uncapped_cents` is `entered_value_cents` multiplied by
        that rate, rounded half up to integer cents."
        PRD §3.6: "The consolidated `mpf_cents` then applies the statutory floor and
        ceiling: it is the uncapped fee raised to at least 3,000 cents (that is,
        $30.00) and capped at at most 60,000 cents ($600.00)."
        PRD §3.6: "Finally, `mpf_savings_cents` is `per_shipment_mpf_cents` minus
        `mpf_cents`."

        Design: Difficulty/combinatorial_formula/weekly_settlement_line_rounding_order
        """
        _zone, entry, _w1, _w2 = self._setup_two_line_entry()
        imp = make_importer_headers("imp-1")
        data = validate_success(api_client.file_weekly_entry(entry["id"], imp))
        # round(2642 x 0.003464) = round(9.151888) = 9
        assert data["mpf_uncapped_cents"] == 9, (
            f"mpf uncapped round(2642 x 0.003464) == 9, got {data['mpf_uncapped_cents']}"
        )
        # floor: max(9, 3000) = 3000
        assert data["mpf_cents"] == 3000, (
            f"MPF_MIN floor: expected 3000, got {data['mpf_cents']}"
        )
        # each line alone rounds below the floor: 3000 + 3000 = 6000
        assert data["per_shipment_mpf_cents"] == 6000, (
            f"per-shipment MPF: each line alone floors at 3000 -> 6000, got {data['per_shipment_mpf_cents']}"
        )
        assert data["mpf_savings_cents"] == 3000, (
            f"savings 6000 - 3000 == 3000, got {data['mpf_savings_cents']}"
        )
