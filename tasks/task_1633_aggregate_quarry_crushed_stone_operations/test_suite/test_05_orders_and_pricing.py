"""Sales orders: delivered pricing, confirmation, backorder sweep, OCC
reprice, and cancellation compensation."""
import pytest

from test_helpers import (
    ADMIN,
    MANAGER,
    SALES,
    ApiErrorId,
    adjust_stockpile,
    assert_stockpile_invariants,
    complete_run,
    confirm_order,
    create_confirmed_order,
    create_gradation_test,
    create_order,
    create_run,
    create_sales_order_payload,
    create_site,
    create_spec,
    create_stockpile,
    create_zone,
    get_order,
    get_stockpile,
    make_qc_technician_headers,
    run_output,
    setup_plant_run_site,
    start_run,
    stockpile_adjustment_payload,
    validate_error,
    validate_success,
)

QC_2 = make_qc_technician_headers("qc-2")


class TestDeliveredPriceQuote:
    def _order_qty_500(self):
        site = create_site()
        spec = create_spec()  # A57, COARSE, base 12.50
        zone = create_zone()  # base_freight_per_ton 6.00
        return create_order(site["id"], spec["id"], zone["id"],
                            quantity_tons=500)

    def test_delivered_price_material_and_freight_components(self, api):
        """PRD 3.6: "First the material component: `base_price_per_ton` is
        multiplied by a volume factor chosen by `quantity_tons` — the full
        price (a factor of 1.00) for orders of at most 100 tons; five
        percent off (a factor of 0.95) for orders above 100 tons and at
        most 1,000 tons ... rounded half-up to two decimals and stored as
        `quoted_material_per_ton`. Second, the freight component is the
        zone's `base_freight_per_ton` rounded half-up to two decimals,
        stored as `quoted_freight_per_ton`."

        Design: Difficulty/combinatorial_formula/delivered_price_multi_input_quote
        """
        order = self._order_qty_500()
        # round_half_up(12.50 x 0.95, 2) from 11.875 -> 11.88
        assert order["quoted_material_per_ton"] == pytest.approx(11.88,
                                                                 abs=1e-6)
        assert order["quoted_freight_per_ton"] == pytest.approx(6.00,
                                                                abs=1e-6)

    def test_delivered_price_surcharge_unit_and_total(self, api):
        """PRD 3.6: "Third, the two rounded components are summed, and the
        fuel surcharge is taken from that subtotal ... the rate is eight
        percent when the subtotal is below $20.00 ... with the surcharge
        rounded half-up to two decimals as `quoted_surcharge_per_ton`. The
        unit delivered price `quoted_unit_delivered_per_ton` is the sum of
        the three components, and `quoted_total_usd` is that unit price
        times `quantity_tons`, rounded half-up to two decimals. Rounding is
        pinned per component: round each component first, then sum — never
        round once at the end."

        Design: Difficulty/combinatorial_formula/delivered_price_multi_input_quote
        """
        order = self._order_qty_500()
        # subtotal 17.88 < 20.00 -> 8% -> round_half_up(1.4304) = 1.43
        assert order["quoted_surcharge_per_ton"] == pytest.approx(1.43,
                                                                  abs=1e-6)
        assert order["quoted_unit_delivered_per_ton"] == pytest.approx(
            19.31, abs=1e-6)
        assert order["quoted_total_usd"] == pytest.approx(9655.00, abs=1e-6)


