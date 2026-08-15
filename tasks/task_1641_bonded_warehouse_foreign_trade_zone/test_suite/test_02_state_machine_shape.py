"""Non-linear state-machine shapes: the Admission revision cycle and the
Withdrawal FILED fork into DUTY_PAID vs EXPORTED."""
from test_helpers import (
    admit_admission,
    api_client,
    create_admission,
    create_filed_withdrawal,
    create_withdrawal,
    create_zone,
    file_withdrawal,
    get_lot,
    get_success_data,
    make_customs_officer_headers,
    make_importer_headers,
    setup_zone_with_lot,
    submit_admission,
    validate_success,
)


class TestAdmissionSubmitReturnCycle:
    """DRAFT -> SUBMITTED -> DRAFT revision loop, terminable by admit."""

    def test_submit_return_cycle_repeats_then_admits(self):
        """PRD §3.2: "If the documentation is deficient, customs returns it, moving
        the admission from `SUBMITTED` back to `DRAFT`; the submit–return loop may
        repeat as many times as needed."
        PRD §3.2: "If the documentation is sound, customs admits the merchandise,
        moving the admission from `SUBMITTED` to the terminal `ADMITTED` state."

        Design: Difficulty/non_linear_state_machine/admission_submit_return_cycle
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Cycle Zone", zone_code="Z-CYC")
        imp = make_importer_headers("imp-1")
        customs = make_customs_officer_headers()
        a = create_admission(zone["id"], importer_id="imp-1", description="Dairy",
                             hts_code="0401.10", quantity=4, unit_value_cents=2500,
                             zone_status="NON_PRIVILEGED_FOREIGN")

        s1 = validate_success(api_client.submit_admission(a["id"], imp))
        assert s1["status"] == "SUBMITTED", f"after first submit: expected SUBMITTED, got {s1['status']}"

        s2 = validate_success(api_client.return_admission(a["id"], customs))
        assert s2["status"] == "DRAFT", f"after customs return: expected DRAFT (cycle), got {s2['status']}"

        s3 = validate_success(api_client.submit_admission(a["id"], imp))
        assert s3["status"] == "SUBMITTED", f"after second submit: expected SUBMITTED, got {s3['status']}"

        s4 = validate_success(api_client.admit_admission(a["id"], customs))
        assert s4["status"] == "ADMITTED", f"after admit: expected terminal ADMITTED, got {s4['status']}"

    def test_admit_stamps_admission_date_from_logical_clock(self):
        """PRD §3.2: "Admitting stamps `admission_date` from the logical clock (the
        field is null beforehand)"
        PRD §2.5: "At server startup the logical clock reads exactly
        2026-08-01T00:00:00Z"

        Design: Difficulty/non_linear_state_machine/admission_submit_return_cycle
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Cycle Zone 2", zone_code="Z-CY2")
        imp = make_importer_headers("imp-1")
        customs = make_customs_officer_headers()
        a = create_admission(zone["id"], importer_id="imp-1", description="Dairy",
                             hts_code="0401.10", quantity=4, unit_value_cents=2500,
                             zone_status="NON_PRIVILEGED_FOREIGN")
        assert a.get("admission_date") is None, "admission_date must be null before admission"

        submit_admission(a["id"], importer_id="imp-1")
        admitted = validate_success(api_client.admit_admission(a["id"], customs))
        assert admitted["admission_date"] == "2026-08-01T00:00:00Z", (
            f"admission_date must be stamped from the logical clock default "
            f"2026-08-01T00:00:00Z, got {admitted['admission_date']!r}"
        )
        assert admitted["status"] == "ADMITTED"


