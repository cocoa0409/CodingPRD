"""Transitive cascades: the reconciliation-submit audit-hold cascade and the
withdrawal-file lot-depletion cascade."""
from test_helpers import (
    api_client,
    create_filed_withdrawal,
    create_reconciliation,
    create_weekly_entry,
    create_withdrawal,
    create_zone,
    file_withdrawal,
    get_lot,
    get_weekly_entry,
    get_zone,
    get_success_data,
    make_importer_headers,
    make_zone_operator_headers,
    setup_zone_with_lot,
    submit_reconciliation,
    validate_success,
)


class TestAuditBreachCascadeFreezesEntries:
    """Depth-4 cascade: recon flagged -> zone AUDIT_HOLD -> OPEN entry FROZEN ->
    attached FILED withdrawal detached/restored -> lot DEPLETED->IN_ZONE and zone
    aggregates recomputed."""

    def _setup_flagged_recon(self):
        zone, _a, lot = setup_zone_with_lot(
            quantity=5, unit_value_cents=1000, hts_code="0401.10",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Cascade Zone", zone_code="Z-CAS",
        )
        entry = create_weekly_entry(zone["id"], week_start_date="2026-07-27T00:00:00Z",
                                    importer_id="imp-1")
        # Withdraw all 5 units, attached to the entry -> lot DEPLETED.
        w = create_filed_withdrawal(zone["id"], lot["id"], quantity=5,
                                    withdrawal_type="CONSUMPTION",
                                    weekly_entry_id=entry["id"], importer_id="imp-1")
        # Sanity: lot depleted, zone aggregates relieved.
        assert get_lot(lot["id"])["status"] == "DEPLETED"
        z_mid = get_zone(zone["id"])
        assert z_mid["active_lot_count"] == 0
        assert z_mid["deferred_duty_exposure_cents"] == 0

        # book: receipts 5000 - withdrawals 5000 = 0; book==0 with physical!=0 -> pct 100 > 0.5
        recon = create_reconciliation(zone["id"], zone_year=2026,
                                      beginning_value_cents=0, physical_ending_value_cents=1000)
        return zone, lot, entry, w, recon

    def test_flagged_recon_freezes_entry_and_restores_lot(self):
        """PRD §3.7: "The zone's `compliance_posture` moves from `NORMAL` to
        `AUDIT_HOLD`. Every weekly entry of that zone in `OPEN` status is frozen to
        `FROZEN`. Every withdrawal in `FILED` status attached to a freezing entry is
        forced back to `DRAFT`, its `weekly_entry_id` is cleared to null, and its
        quantity is restored to its lot: the lot's `quantity_on_hand` is increased
        by the withdrawal's `quantity` and its `cumulative_withdrawn` is decreased
        by the same amount."

        Design: Difficulty/transitive_cascade/audit_breach_cascade_freezes_entries
        """
        zone, lot, entry, w, recon = self._setup_flagged_recon()
        op = make_zone_operator_headers()

        submitted = validate_success(api_client.submit_annual_reconciliation(recon["id"], op))
        assert submitted["audit_flagged"] is True, (
            f"book_ending 0 with physical 1000 pins discrepancy_pct 100 > 0.5; "
            f"got pct={submitted.get('discrepancy_pct')}"
        )

        zone_after = get_zone(zone["id"])
        assert zone_after["compliance_posture"] == "AUDIT_HOLD", (
            f"hop 1: expected AUDIT_HOLD, got {zone_after['compliance_posture']}"
        )

        entry_after = get_weekly_entry(entry["id"])
        assert entry_after["status"] == "FROZEN", (
            f"hop 2: expected FROZEN, got {entry_after['status']}"
        )

        w_after = get_success_data(api_client.get_withdrawal(w["id"], op))
        assert w_after["status"] == "DRAFT", (
            f"hop 3: withdrawal must be forced back to DRAFT, got {w_after['status']}"
        )
        assert w_after.get("weekly_entry_id") is None, (
            f"hop 3: weekly_entry_id must be cleared to null, got {w_after.get('weekly_entry_id')!r}"
        )

    def test_flagged_recon_restores_depleted_lot_and_zone_aggregates(self):
        """PRD §3.7: "A lot restored from zero on hand by this restoration returns
        from `DEPLETED` to `IN_ZONE`, and the zone's `active_lot_count` and
        `deferred_duty_exposure_cents` are recomputed."
        PRD §3.3: "The zone's `deferred_duty_exposure_cents` is the sum, taken over
        every lot of the zone whose status is `IN_ZONE`, of that lot's deferred-duty
        estimate: the lot's `quantity_on_hand` multiplied by its `unit_value_cents`
        and by its `duty_rate`, each lot's product rounded half up to integer cents
        before the products are summed."

        Design: Difficulty/transitive_cascade/audit_breach_cascade_freezes_entries
        """
        zone, lot, _entry, _w, recon = self._setup_flagged_recon()
        submit_reconciliation(recon["id"])

        lot_after = get_lot(lot["id"])
        assert lot_after["quantity_on_hand"] == 5, (
            f"hop 3/4: quantity restored to 5, got {lot_after['quantity_on_hand']}"
        )
        assert lot_after["status"] == "IN_ZONE", (
            f"hop 4: restored-from-zero lot must return to IN_ZONE, got {lot_after['status']}"
        )

        zone_after = get_zone(zone["id"])
        assert zone_after["active_lot_count"] == 1, (
            f"hop 4: active_lot_count must be 1 again, got {zone_after['active_lot_count']}"
        )
        # round(5 x 1000 x 0.05) = 250
        assert zone_after["deferred_duty_exposure_cents"] == 250, (
            f"hop 4: exposure round(5 x 1000 x 0.05) == 250, got "
            f"{zone_after['deferred_duty_exposure_cents']}"
        )


