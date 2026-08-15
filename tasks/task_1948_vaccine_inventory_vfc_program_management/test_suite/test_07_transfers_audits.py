"""Short-date transfers and the compliance site-visit accountability audit."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_short_date_transfer,
    assert_site_visit_audit_snapshot,
    get_lot,
    get_site,
    issue_findings,
    make_audit_in_progress,
    make_private_lot,
    make_product,
    make_public_dose,
    make_public_lot,
    make_public_lots,
    make_site,
    make_transfer,
    make_unit,
    open_and_close_excursion,
    open_excursion,
    resolve_excursion_wasted,
    set_clock,
    validate_error,
    validate_success,
)

VM = TEST_USERS["vaccine_manager_headers"]
CA = TEST_USERS["compliance_auditor_headers"]


class TestShortDateTransferConservation:
    def _setup_transfer(self, api):
        s1 = make_site()
        s2 = make_site()
        u1 = make_unit(s1["id"], unit_label="U1")
        u2 = make_unit(s2["id"], unit_label="U2")
        product = make_product()
        lot_x = make_private_lot(s1["id"], u1["id"], product["id"],
                                 quantity_on_hand=8, lot_number="LOT-X")
        transfer = make_transfer(s1["id"], lot_x["id"], s2["id"], u2["id"], 3,
                                 reason="short-dated at S1")
        return {"s1": s1, "s2": s2, "u1": u1, "u2": u2,
                "lot_x": lot_x, "transfer": transfer}

    def test_ship_decrements_source_lot(self, api):
        """PRD §3.8: "The source lot must be `AVAILABLE`
        (`ERR_LOT_NOT_AVAILABLE`) and hold at least `quantity_doses`
        (`ERR_INSUFFICIENT_STOCK`); on shipment its `quantity_on_hand`
        decreases by `quantity_doses`".

        Design: Difficulty/compensating_invariant/short_date_transfer_conserves_total_across_sites
        """
        ctx = self._setup_transfer(api)
        shipped = validate_success(
            api.ship_transfer(ctx["s1"]["id"], ctx["transfer"]["id"], VM)
        )
        assert shipped["status"] == "IN_TRANSIT"
        assert get_lot(ctx["lot_x"]["id"])["quantity_on_hand"] == 5

    def test_receive_materializes_successor_lot_and_conserves_total(self, api):
        """PRD §3.8: "Otherwise a successor lot is created at the destination
        site, inheriting `lot_number`, `expires_on`, `stock_type`, and
        `vaccine_product_id` from the source lot, stored in the destination
        unit, with `quantity_on_hand` equal to `quantity_doses`. Either way
        the transfer's `new_lot_id` is set to the destination lot".

        Design: Difficulty/compensating_invariant/short_date_transfer_conserves_total_across_sites
        """
        ctx = self._setup_transfer(api)
        validate_success(api.ship_transfer(ctx["s1"]["id"], ctx["transfer"]["id"], VM))
        received = validate_success(
            api.receive_transfer(ctx["s1"]["id"], ctx["transfer"]["id"], VM)
        )
        assert_short_date_transfer(received)
        assert received["status"] == "RECEIVED"
        new_lot = get_lot(received["new_lot_id"])
        assert new_lot["quantity_on_hand"] == 3
        assert new_lot["lot_number"] == "LOT-X"
        assert new_lot["provider_site_id"] == ctx["s2"]["id"]
        assert new_lot["stock_type"] == "PRIVATE"
        source = get_lot(ctx["lot_x"]["id"])
        assert source["quantity_on_hand"] + new_lot["quantity_on_hand"] == 8, (
            "total on-hand for LOT-X across both sites is conserved"
        )


class TestAccountabilitySnapshotVariants:
    def _setup_initiated_transfer_scenario(self, api):
        """14 public doses received (lots 10 + 4), 1 administered, and a
        3-dose transfer sitting in INITIATED (never shipped)."""
        set_clock("2026-08-01T00:00:00Z")
        site = make_site()
        site2 = make_site()
        unit = make_unit(site["id"], unit_label="U")
        unit2 = make_unit(site2["id"], unit_label="U2")
        product = make_product()
        pub = make_public_lots(site["id"], unit["id"], product["id"], [10, 4])
        lot_a, lot_b = pub["lot_ids"]
        make_public_dose(site["id"], lot_a)
        transfer = make_transfer(site["id"], lot_a, site2["id"], unit2["id"], 3,
                                 reason="short-dated")
        assert transfer["status"] == "INITIATED"
        audit = make_audit_in_progress(site["id"])
        return {"site": site, "audit": audit, "lot_a": lot_a, "lot_b": lot_b}

    def test_provisional_balance_counts_initiated_transfer(self, api):
        """PRD §2.7: "The ledger is recomputed incrementally on every event
        that touches any of its terms — allocation receipt, public-funded
        administration, excursion write-off or expiry of public stock, and
        public-stock transfer shipment. This running, provisional view counts
        transfers that have been initiated but not yet shipped, and it counts
        nothing from excursions that are still open, since no write-off
        exists yet."

        Design: Difficulty/dual_variant_calc/accountability_snapshot_provisional_vs_final_transfer_window
        """
        ctx = self._setup_initiated_transfer_scenario(api)
        site = get_site(ctx["site"]["id"])
        # received 14 - administered 1 - transferred out (INITIATED) 3 = 10
        assert site["accountability_balance_doses"] == 10, (
            f"provisional ledger must already deduct the INITIATED transfer: "
            f"14 - 1 - 3 = 10, got {site['accountability_balance_doses']}"
        )

    def test_final_snapshot_ignores_initiated_transfer(self, api):
        """PRD §3.9: "`public_doses_transferred_out` totals the
        `quantity_doses` of the site's public-stock transfers that are
        `IN_TRANSIT` or `RECEIVED` — doses physically off the shelf — while
        transfers still merely `INITIATED` do not count". "The
        `accountability_gap` is then received minus administered minus wasted
        minus transferred out".

        Design: Difficulty/dual_variant_calc/accountability_snapshot_provisional_vs_final_transfer_window
        """
        ctx = self._setup_initiated_transfer_scenario(api)
        audit = issue_findings(ctx["site"]["id"], ctx["audit"]["id"])
        assert_site_visit_audit_snapshot(audit)
        assert audit["public_doses_received"] == 14
        assert audit["public_doses_administered"] == 1
        assert audit["public_doses_transferred_out"] == 0, (
            "an INITIATED transfer is not yet physically off the shelf"
        )
        # 14 - 1 - 0 - 0 = 13: provisional and final diverge by exactly the
        # 3 doses still sitting in INITIATED.
        assert audit["accountability_gap"] == 13


class TestWastageSnapshot:
    def _setup_wastage_scenario(self, api):
        """21 public doses received (lots 20 + 1); 1 administered from the
        big lot; an excursion resolves wasted, writing off all 20 remaining
        public doses."""
        set_clock("2026-08-01T00:00:00Z")
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        pub = make_public_lots(site["id"], unit["id"], product["id"], [20, 1])
        lot_a, lot_b = pub["lot_ids"]
        make_public_dose(site["id"], lot_a)
        excursion = open_and_close_excursion(
            unit["id"], open_at="2026-08-06T08:00:00Z",
            close_at="2026-08-06T09:00:00Z",
        )
        resolved = resolve_excursion_wasted(unit["id"], excursion["id"])
        audit = make_audit_in_progress(site["id"])
        return {"site": site, "resolved": resolved, "audit": audit,
                "lot_a": lot_a, "lot_b": lot_b}

    def test_snapshot_counts_received_administered_and_wasted(self, api):
        """PRD §3.9: "`public_doses_received` totals every allocation receipt
        quantity across the site's orders, over all time.
        `public_doses_administered` counts the site's dose records whose
        `funding_source` is `PUBLIC_VFC`. `public_doses_wasted` adds the
        excursion write-offs attributed to the site's public lots — the
        `doses_written_off` of wasted resolutions — to the pre-zero on-hand
        quantities of public lots that expired."

        Design: Difficulty/combinatorial_formula/tiered_wastage_rate_boundary_rounding
        """
        ctx = self._setup_wastage_scenario(api)
        assert ctx["resolved"]["doses_written_off"] == 20, (
            "write-off sums the pre-zero on-hand of both quarantined public lots "
            "(19 + 1)"
        )
        audit = issue_findings(ctx["site"]["id"], ctx["audit"]["id"])
        assert_site_visit_audit_snapshot(audit)
        assert audit["public_doses_received"] == 21
        assert audit["public_doses_administered"] == 1
        assert audit["public_doses_wasted"] == 20

    def test_gap_and_on_hand_reconcile_at_zero(self, api):
        """PRD §3.9: "The `accountability_gap` is then received minus
        administered minus wasted minus transferred out, and
        `on_hand_public_total` sums `quantity_on_hand` across the site's
        `PUBLIC_VFC` lots in `AVAILABLE` or `QUARANTINED` status."

        Design: Difficulty/combinatorial_formula/tiered_wastage_rate_boundary_rounding
        """
        ctx = self._setup_wastage_scenario(api)
        audit = issue_findings(ctx["site"]["id"], ctx["audit"]["id"])
        assert_site_visit_audit_snapshot(audit)
        # 21 - 1 - 20 - 0 = 0; both lots are WASTED_CLOSED, so none remain on hand.
        assert audit["accountability_gap"] == 0
        assert audit["on_hand_public_total"] == 0


class TestAuditClosePassGuards:
    def test_close_pass_blocked_by_open_excursion(self, api):
        """PRD §3.9: "Closing the audit as passed requires the audit to be
        `FINDINGS_ISSUED` (`ERR_INVALID_STATE` otherwise), and then three
        conditions in order: the frozen `accountability_gap` must equal the
        `on_hand_public_total` exactly, or closure fails with
        `ERR_ACCOUNTABILITY_GAP_UNRESOLVED`; no excursion anywhere at the site
        may be `OPEN` or `UNDER_REVIEW` (`ERR_OPEN_EXCURSION_EXISTS`); and no
        borrow ticket may remain `OPEN` or `PARTIALLY_REPAID`
        (`ERR_OPEN_BORROW_TICKET_EXISTS`)."

        Design: Corner/state_machines/audit_close_pass_blocked_by_accountability_gap
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        make_public_lot(site["id"], unit["id"], product["id"], 5)
        audit = make_audit_in_progress(site["id"])
        open_excursion(unit["id"], recorded_at="2026-08-09T08:00:00Z")
        issue_findings(site["id"], audit["id"])
        resp = api.close_audit_pass(site["id"], audit["id"], CA)
        validate_error(resp, ApiErrorId.ERR_OPEN_EXCURSION_EXISTS)
