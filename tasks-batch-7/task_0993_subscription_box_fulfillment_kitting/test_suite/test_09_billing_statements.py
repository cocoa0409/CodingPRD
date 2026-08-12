"""Billing statements: provisional vs final variants, per-line rounding,
postage reconciliation cascades, the dispute wallet cycle, and the
period-end and role gates on finalize.

Covers PRD §3.7 (statements) and §3.5 (wave cancel effects).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_billing_statement,
    assign_and_manifest,
    create_active_plan_with_bom,
    create_client,
    create_run,
    create_stocked_component,
    create_wave,
    get_shipment,
    get_statement,
    get_statement_for_client,
    import_named_subscribers,
    list_run_shipments,
    make_client_ops_headers,
    resolve_dispute_payload,
    run_to_kitted,
    set_clock,
    setup_kitted_scenario,
    validate_error,
    validate_success,
    TEST_USERS,
)

WAREHOUSE = TEST_USERS["warehouse_ops_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


class TestStatementVariants:
    def _setup_dv1(self):
        """Run kitted 1 of planned 2 at price 3000; statement PROVISIONAL.
        A wave manifest over the kept STAGED shipment then fires the
        PRD §3.7 provisional recompute trigger ("a label purchase at wave
        manifest") so the stored amounts reflect the now-KITTED run set."""
        env = setup_kitted_scenario(
            "DV1", num_subscribers=2, actual_kitted_count=1,
            qty_per_box=1, stock=500, price_per_box_cents=3000,
            shipping_weight_grams=1000, wallet_cents=1000000, zone=2)
        staged_ids = [s["id"] for s in env["shipments"]
                      if s["fulfill_status"] == "STAGED"]
        wave = create_wave()
        assign_and_manifest(wave["id"], staged_ids)
        return env

    def test_statement_provisional_variant_bills_planned_boxes(self):
        """PRD §3.7: "Thereafter, while the statement is `PROVISIONAL`, five
        events each trigger a full provisional recompute: a run lock (the
        find-or-create itself), a label purchase at wave manifest, a label
        void, a wave cancel, and a return resolved as `REFUND`." PRD §3.7:
        "Step two fixes the volume basis: the sum of `planned_box_count`
        across the run set in the provisional variant, or of
        `kitted_box_count` in the final variant."

        Design: Difficulty/dual_variant_calc/statement_provisional_vs_final_variant_divergence
        """
        env = self._setup_dv1()
        client = env["client"]
        statement = get_statement_for_client(client["id"])
        assert_billing_statement(statement)
        assert statement["status"] == "PROVISIONAL"
        # Provisional: planned 2 x 3000 with volume 2 below the 200 tier.
        assert statement["box_charge_cents"] == 6000, (
            f"provisional variant bills planned boxes: expected 6000, got "
            f"{statement['box_charge_cents']}"
        )
        assert statement["discount_pct"] == 0
        # One PURCHASED label, 1000 g in zone 2: 2 slabs, 320 + 2 x 40 = 400,
        # raised to the 450 GROUND minimum.
        assert statement["postage_cents"] == 450
        assert statement["net_cents"] == 6450
        wallet = validate_success(api_client.get_client(client["id"], BILLING))
        assert wallet["credit_balance_cents"] == 1000000, \
            "the wallet is not debited while the statement is PROVISIONAL"

    def test_statement_final_variant_diverges_to_kitted_boxes(self):
        """PRD §3.7: "the run's boxes are its `planned_box_count` in the
        provisional variant or its `kitted_box_count` in the final variant".
        PRD §3.7: "The final variant then recomputes and overwrites
        `box_charge_cents`, `postage_cents`, `refund_credit_cents`,
        `discount_pct`, and `net_cents`". PRD §3.7: "On success the wallet is
        debited by `net_cents`".

        Design: Difficulty/dual_variant_calc/statement_provisional_vs_final_variant_divergence
        """
        env = self._setup_dv1()
        client = env["client"]
        statement = get_statement_for_client(client["id"])
        assert statement["box_charge_cents"] == 6000, \
            "pre-finalize provisional charge uses planned_box_count (2 x 3000)"

        set_clock("2026-06-01T00:00:00Z")
        finalized = validate_success(api_client.finalize_statement(statement["id"],
                                                                   BILLING))
        assert_billing_statement(finalized)
        assert finalized["status"] == "FINALIZED"
        # Final: kitted 1 x 3000 — the variants diverge because kitted != planned.
        assert finalized["box_charge_cents"] == 3000, (
            f"final variant bills kitted boxes: expected 3000, got "
            f"{finalized['box_charge_cents']}"
        )
        # Postage is identical in both variants: the PURCHASED label stays 450.
        assert finalized["postage_cents"] == 450
        assert finalized["net_cents"] == 3450

        wallet = validate_success(api_client.get_client(client["id"], BILLING))
        assert wallet["credit_balance_cents"] == 996550, (
            f"wallet debited by net 3450: expected 996550, got "
            f"{wallet['credit_balance_cents']}"
        )


class TestStatementRoundingOrder:
    def _setup_cf2(self):
        """Three plans, 67 subscribers each, price 199; one run per plan,
        kitted 67. Shared component stocked 1000. Returns (client, one
        STAGED shipment id) so a test can fire a provisional recompute
        trigger via a wave manifest."""
        set_clock()
        client = create_client(wallet_cents=200000, name="CF2 Client",
                               billing_email="cf2@acme.test")
        component = create_stocked_component("CMP-CF2", 1000)
        run = None
        for suffix in ("A", "B", "C"):
            plan, _rev = create_active_plan_with_bom(
                client["id"], f"PL-RR-{suffix}", [(component["id"], 1)],
                price_per_box_cents=199, shipping_weight_grams=300,
                name=f"RR Box {suffix}")
            import_named_subscribers(
                plan["id"], client["id"],
                [(f"rr{suffix.lower()}{i:02d}@x.test", 2) for i in range(1, 68)])
            run = create_run(plan["id"])
            run_to_kitted(run["id"], 67)
        staged = list_run_shipments(run["id"], fulfill_status="STAGED")
        return client, staged[0]["id"]

    def test_statement_provisional_per_line_rounding(self):
        """PRD §3.7: "Step three sets `discount_pct`: 10 when the volume basis
        reaches at least 500 boxes, else 5 when it reaches at least 200 boxes,
        else 0." PRD §3.7: "Each run's line charge is rounded half-up to whole
        cents first, and only then are the rounded line charges summed —
        summing unrounded amounts and rounding once at the end is a rejected
        interpretation." PRD §3.7: "five events each trigger a full
        provisional recompute: a run lock (the find-or-create itself), a
        label purchase at wave manifest, a label void, a wave cancel, and a
        return resolved as `REFUND`."

        Design: Difficulty/combinatorial_formula/statement_per_line_rounding_order
        """
        client, shipment_id = self._setup_cf2()
        # Fire the label-purchase recompute trigger so the provisional
        # variant recomputes over the three KITTED runs.
        wave = create_wave()
        assign_and_manifest(wave["id"], [shipment_id])
        statement = get_statement_for_client(client["id"])
        # Volume basis 201 >= 200 -> 5%; per line round_half_up(199*67*0.95)
        # = 12666; three lines -> 37998 (sum-then-round would give 37999).
        assert statement["discount_pct"] == 5, (
            f"planned volume 201 reaches the 200-box tier: "
            f"{statement['discount_pct']}"
        )
        assert statement["box_charge_cents"] == 37998, (
            f"per-line rounding pins 3 x 12666 = 37998, got "
            f"{statement['box_charge_cents']}"
        )
        # The manifested 300 g zone-2 GROUND label: 1 slab, 320 + 40 = 360,
        # raised to the 450 minimum.
        assert statement["postage_cents"] == 450

    def test_statement_final_per_line_rounding(self):
        """PRD §3.7: "Each run's line charge is rounded half-up to whole cents
        first, and only then are the rounded line charges summed — summing
        unrounded amounts and rounding once at the end is a rejected
        interpretation."

        Design: Difficulty/combinatorial_formula/statement_per_line_rounding_order
        """
        client, _shipment_id = self._setup_cf2()
        statement = get_statement_for_client(client["id"])

        set_clock("2026-06-01T00:00:00Z")
        finalized = validate_success(api_client.finalize_statement(statement["id"],
                                                                   BILLING))
        assert finalized["box_charge_cents"] == 37998, (
            f"kitted equals planned here, so the pinned per-line rounding "
            f"must reproduce 37998, got {finalized['box_charge_cents']}"
        )
        assert finalized["discount_pct"] == 5
        assert finalized["net_cents"] == 37998
        assert finalized["status"] == "FINALIZED"


class TestWaveCancelStatementCascade:
    def _setup_tc2(self):
        """Two boxes manifested at postage 485 each (1200 g, zone 3, GROUND);
        statement postage 970."""
        env = setup_kitted_scenario(
            "TC2", num_subscribers=2, actual_kitted_count=2,
            qty_per_box=1, stock=100, price_per_box_cents=2000,
            shipping_weight_grams=1200, zone=3)
        shipment_ids = [s["id"] for s in env["shipments"]]
        wave = create_wave("USPS", "GROUND", "2026-05-10T10:00:00Z",
                           "2026-05-10T12:00:00Z")
        assign_and_manifest(wave["id"], shipment_ids)
        return env, wave, shipment_ids

    def test_wave_cancel_reverts_shipments_and_voids_labels(self):
        """PRD §3.5: "From `MANIFESTED` (`MANIFESTED → CANCELLED`), each
        manifested shipment likewise reverts `MANIFESTED → STAGED` with
        `wave_id` cleared, every `PURCHASED` label flips to `VOIDED`, the
        period's statement (if any) recomputes its provisional postage, and
        the wave's `version` increments."

        Design: Difficulty/transitive_cascade/wave_cancel_cascade_to_statement_postage
        """
        _env, wave, shipment_ids = self._setup_tc2()
        cancelled = validate_success(api_client.cancel_wave(wave["id"], WAREHOUSE))
        assert cancelled["status"] == "CANCELLED"

        for shipment_id in shipment_ids:
            shipment = get_shipment(shipment_id)
            assert shipment["fulfill_status"] == "STAGED", \
                "manifested shipment reverts to STAGED on wave cancel"
            assert shipment["label_status"] == "VOIDED", \
                "purchased label flips to VOIDED"
            assert shipment["wave_id"] is None, "wave_id is cleared"

    def test_wave_cancel_recomputes_statement_postage(self):
        """PRD §3.7: "Step six sums, into `postage_cents`, the `postage_cents`
        of every shipment of the run set whose `label_status` is `PURCHASED` —
        identical in both variants, which is why voided labels and wave cancels
        move the provisional number."

        Design: Difficulty/transitive_cascade/wave_cancel_cascade_to_statement_postage
        """
        env, wave, _shipment_ids = self._setup_tc2()
        client_id = env["client"]["id"]
        statement = get_statement_for_client(client_id)
        assert statement["postage_cents"] == 970, (
            f"two purchased labels at 485: expected 970, got "
            f"{statement['postage_cents']}"
        )
        assert statement["box_charge_cents"] == 4000

        validate_success(api_client.cancel_wave(wave["id"], WAREHOUSE))

        after = get_statement(statement["id"])
        assert after["postage_cents"] == 0, (
            f"only PURCHASED labels count, so voided labels drop postage to "
            f"0, got {after['postage_cents']}"
        )
        assert after["box_charge_cents"] == 4000, \
            "box charges are untouched by a wave cancel"
        assert after["status"] == "PROVISIONAL", \
            "a wave cancel never finalizes the statement"


class TestDisputeWalletCycle:
    def _setup_finalized_ci2(self):
        """Run kitted 1 at price 2000; statement finalized at period end
        (net 2000, wallet 100000 -> 98000)."""
        env = setup_kitted_scenario(
            "CI2", num_subscribers=1, actual_kitted_count=1,
            qty_per_box=1, stock=10, price_per_box_cents=2000,
            shipping_weight_grams=1000, wallet_cents=100000, zone=2)
        statement = get_statement_for_client(env["client"]["id"])
        set_clock("2026-06-01T00:00:00Z")
        finalized = validate_success(api_client.finalize_statement(statement["id"],
                                                                   BILLING))
        assert finalized["net_cents"] == 2000
        return env, finalized

    def test_dispute_credits_full_net_back_to_wallet(self):
        """PRD §3.7: "moves the statement `FINALIZED → DISPUTED`, which credits
        the wallet back in full by adding `net_cents` to
        `credit_balance_cents` as a provisional refund while the dispute is
        open".

        Design: Difficulty/compensating_invariant/dispute_resolve_zero_adjustment_conserves_wallet
        """
        env, statement = self._setup_finalized_ci2()
        client_id = env["client"]["id"]
        post_finalize = validate_success(api_client.get_client(client_id, BILLING))
        assert post_finalize["credit_balance_cents"] == 98000

        disputed = validate_success(
            api_client.dispute_statement(statement["id"],
                                         make_client_ops_headers(client_id)))
        assert disputed["status"] == "DISPUTED"

        wallet = validate_success(api_client.get_client(client_id, BILLING))
        assert wallet["credit_balance_cents"] == 100000, (
            f"full net 2000 credited back: expected 100000, got "
            f"{wallet['credit_balance_cents']}"
        )

    def test_resolve_dispute_zero_adjustment_redebits_same_net(self):
        """PRD §3.7: "Resolution records the adjustment, reduces `net_cents`
        by it, re-debits the reduced `net_cents` from the wallet, moves the
        statement `DISPUTED → FINALIZED`".

        Design: Difficulty/compensating_invariant/dispute_resolve_zero_adjustment_conserves_wallet
        """
        env, statement = self._setup_finalized_ci2()
        client_id = env["client"]["id"]
        validate_success(
            api_client.dispute_statement(statement["id"],
                                         make_client_ops_headers(client_id)))

        resolved = validate_success(
            api_client.resolve_dispute(statement["id"],
                                       resolve_dispute_payload(0), BILLING))
        assert resolved["status"] == "FINALIZED"
        assert resolved["net_cents"] == 2000, \
            "a zero adjustment leaves the net unchanged"

        wallet = validate_success(api_client.get_client(client_id, BILLING))
        assert wallet["credit_balance_cents"] == 98000, (
            f"re-debiting the unchanged net returns the wallet to exactly the "
            f"post-finalize value: expected 98000, got "
            f"{wallet['credit_balance_cents']}"
        )


class TestFinalizeGates:
    def test_finalize_before_period_end_rejected(self):
        """PRD §3.7: "The current clock must read at or after the first instant
        of the month following the statement's `period` (else
        `ERR_STATEMENT_PERIOD_OPEN`)."

        Design: Corner/validations/finalize_before_period_end_rejected
        """
        env = setup_kitted_scenario(
            "V3", num_subscribers=1, actual_kitted_count=1, stock=10,
            price_per_box_cents=2000, shipping_weight_grams=800)
        statement = get_statement_for_client(env["client"]["id"])
        set_clock("2026-05-15T00:00:00Z")

        resp = api_client.finalize_statement(statement["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OPEN)

        after = get_statement(statement["id"])
        assert after["status"] == "PROVISIONAL", \
            "a rejected finalize leaves the statement PROVISIONAL"
        wallet = validate_success(api_client.get_client(env["client"]["id"], BILLING))
        assert wallet["credit_balance_cents"] == 100000, \
            "a rejected finalize leaves the wallet untouched"

    def test_client_ops_cannot_finalize_statement(self):
        """PRD §4: POST /billing-statements/{id}/finalize is authorized for
        "BillingAdmin" only. PRD §2.1: "an authenticated caller whose role is
        not admitted, or who violates the ownership rule below, is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/client_ops_cannot_finalize_statement
        """
        env = setup_kitted_scenario(
            "RB2", num_subscribers=1, actual_kitted_count=1, stock=10,
            price_per_box_cents=1000, shipping_weight_grams=800)
        statement = get_statement_for_client(env["client"]["id"])
        set_clock("2026-06-01T00:00:00Z")

        resp = api_client.finalize_statement(
            statement["id"], make_client_ops_headers(env["client"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = get_statement(statement["id"])
        assert after["status"] == "PROVISIONAL", \
            "a forbidden finalize leaves the statement PROVISIONAL"