class TestWithdrawalFileCascadeDepletesLot:
    """Depth-3 cascade: file -> lot debited -> lot hits 0 and auto-DEPLETED ->
    zone aggregates recomputed."""

    def _setup(self):
        return setup_zone_with_lot(
            quantity=3, unit_value_cents=4000, hts_code="8542.31",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Deplete Zone", zone_code="Z-DEP",
        )

    def test_filing_exact_quantity_depletes_lot(self):
        """PRD §3.5: "The lot is then debited — `quantity_on_hand` decreased and
        `cumulative_withdrawn` increased by the withdrawal `quantity` — a lot left
        at zero on hand transitions from `IN_ZONE` to `DEPLETED`"

        Design: Difficulty/transitive_cascade/withdrawal_file_cascade_depletes_lot
        """
        zone, _a, lot = self._setup()
        w = create_filed_withdrawal(zone["id"], lot["id"], quantity=3,
                                    withdrawal_type="EXPORT", importer_id="imp-1")
        assert w["status"] == "FILED"

        lot_after = get_lot(lot["id"])
        assert lot_after["quantity_on_hand"] == 0, (
            f"hop 1: expected 0 on hand, got {lot_after['quantity_on_hand']}"
        )
        assert lot_after["cumulative_withdrawn"] == 3, (
            f"hop 1: cumulative_withdrawn must be 3, got {lot_after['cumulative_withdrawn']}"
        )
        assert lot_after["status"] == "DEPLETED", (
            f"hop 2: lot at zero must auto-transition DEPLETED, got {lot_after['status']}"
        )

    def test_depletion_recomputes_zone_aggregates(self):
        """PRD §3.3: "The zone's `active_lot_count` is the count of its lots in
        `IN_ZONE`. These aggregates are recomputed immediately whenever any lot's
        on-hand quantity changes or its membership in `IN_ZONE` changes"
        PRD §3.3: "`DEPLETED` lots contribute nothing and are excluded."

        Design: Difficulty/transitive_cascade/withdrawal_file_cascade_depletes_lot
        """
        zone, _a, lot = self._setup()
        # Before: round(3 x 4000 x 0.04) = 480 exposure, 1 active lot
        z_before = get_zone(zone["id"])
        assert z_before["deferred_duty_exposure_cents"] == 480
        assert z_before["active_lot_count"] == 1

        create_filed_withdrawal(zone["id"], lot["id"], quantity=3,
                                withdrawal_type="EXPORT", importer_id="imp-1")

        z_after = get_zone(zone["id"])
        assert z_after["active_lot_count"] == 0, (
            f"hop 3: active_lot_count must drop to 0, got {z_after['active_lot_count']}"
        )
        assert z_after["deferred_duty_exposure_cents"] == 0, (
            f"hop 3: exposure relieved to 0 by the export filing, got "
            f"{z_after['deferred_duty_exposure_cents']}"
        )