class TestOrderLifecycleGates:
    def test_spec_retired_blocks_order_create(self, api):
        """PRD 3.4: "Retiring a specification moves it `ACTIVE` → `RETIRED`,
        which blocks the creation and the confirmation of new orders
        against it (`ERR_SPEC_RETIRED`)".

        Design: Corner/validations/spec_retired_blocks_order_create
        """
        site = create_site()
        spec = create_spec()
        zone = create_zone()
        validate_success(api.retire_product_spec(spec["id"], ADMIN))
        payload = create_sales_order_payload(site["id"], spec["id"],
                                             zone["id"], quantity_tons=30)
        resp = api.create_sales_order(payload, SALES)
        validate_error(resp, ApiErrorId.ERR_SPEC_RETIRED)

    def test_zone_inactive_blocks_order_create(self, api):
        """PRD 3.6: "Deactivating a zone moves it `ACTIVE` → `INACTIVE`;
        new order creation against an inactive zone is rejected with
        `ERR_ZONE_INACTIVE`, while existing orders keep their pinned
        prices."

        Design: Corner/validations/zone_inactive_blocks_order_create
        """
        site = create_site()
        spec = create_spec()
        zone = create_zone()
        validate_success(api.deactivate_freight_zone(zone["id"], ADMIN))
        payload = create_sales_order_payload(site["id"], spec["id"],
                                             zone["id"], quantity_tons=30)
        resp = api.create_sales_order(payload, SALES)
        validate_error(resp, ApiErrorId.ERR_ZONE_INACTIVE)