class TestWithdrawalConsumptionExportFork:
    """From FILED the CONSUMPTION branch ends DUTY_PAID/COLLECTED while the
    EXPORT branch ends EXPORTED/EXTINGUISHED."""

    def _setup_lot(self):
        return setup_zone_with_lot(
            quantity=10, unit_value_cents=2000, hts_code="8542.31",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Fork Zone", zone_code="Z-FRK",
        )

    def test_consumption_branch_ends_duty_paid_collected(self):
        """PRD §3.5: "For a `CONSUMPTION` withdrawal, the owning importer pays the
        assessed duty, moving it to `DUTY_PAID` and setting `duty_outcome` to
        `COLLECTED`"

        Design: Difficulty/non_linear_state_machine/withdrawal_consumption_export_fork
        """
        zone, _a, lot = self._setup_lot()
        imp = make_importer_headers("imp-1")
        w = create_filed_withdrawal(zone["id"], lot["id"], quantity=5,
                                    withdrawal_type="CONSUMPTION", importer_id="imp-1")
        # 5 x 2000 x 0.04 = 400
        assert w["assessed_duty_cents"] == 400, (
            f"assessed duty at filing: expected 400, got {w['assessed_duty_cents']}"
        )
        paid = validate_success(api_client.pay_duty_withdrawal(w["id"], imp))
        assert paid["status"] == "DUTY_PAID", f"expected DUTY_PAID, got {paid['status']}"
        assert paid["duty_outcome"] == "COLLECTED", (
            f"expected duty_outcome COLLECTED, got {paid['duty_outcome']}"
        )

    def test_export_branch_ends_exported_extinguished(self):
        """PRD §3.5: "For an `EXPORT` withdrawal, a `CustomsOfficer` confirms the
        export, moving it to `EXPORTED` and setting `duty_outcome` to
        `EXTINGUISHED` — export extinguishes the deferred duty and no duty is
        collected"

        Design: Difficulty/non_linear_state_machine/withdrawal_consumption_export_fork
        """
        zone, _a, lot = self._setup_lot()
        customs = make_customs_officer_headers()
        w = create_filed_withdrawal(zone["id"], lot["id"], quantity=5,
                                    withdrawal_type="EXPORT", importer_id="imp-1")
        # assessed at filing with the same formula: 5 x 2000 x 0.04 = 400
        assert w["assessed_duty_cents"] == 400
        exported = validate_success(api_client.confirm_export_withdrawal(w["id"], customs))
        assert exported["status"] == "EXPORTED", f"expected EXPORTED, got {exported['status']}"
        assert exported["duty_outcome"] == "EXTINGUISHED", (
            f"expected duty_outcome EXTINGUISHED, got {exported['duty_outcome']}"
        )

    def test_fork_branches_share_filed_origin_and_deplete_lot(self):
        """PRD §3.5: "The lot is then debited — `quantity_on_hand` decreased and
        `cumulative_withdrawn` increased by the withdrawal `quantity` — a lot left
        at zero on hand transitions from `IN_ZONE` to `DEPLETED`"

        Design: Difficulty/non_linear_state_machine/withdrawal_consumption_export_fork
        """
        zone, _a, lot = self._setup_lot()
        imp = make_importer_headers("imp-1")
        customs = make_customs_officer_headers()

        w_c = create_filed_withdrawal(zone["id"], lot["id"], quantity=5,
                                      withdrawal_type="CONSUMPTION", importer_id="imp-1")
        paid = validate_success(api_client.pay_duty_withdrawal(w_c["id"], imp))
        assert paid["status"] == "DUTY_PAID" and paid["duty_outcome"] == "COLLECTED"

        w_x = create_filed_withdrawal(zone["id"], lot["id"], quantity=5,
                                      withdrawal_type="EXPORT", importer_id="imp-1")
        exported = validate_success(api_client.confirm_export_withdrawal(w_x["id"], customs))
        assert exported["status"] == "EXPORTED" and exported["duty_outcome"] == "EXTINGUISHED"

        lot_after = get_lot(lot["id"])
        assert lot_after["quantity_on_hand"] == 0, (
            f"5 + 5 of admitted 10 withdrawn: expected 0 on hand, got {lot_after['quantity_on_hand']}"
        )
        assert lot_after["status"] == "DEPLETED", (
            f"lot at zero on hand must be DEPLETED, got {lot_after['status']}"
        )
