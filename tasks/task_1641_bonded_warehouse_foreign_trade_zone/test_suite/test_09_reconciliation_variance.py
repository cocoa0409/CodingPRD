"""Reconciliation dual-variant divergence: book-derived ending vs independent
physical count, and the resulting discrepancy exposure."""
import pytest

from test_helpers import (
    api_client,
    create_admission,
    create_filed_withdrawal,
    create_reconciliation,
    create_zone,
    get_success_data,
    get_zone,
    make_zone_operator_headers,
    setup_zone_with_lot,
    submit_admission,
    admit_admission,
    submit_reconciliation,
    validate_success,
)


class TestBookVsPhysicalReconciliationVariant:
    """The book-derived algorithm (beginning + receipts - withdrawals) and the
    independent physical count legitimately diverge; the reconciliation exposes
    the delta as discrepancy_cents / discrepancy_pct."""

    def _setup(self):
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Recon Zone", zone_code="Z-REC")
        op = make_zone_operator_headers()

        a1 = create_admission(zone["id"], importer_id="imp-1", description="Processors",
                              hts_code="8542.31", quantity=10, unit_value_cents=5000,
                              zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a1["id"], importer_id="imp-1")
        admit_admission(a1["id"])
        lot1 = get_success_data(api_client.list_lots(op, params={"admission_id": a1["id"]}))[0]

        a2 = create_admission(zone["id"], importer_id="imp-1", description="Toys",
                              hts_code="9503.00", quantity=20, unit_value_cents=3000,
                              zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a2["id"], importer_id="imp-1")
        admit_admission(a2["id"])

        # One CONSUMPTION withdrawal of 4 units from lot1, FILED (value 20000).
        create_filed_withdrawal(zone["id"], lot1["id"], quantity=4,
                                withdrawal_type="CONSUMPTION", importer_id="imp-1")

        recon = create_reconciliation(zone["id"], zone_year=2026,
                                      beginning_value_cents=100000,
                                      physical_ending_value_cents=188000)
        return zone, recon

    def test_book_side_forward_derived(self):
        """PRD §3.7: "The book side is forward-derived from system records:
        `book_receipts_value_cents` is the sum, over admissions in `ADMITTED`
        status whose `admission_date` falls inside the window, of each admission's
        `quantity` multiplied by its `unit_value_cents`; `book_withdrawals_value_cents`
        is the sum, over withdrawals in `FILED`, `DUTY_PAID`, or `EXPORTED` status
        whose `withdrawal_date` falls inside the window, of each withdrawal's
        `quantity` multiplied by its lot's `unit_value_cents` — withdrawals in
        `DRAFT` or `CANCELLED` status are excluded; and `book_ending_value_cents`
        is the beginning value plus receipts minus withdrawals."

        Design: Difficulty/dual_variant_calc/book_vs_physical_reconciliation_variant
        """
        _zone, recon = self._setup()
        data = submit_reconciliation(recon["id"])
        # receipts: 10x5000 + 20x3000 = 110000
        assert data["book_receipts_value_cents"] == 110000, (
            f"book receipts 110000, got {data['book_receipts_value_cents']}"
        )
        # withdrawals: 4 x 5000 = 20000
        assert data["book_withdrawals_value_cents"] == 20000, (
            f"book withdrawals 20000, got {data['book_withdrawals_value_cents']}"
        )
        # ending: 100000 + 110000 - 20000 = 190000
        assert data["book_ending_value_cents"] == 190000, (
            f"book ending 190000, got {data['book_ending_value_cents']}"
        )

    def test_physical_count_diverges_and_exposes_discrepancy(self):
        """PRD §3.7: "The `discrepancy_cents` is the physical ending value minus
        the book ending value."
        PRD §3.7: "in all other cases it is the absolute value of the discrepancy
        divided by the book ending value, multiplied by 100, rounded half up to
        four decimal places"
        PRD §3.7: "The reconciliation is `audit_flagged` when that percentage is
        strictly greater than one-half of one percent"

        Design: Difficulty/dual_variant_calc/book_vs_physical_reconciliation_variant
        """
        zone, recon = self._setup()
        data = submit_reconciliation(recon["id"])
        # physical 188000 - book 190000 = -2000
        assert data["discrepancy_cents"] == -2000, (
            f"discrepancy -2000, got {data['discrepancy_cents']}"
        )
        # |−2000| / 190000 x 100 = 1.052631... -> 1.0526 (4dp half-up)
        assert data["discrepancy_pct"] == pytest.approx(1.0526, abs=1e-9), (
            f"discrepancy_pct 1.0526, got {data['discrepancy_pct']}"
        )
        assert data["audit_flagged"] is True, "1.0526 > 0.5 must flag"
        zone_after = get_zone(zone["id"])
        assert zone_after["compliance_posture"] == "AUDIT_HOLD", (
            f"flagged recon must move posture to AUDIT_HOLD, got {zone_after['compliance_posture']}"
        )
