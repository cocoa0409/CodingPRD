"""Compensating invariants: file/cancel pairs restore conserved quantities with
zero drift — merchandise units on the lot, and dollar totals on the entry."""
from test_helpers import (
    api_client,
    create_filed_withdrawal,
    create_weekly_entry,
    create_withdrawal,
    create_zone,
    file_withdrawal,
    get_lot,
    get_weekly_entry,
    make_importer_headers,
    setup_zone_with_lot,
    validate_success,
)


class TestLotUnitConservationOnCancel:
    """Conserved quantity: merchandise UNITS.
    admitted_quantity == quantity_on_hand + cumulative_withdrawn + cumulative_consumed."""

    def test_file_then_cancel_restores_units_with_zero_drift(self):
        """PRD §3.5: "The lot is then debited — `quantity_on_hand` decreased and
        `cumulative_withdrawn` increased by the withdrawal `quantity`"
        PRD §3.5: "Cancelling a `FILED` withdrawal compensates the filing in full:
        the lot's `quantity_on_hand` is increased by the withdrawal `quantity`, its
        `cumulative_withdrawn` is decreased by the same amount"

        Design: Difficulty/compensating_invariant/lot_unit_conservation_on_cancel
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=10, unit_value_cents=1221, hts_code="8708.29",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Units Zone", zone_code="Z-UNT",
        )
        imp = make_importer_headers("imp-1")
        w = create_withdrawal(zone["id"], lot["id"], quantity=4,
                              withdrawal_type="CONSUMPTION", importer_id="imp-1")
        validate_success(api_client.file_withdrawal(w["id"], imp))

        mid = get_lot(lot["id"])
        assert mid["quantity_on_hand"] == 6, f"after file: expected 6 on hand, got {mid['quantity_on_hand']}"
        assert mid["cumulative_withdrawn"] == 4, (
            f"after file: cumulative_withdrawn 4, got {mid['cumulative_withdrawn']}"
        )
        # conservation mid-flight: 10 == 6 + 4 + 0
        assert mid["admitted_quantity"] == (
            mid["quantity_on_hand"] + mid["cumulative_withdrawn"] + mid["cumulative_consumed"]
        )

        cancelled = validate_success(api_client.cancel_withdrawal(w["id"], imp))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["duty_outcome"] == "NONE"

        end = get_lot(lot["id"])
        assert end["quantity_on_hand"] == 10, (
            f"after cancel: quantity restored to 10, got {end['quantity_on_hand']}"
        )
        assert end["cumulative_withdrawn"] == 0, (
            f"after cancel: cumulative_withdrawn back to 0, got {end['cumulative_withdrawn']}"
        )
        assert end["cumulative_consumed"] == 0
        assert end["status"] == "IN_ZONE"
        # zero drift: 10 == 10 + 0 + 0
        assert end["admitted_quantity"] == (
            end["quantity_on_hand"] + end["cumulative_withdrawn"] + end["cumulative_consumed"]
        )

    def test_cancelled_filed_withdrawal_returns_depleted_lot_to_in_zone(self):
        """PRD §3.5: "a lot thereby restored from zero on hand returns from
        `DEPLETED` to `IN_ZONE`"

        Design: Difficulty/compensating_invariant/lot_unit_conservation_on_cancel
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=4, unit_value_cents=1221, hts_code="8708.29",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Units Zone 2", zone_code="Z-UN2",
        )
        imp = make_importer_headers("imp-1")
        # File away ALL 4 units -> DEPLETED.
        w = create_filed_withdrawal(zone["id"], lot["id"], quantity=4,
                                    withdrawal_type="CONSUMPTION", importer_id="imp-1")
        assert get_lot(lot["id"])["status"] == "DEPLETED"

        validate_success(api_client.cancel_withdrawal(w["id"], imp))
        end = get_lot(lot["id"])
        assert end["status"] == "IN_ZONE", (
            f"restored-from-zero lot must return to IN_ZONE, got {end['status']}"
        )
        assert end["quantity_on_hand"] == 4
        assert end["cumulative_withdrawn"] == 0


class TestEntryDollarTotalsConservationOnCancel:
    """Conserved quantity: weekly-entry DOLLAR totals return to exactly zero when
    the only member withdrawal is cancelled while the entry is OPEN."""

    def _setup(self):
        zone, _a, lot = setup_zone_with_lot(
            quantity=10, unit_value_cents=4000, hts_code="8542.31",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Totals Zone", zone_code="Z-TOT",
        )
        entry = create_weekly_entry(zone["id"], week_start_date="2026-07-27T00:00:00Z",
                                    importer_id="imp-1")
        w = create_withdrawal(zone["id"], lot["id"], quantity=2,
                              withdrawal_type="CONSUMPTION",
                              weekly_entry_id=entry["id"], importer_id="imp-1")
        return zone, lot, entry, w

    def test_filing_member_raises_entry_totals_live(self):
        """PRD §3.6: "These totals are live: whenever membership or a member's
        status changes — a member withdrawal is filed, cancelled, or detached by an
        entry freeze — the totals are recomputed immediately, not only at filing."
        PRD §3.6: "The `entered_value_cents` is the sum of the line values."

        Design: Difficulty/compensating_invariant/entry_dollar_totals_conservation_on_cancel
        """
        _zone, _lot, entry, w = self._setup()
        imp = make_importer_headers("imp-1")
        validate_success(api_client.file_withdrawal(w["id"], imp))

        mid = get_weekly_entry(entry["id"])
        # entered value: 2 x 4000 = 8000; duty: round(8000 x 0.04) = 320
        assert mid["entered_value_cents"] == 8000, (
            f"mid-flight entered value 8000, got {mid['entered_value_cents']}"
        )
        assert mid["duty_total_cents"] == 320, (
            f"mid-flight duty round(8000 x 0.04) == 320, got {mid['duty_total_cents']}"
        )
        # uncapped round(8000 x 0.003464) = 28 -> floored to MPF_MIN 3000
        assert mid["mpf_cents"] == 3000, (
            f"uncapped 28 floored to 3000, got {mid['mpf_cents']}"
        )

    def test_cancelling_only_member_restores_all_totals_to_zero(self):
        """PRD §3.6: "If the member set is empty, all six totals are zero and
        computation stops."
        PRD §3.6: "These totals are live: whenever membership or a member's status
        changes — a member withdrawal is filed, cancelled, or detached by an entry
        freeze — the totals are recomputed immediately, not only at filing."

        Design: Difficulty/compensating_invariant/entry_dollar_totals_conservation_on_cancel
        """
        _zone, _lot, entry, w = self._setup()
        imp = make_importer_headers("imp-1")
        validate_success(api_client.file_withdrawal(w["id"], imp))
        validate_success(api_client.cancel_withdrawal(w["id"], imp))

        end = get_weekly_entry(entry["id"])
        for field in ("entered_value_cents", "duty_total_cents", "mpf_uncapped_cents",
                      "mpf_cents", "per_shipment_mpf_cents", "mpf_savings_cents"):
            assert end[field] == 0, (
                f"after cancel the empty member set pins {field} to 0, got {end[field]}"
            )