class TestConfirmAgainstQuarantinedPile:
    def _quarantined_setup(self, api):
        site = create_site()
        spec = create_spec()
        zone = create_zone()
        pile = create_stockpile(site["id"], spec["id"])
        failing = create_gradation_test(
            pile["id"], "2026-08-01T07:00:00Z",
            [{"sieve": "1.5in", "pct_passing": 80}])
        validate_success(api.confirm_gradation_test(failing["id"], QC_2))
        assert get_stockpile(pile["id"])["status"] == "QUARANTINED"
        order = create_order(site["id"], spec["id"], zone["id"],
                             quantity_tons=30)
        return site, pile, order

    def test_confirm_requires_stockpile_open_not_quarantined_error(self,
                                                                   api):
        """PRD 3.6: "the site's stockpile for the ordered specification
        must exist and stand `OPEN`, otherwise confirmation fails with
        `ERR_STOCKPILE_QUARANTINED`."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_stockpile_open_not_quarantined
        """
        _site, _pile, order = self._quarantined_setup(api)
        resp = api.confirm_sales_order(order["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_STOCKPILE_QUARANTINED)

    def test_confirm_quarantined_leaves_order_quoted_unpinned(self, api):
        """PRD 3.6: "Confirming moves the order out of `QUOTED` and freezes
        all five `quoted_` fields — `prices_pinned` becomes true". A
        rejected confirmation does neither: the order stays `QUOTED` with
        `prices_pinned` false and the pile stays `QUARANTINED`.

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_stockpile_open_not_quarantined
        """
        _site, pile, order = self._quarantined_setup(api)
        validate_error(api.confirm_sales_order(order["id"], SALES),
                       ApiErrorId.ERR_STOCKPILE_QUARANTINED)
        order = get_order(order["id"])
        assert order["status"] == "QUOTED"
        assert order["prices_pinned"] is False
        assert get_stockpile(pile["id"])["status"] == "QUARANTINED"


class TestConfirmCancelRoundtrip:
    def _confirmed_order_30(self):
        site = create_site()
        spec = create_spec()
        zone = create_zone()
        pile = create_stockpile(site["id"], spec["id"])
        pile = adjust_stockpile(pile, 80.0)
        order = create_order(site["id"], spec["id"], zone["id"],
                             quantity_tons=30)
        return pile, order

    def test_confirm_reserves_quantity_and_preserves_invariant(self, api):
        """PRD 3.6: "when the pile's `available_tons` is at least
        `quantity_tons` — equality confirms — the order lands `QUOTED` →
        `CONFIRMED`, its `stockpile_id` is set, and the pile's
        `reserved_tons` gains `quantity_tons`".
        PRD 3.4: "One invariant governs the pile at all times:
        `available_tons` always equals `on_hand_tons` minus
        `reserved_tons`".

        Design: Difficulty/compensating_invariant/order_confirm_cancel_roundtrip_conserves_reserved_tons
        """
        pile, order = self._confirmed_order_30()
        pile = get_stockpile(pile["id"])
        assert pile["on_hand_tons"] == pytest.approx(80.0, abs=1e-6)
        assert pile["reserved_tons"] == pytest.approx(0.0, abs=1e-9)
        order = confirm_order(order["id"])
        assert order["status"] == "CONFIRMED"
        assert order["stockpile_id"] == pile["id"]
        pile = get_stockpile(pile["id"])
        assert pile["reserved_tons"] == pytest.approx(30.0, abs=1e-6)
        assert pile["available_tons"] == pytest.approx(50.0, abs=1e-6)
        assert_stockpile_invariants(pile)

    def test_cancel_releases_full_reservation(self, api):
        """PRD 3.6: "a confirmed order releases its full `quantity_tons`
        reservation".

        Design: Difficulty/compensating_invariant/order_confirm_cancel_roundtrip_conserves_reserved_tons
        """
        pile, order = self._confirmed_order_30()
        confirm_order(order["id"])
        order = validate_success(api.cancel_sales_order(order["id"], SALES))
        assert order["status"] == "CANCELLED"
        pile = get_stockpile(pile["id"])
        assert pile["reserved_tons"] == pytest.approx(0.0, abs=1e-9)
        assert pile["available_tons"] == pytest.approx(80.0, abs=1e-6)
        assert_stockpile_invariants(pile)


class TestBackorderSweep:
    def test_allocation_sweep_fifo_no_skip(self, api):
        """PRD 3.6: "the system walks the `BACKORDERED` orders of the same
        site and specification in strict first-in-first-out order: ranked
        by `created_at` ascending ... Each order promotes `BACKORDERED` →
        `CONFIRMED` only if, at its turn, the pile's `available_tons`
        covers its full `quantity_tons` ... The sweep stops at the first
        order that does not fit — no skipping ahead to smaller orders
        behind it."

        Design: Corner/calculations/allocation_sweep_fifo_no_skip
        """
        site = create_site()
        spec = create_spec()
        zone = create_zone()
        pile = create_stockpile(site["id"], spec["id"])
        o1 = create_confirmed_order(site["id"], spec["id"], zone["id"],
                                    customer_name="ACME", quantity_tons=40)
        assert o1["status"] == "BACKORDERED"
        o2 = create_confirmed_order(site["id"], spec["id"], zone["id"],
                                    customer_name="BETA", quantity_tons=40)
        assert o2["status"] == "BACKORDERED"
        pile = get_stockpile(pile["id"])
        payload = stockpile_adjustment_payload(50.0, pile["version"],
                                               reason="survey credit")
        validate_success(api.adjust_stockpile(pile["id"], payload, MANAGER))
        assert get_order(o1["id"])["status"] == "CONFIRMED"
        assert get_order(o2["id"])["status"] == "BACKORDERED"
        pile = get_stockpile(pile["id"])
        assert pile["on_hand_tons"] == pytest.approx(50.0, abs=1e-6)
        assert pile["reserved_tons"] == pytest.approx(40.0, abs=1e-6)
        assert pile["available_tons"] == pytest.approx(10.0, abs=1e-6)

    def _backordered_order_then_credit(self, api):
        """Fired-shot site; order for 30 t backorders (pile empty); a run
        then credits 620 t to the pile."""
        ctx = setup_plant_run_site()
        zone = create_zone()
        order = create_confirmed_order(ctx["site"]["id"], ctx["spec"]["id"],
                                       zone["id"], quantity_tons=30)
        assert order["status"] == "BACKORDERED"
        run = create_run(ctx)
        start_run(run["id"])
        run = complete_run(run["id"], 620.0, [run_output(
            ctx["pile"]["id"], ctx["spec"]["id"], 620.0)])
        return ctx, order, run

    def test_run_credit_promotes_backordered_order(self, api):
        """PRD 3.6: "Whenever a pile is credited — a plant-run completion
        or a positive manual adjustment — and the pile stands `OPEN`, the
        system walks the `BACKORDERED` orders of the same site and
        specification ... Each order promotes `BACKORDERED` → `CONFIRMED`
        only if, at its turn, the pile's `available_tons` covers its full
        `quantity_tons`; promotion reserves that tonnage in
        `reserved_tons`."

        Design: Difficulty/transitive_cascade/plant_run_credit_backorder_sweep_cascade
        """
        ctx, order, run = self._backordered_order_then_credit(api)
        assert run["production_status"] == "COMPLETED"
        order = get_order(order["id"])
        assert order["status"] == "CONFIRMED"
        assert order["prices_pinned"] is True

    def test_run_credit_sweep_updates_pile_reserved(self, api):
        """PRD 3.5: "each output pile's `on_hand_tons` gains its credited
        `tons` with `available_tons` recomputed; and each credited pile
        triggers the backorder allocation sweep of §3.6."

        Design: Difficulty/transitive_cascade/plant_run_credit_backorder_sweep_cascade
        """
        ctx, order, _run = self._backordered_order_then_credit(api)
        pile = get_stockpile(ctx["pile"]["id"])
        assert pile["on_hand_tons"] == pytest.approx(620.0, abs=1e-6)
        assert pile["reserved_tons"] == pytest.approx(30.0, abs=1e-6)
        assert pile["available_tons"] == pytest.approx(590.0, abs=1e-6)
        assert_stockpile_invariants(pile)


class TestConfirmImmediateConsistency:
    def test_immediate_consistency_confirm_response(self, api):
        """PRD 2.9: "Cascades never span requests: every mutation a request
        triggers, however indirect, is committed and visible within that
        request's response."
        PRD 3.6: "Confirming moves the order out of `QUOTED` and freezes
        all five `quoted_` fields — `prices_pinned` becomes true — so that
        identical inputs afterwards produce the pinned values even if the
        price book later changes".

        Design: Corner/consistency_model/immediate_consistency_confirm_response
        """
        site = create_site()
        spec = create_spec()
        zone = create_zone()
        pile = create_stockpile(site["id"], spec["id"])
        adjust_stockpile(pile, 200.0)
        order = create_order(site["id"], spec["id"], zone["id"],
                             quantity_tons=30)
        confirmed = validate_success(api.confirm_sales_order(order["id"],
                                                             SALES))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["prices_pinned"] is True
        assert confirmed["stockpile_id"] == pile["id"]
        # qty 30 <= 100 -> factor 1.00 -> material 12.50; subtotal 18.50 ->
        # surcharge round_half_up(18.50 x 0.08, 2) == 1.48.
        assert confirmed["quoted_material_per_ton"] == pytest.approx(
            12.50, abs=1e-6)
        assert confirmed["quoted_surcharge_per_ton"] == pytest.approx(
            1.48, abs=1e-6)
        assert confirmed["quoted_unit_delivered_per_ton"] == pytest.approx(
            19.98, abs=1e-6)
        assert confirmed["quoted_total_usd"] == pytest.approx(599.40,
                                                              abs=1e-6)


class TestOrderRepriceOcc:
    def test_occ_order_reprice_stale_version(self, api):
        """PRD 2.8: "In each case, if the supplied value does not equal the
        resource's current `version` — because an accepted write (a
        production credit, a ticket draw, a reservation, a prior adjustment,
        a prior release, or a prior reprice) has advanced it since the
        client last read the resource — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated."

        Design: Corner/complexity_layers/occ_order_reprice_stale_version
        """
        site = create_site()
        spec = create_spec()
        zone = create_zone()
        order = create_order(site["id"], spec["id"], zone["id"],
                             quantity_tons=500)
        order_v = order["version"]
        payload = {"expected_sales_order_version": order_v}
        order = validate_success(
            api.reprice_sales_order(order["id"], payload, SALES))
        assert order["version"] == order_v + 1
        assert order["status"] == "QUOTED"
        # Price book unchanged: the requote reproduces the same numbers.
        assert order["quoted_unit_delivered_per_ton"] == pytest.approx(
            19.31, abs=1e-6)
        resp = api.reprice_sales_order(order["id"],
                                       {"expected_sales_order_version":
                                        order_v}, SALES)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_order(order["id"])["status"] == "QUOTED"
