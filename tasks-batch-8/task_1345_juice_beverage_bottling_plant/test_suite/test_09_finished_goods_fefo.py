"""Finished-good lots, shelf-life dating, FEFO allocation, orders, and shipping."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, factories,
    create_customer, create_formula, set_clock, setup_completed_run,
    place_order, allocate_order, ship_allocated_order,
    get_finished_lot_for_run, create_tank, create_released_batch, quote_run,
    confirm_run, schedule_run,
)

PM = TEST_USERS["plant_manager_headers"]
QA = TEST_USERS["qa_inspector_headers"]
WH = TEST_USERS["warehouse_lead_headers"]
CSR = TEST_USERS["customer_service_rep_headers"]


class TestChannelMinShelfLife:
    def test_channel_derived_minimum_shelf_life(self, api):
        """PRD §3.9: "The order is born in `PLACED` with a channel-derived
        `min_shelf_life_days` — thirty days for `DIRECT_RETAIL`, forty-five for
        `CLUB`, twenty-one for `FOODSERVICE`, and sixty for `EXPORT`"

        Design: Corner/entities/channel_min_shelf_life_derivation
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        club = place_order(customer["id"], formula["id"], channel="CLUB",
                           requested_delivery_date="2026-08-15", units_requested=100)
        foodservice = place_order(customer["id"], formula["id"], channel="FOODSERVICE",
                                  requested_delivery_date="2026-08-15", units_requested=100)
        assert club["min_shelf_life_days"] == 45
        assert foodservice["min_shelf_life_days"] == 21


class TestShelfLifeVariants:
    def _hpp_lot_produced_2026_08_05(self):
        """HPP pipeline completed with the clock at 2026-08-05T09:00Z."""
        return setup_completed_run(
            formula_overrides={"process_type": "HPP", "target_brix": 8.0,
                               "concentrate_brix": 60.0, "claims": ["COLD_PRESSED"]},
            zone_temperature="CHILLED",
            scheduled_start_at="2026-08-05T08:00:00Z",
            scheduled_end_at="2026-08-05T12:00:00Z",
            clock_at_start="2026-08-05T09:00:00Z")

    def test_lot_carries_label_and_stability_dates(self, api):
        """PRD §3.9: "The label date, `expiry_label_date`, is the production date
        plus the formula's `shelf_life_days`. The stability date,
        `expiry_stability_date`, depends on the process: for `HPP` product it is
        the production date plus the floor of one and a half times
        `shelf_life_days`; for `PASTEURIZATION` product it is the production date
        plus `shelf_life_days` minus seven days."

        Design: Difficulty/dual_variant_calc/shelf_life_label_vs_stability_export
        """
        ctx = self._hpp_lot_produced_2026_08_05()
        lot = ctx["lot"]
        assert lot["production_date"] == "2026-08-05"
        assert lot["expiry_label_date"] == "2026-12-03"       # 2026-08-05 + 120 d
        assert lot["expiry_stability_date"] == "2027-02-01"   # + floor(120 * 1.5) d
        assert lot["units_total"] == 1000
        assert lot["status"] == "AVAILABLE"

    def test_export_reads_stability_retail_reads_label(self, api):
        """PRD §3.9: "The effective expiry is channel-dependent — `EXPORT` orders
        read the lot's `expiry_stability_date`, while every other channel reads
        `expiry_label_date`." and "The outcome is binary: the order lands in
        `ALLOCATED` when `allocated_units` equals `units_requested`, and in
        `BACKORDERED` otherwise — an empty eligible pool is not an error, merely a
        fully backordered order."

        Design: Difficulty/dual_variant_calc/shelf_life_label_vs_stability_export
        """
        ctx = self._hpp_lot_produced_2026_08_05()
        # delivery 2026-11-15: stability 2027-02-01 leaves 78 days (>= 60);
        # label 2026-12-03 leaves 18 days (< 30)
        order_exp = place_order(ctx["customer"]["id"], ctx["formula"]["id"],
                                channel="EXPORT", requested_delivery_date="2026-11-15",
                                units_requested=100)
        order_ret = place_order(ctx["customer"]["id"], ctx["formula"]["id"],
                                channel="DIRECT_RETAIL", requested_delivery_date="2026-11-15",
                                units_requested=100)
        assert order_exp["min_shelf_life_days"] == 60
        assert order_ret["min_shelf_life_days"] == 30
        allocated = allocate_order(order_exp["id"])
        assert allocated["status"] == "ALLOCATED"
        assert allocated["allocated_units"] == 100
        backordered = allocate_order(order_ret["id"])
        assert backordered["status"] == "BACKORDERED"
        assert backordered["allocated_units"] == 0


class TestPasteurizationStabilityDate:
    def test_paste_lot_dates_from_logical_clock(self, api):
        """PRD §3.9: "The label date, `expiry_label_date`, is the production date
        plus the formula's `shelf_life_days`. The stability date,
        `expiry_stability_date`, depends on the process: ... for `PASTEURIZATION`
        product it is the production date plus `shelf_life_days` minus seven
        days." and "a `production_date` taken as the calendar date of the logical
        clock at completion."

        Design: Corner/calculations/pasteurization_stability_date_computation
        """
        ctx = setup_completed_run(
            shelf_life_days=120,
            scheduled_start_at="2026-08-05T08:00:00Z",
            scheduled_end_at="2026-08-05T12:00:00Z",
            clock_at_start="2026-08-05T09:00:00Z")
        lot = ctx["lot"]
        assert lot["production_date"] == "2026-08-05"
        assert lot["expiry_label_date"] == "2026-12-03"      # +120 days
        assert lot["expiry_stability_date"] == "2026-11-26"  # +120 - 7 days
        assert lot["units_total"] == 1000
        assert lot["units_available"] == 1000
        assert lot["status"] == "AVAILABLE"


class TestFefoTiebreakAndPalletCeil:
    def test_older_lot_drained_first_and_per_lot_pallet_ceil(self, api):
        """PRD §3.9: "Lots are ranked by that effective expiry ascending, ties
        broken by lot creation order ascending, and the waterfall takes from each
        lot the lesser of its availability and the remaining need until the
        request is covered or the pool runs dry." and §2.8: "a shipment order's
        pallet count ceilings each allocated lot separately and sums those
        ceilings"

        Design: Corner/calculations/fefo_created_at_tiebreak_and_per_lot_pallet_ceil
        """
        # two runs completed on the same logical date -> two lots, identical expiry
        ctx = setup_completed_run(actual_units_filled=500, avg_fill_ml=473,
                                  planned_units=500)
        lot1 = ctx["lot"]
        # second pipeline on the same formula: fresh tank + released batch
        tank2 = create_tank()
        batch2 = create_released_batch(ctx["formula"], tank2)
        run2 = confirm_run(quote_run(ctx["customer"]["id"], ctx["formula"]["id"],
                                     planned_units=500)["id"])
        run2 = schedule_run(run2["id"], batch2["id"], ctx["line"]["id"],
                            "2026-08-11T13:00:00Z", "2026-08-11T17:00:00Z")
        set_clock("2026-08-11T14:00:00Z")
        get_success_data(api.start_run(run2["id"], TEST_USERS["production_planner_headers"]))
        get_success_data(api.complete_run(
            run2["id"],
            factories.complete_run_payload(ctx["zone"]["id"], actual_units_filled=500,
                                           avg_fill_ml=473),
            TEST_USERS["production_planner_headers"]))
        lot2 = get_finished_lot_for_run(run2["id"])
        assert lot1["expiry_label_date"] == lot2["expiry_label_date"]
        order = place_order(ctx["customer"]["id"], ctx["formula"]["id"],
                            channel="FOODSERVICE", requested_delivery_date="2026-08-20",
                            units_requested=800)
        allocated = allocate_order(order["id"])
        assert allocated["status"] == "ALLOCATED"
        assert allocated["allocated_units"] == 800
        allocs = allocated["allocations"]
        assert len(allocs) == 2
        assert allocs[0]["lot_id"] == lot1["id"] and allocs[0]["units"] == 500
        assert allocs[1]["lot_id"] == lot2["id"] and allocs[1]["units"] == 300
        # ceil(500/1440) + ceil(300/1440) == 1 + 1 == 2 (NOT ceil(800/1440) == 1)
        assert allocated["pallet_count"] == 2
        lot1_after = get_success_data(api.get_finished_lot(lot1["id"], PM))
        lot2_after = get_success_data(api.get_finished_lot(lot2["id"], PM))
        assert (lot1_after["units_available"], lot1_after["units_allocated"]) == (0, 500)
        assert (lot2_after["units_available"], lot2_after["units_allocated"]) == (200, 300)


class TestZonePalletsRecompute:
    def test_partial_then_full_ship_recomputes_pallets_and_depletes(self, api):
        """PRD §3.9: "A lot's `units_available` is what remains of `units_total`
        after `units_allocated` and `units_shipped`, and its `pallet_count` is the
        uns shipped remainder divided by the container type's pallet density,
        rounded up" and "Shipping the last units flips a lot to `DEPLETED`, at
        which point it contributes zero to its zone's occupancy."

        Design: Corner/calculations/zone_pallets_recompute_and_lot_depletion
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=473)
        lot_id = ctx["lot"]["id"]
        zone_id = ctx["zone"]["id"]
        order1 = place_order(ctx["customer"]["id"], ctx["formula"]["id"],
                             channel="FOODSERVICE", requested_delivery_date="2026-08-20",
                             units_requested=500)
        order2 = place_order(ctx["customer"]["id"], ctx["formula"]["id"],
                             channel="FOODSERVICE", requested_delivery_date="2026-08-20",
                             units_requested=500)
        shipped1 = ship_allocated_order(order1["id"])
        assert shipped1["status"] == "SHIPPED"
        assert shipped1["pallet_count"] == 1  # ceil(500/1440)
        lot_mid = get_success_data(api.get_finished_lot(lot_id, PM))
        assert lot_mid["units_shipped"] == 500
        assert lot_mid["pallet_count"] == 1  # ceil((1000-500)/1440)
        assert lot_mid["status"] == "AVAILABLE"
        zone_mid = get_success_data(api.get_zone(zone_id, PM))
        assert zone_mid["pallets_stored"] == 1
        shipped2 = ship_allocated_order(order2["id"])
        assert shipped2["status"] == "SHIPPED"
        lot_end = get_success_data(api.get_finished_lot(lot_id, PM))
        assert lot_end["units_shipped"] == 1000
        assert lot_end["status"] == "DEPLETED"
        zone_end = get_success_data(api.get_zone(zone_id, PM))
        assert zone_end["pallets_stored"] == 0


class TestFinishedLotRecall:
    def test_recall_lockdown(self, api):
        """PRD §3.9: "a `QAInspector` may recall a lot standing in `AVAILABLE` or
        `EXPIRED` (else `ERR_LOT_STATE_INVALID`), moving it to `RECALLED`." and
        "a server-minted `lot_code` of the form `FG-` followed by the production
        run's id"

        Design: Corner/state_machines/finished_lot_recall_lockdown
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=473)
        lot = ctx["lot"]
        assert lot["status"] == "AVAILABLE"
        assert lot["lot_code"] == f"FG-{ctx['run']['id']}"
        recalled = get_success_data(api.recall_finished_lot(lot["id"], QA))
        assert recalled["status"] == "RECALLED"
        resp = api.recall_finished_lot(lot["id"], QA)
        validate_error(resp, ApiErrorId.ERR_LOT_STATE_INVALID)
        assert resp.status_code == 409

    def test_recall_deallocates_allocated_order(self, api):
        """PRD §3.9: "Expiry and recall from `AVAILABLE` fire the same
        de-allocation cascade: allocation entries referencing the lot are stripped
        from shipment orders standing in `PLACED`, `ALLOCATED`, or `BACKORDERED`,
        their `allocated_units` recomputed, and any such order whose allocated
        total now falls short of its `units_requested` is demoted to
        `BACKORDERED`"

        Design: Corner/state_machines/recall_deallocates_allocated_order
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=473)
        lot_id = ctx["lot"]["id"]
        order = place_order(ctx["customer"]["id"], ctx["formula"]["id"],
                            channel="DIRECT_RETAIL", requested_delivery_date="2026-08-20",
                            units_requested=400)
        allocated = allocate_order(order["id"])
        assert allocated["status"] == "ALLOCATED"
        assert allocated["allocated_units"] == 400
        get_success_data(api.recall_finished_lot(lot_id, QA))
        order_after = get_success_data(api.get_shipment_order(order["id"], PM))
        assert order_after["status"] == "BACKORDERED"
        assert order_after["allocated_units"] == 0
        assert order_after["allocations"] == []
        lot_after = get_success_data(api.get_finished_lot(lot_id, PM))
        assert lot_after["status"] == "RECALLED"
        assert lot_after["units_allocated"] == 0
        assert lot_after["units_available"] == 1000


class TestShipGate:
    def test_ship_blocked_when_allocated_lot_recalled(self, api):
        """PRD §3.9: "Orders standing in `PICKED` keep their allocations untouched
        — the shipping gate above, not de-allocation, is what stops them." and
        "every allocated lot must still stand in `AVAILABLE` — an allocated lot
        that has since become `EXPIRED`, `RECALLED`, or `DEPLETED` blocks the
        shipment with `ERR_ORDER_CONTAINS_UNSHIPPABLE_LOT`."

        Design: Corner/validations/ship_blocked_when_allocated_lot_unshippable
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=473)
        order = place_order(ctx["customer"]["id"], ctx["formula"]["id"],
                            channel="DIRECT_RETAIL", requested_delivery_date="2026-08-20",
                            units_requested=400)
        allocate_order(order["id"])
        get_success_data(api.pick_order(order["id"], WH))
        get_success_data(api.recall_finished_lot(ctx["lot"]["id"], QA))
        resp = api.ship_order(order["id"], WH)
        validate_error(resp, ApiErrorId.ERR_ORDER_CONTAINS_UNSHIPPABLE_LOT)
        assert resp.status_code == 409
        order_after = get_success_data(api.get_shipment_order(order["id"], PM))
        assert order_after["status"] == "PICKED"
        assert order_after["allocated_units"] == 400


class TestAllocateEmptyPool:
    def test_recalled_only_lot_backorders_order(self, api):
        """PRD §3.9: "The outcome is binary: the order lands in `ALLOCATED` when
        `allocated_units` equals `units_requested`, and in `BACKORDERED` otherwise
        — an empty eligible pool is not an error, merely a fully backordered
        order."

        Design: Difficulty/cross_entity_state_dependency/allocate_backorders_when_only_lot_recalled
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=473)
        order = place_order(ctx["customer"]["id"], ctx["formula"]["id"],
                            channel="DIRECT_RETAIL", requested_delivery_date="2026-08-20",
                            units_requested=400)
        get_success_data(api.recall_finished_lot(ctx["lot"]["id"], QA))
        allocated = get_success_data(api.allocate_order(
            order["id"], {"expected_shipment_order_version": order["version"]}, WH))
        assert allocated["status"] == "BACKORDERED"
        assert allocated["allocated_units"] == 0
        lot = get_success_data(api.get_finished_lot(ctx["lot"]["id"], PM))
        assert lot["status"] == "RECALLED"

    def test_empty_pool_is_a_status_not_an_error(self, api):
        """PRD §3.9: "an empty eligible pool is not an error, merely a fully
        backordered order."

        Design: Difficulty/cross_entity_state_dependency/allocate_backorders_when_only_lot_recalled
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        order = place_order(customer["id"], formula["id"], channel="DIRECT_RETAIL",
                            requested_delivery_date="2026-08-20", units_requested=400)
        resp = api.allocate_order(
            order["id"], {"expected_shipment_order_version": order["version"]}, WH)
        data = validate_success(resp, 200)
        assert data["status"] == "BACKORDERED"
        assert data["allocated_units"] == 0


class TestOrderInvalidTransitions:
    def test_order_state_sweep(self, api):
        """PRD §3.9: "An `ALLOCATED` order is picked by a `WarehouseLead` (any
        other state draws `ERR_ORDER_STATE_INVALID`), moving it to `PICKED`.
        Shipping, again a `WarehouseLead` action, requires `PICKED`" and
        "Cancellation by a `WarehouseLead` or `CustomerServiceRep` is available
        from `PLACED`, `BACKORDERED`, `ALLOCATED`, or `PICKED` (else
        `ERR_ORDER_STATE_INVALID`), moving the order terminally to `CANCELLED`"

        Design: Corner/state_machines/shipment_order_invalid_transitions_and_idempotency
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=473)
        order = place_order(ctx["customer"]["id"], ctx["formula"]["id"],
                            channel="DIRECT_RETAIL", requested_delivery_date="2026-08-20",
                            units_requested=400)
        oid = order["id"]
        validate_error(api.pick_order(oid, WH), ApiErrorId.ERR_ORDER_STATE_INVALID)
        validate_error(api.ship_order(oid, WH), ApiErrorId.ERR_ORDER_STATE_INVALID)
        allocated = allocate_order(oid)
        assert allocated["status"] == "ALLOCATED"
        validate_error(api.ship_order(oid, WH), ApiErrorId.ERR_ORDER_STATE_INVALID)
        picked = get_success_data(api.pick_order(oid, WH))
        assert picked["status"] == "PICKED"
        validate_error(api.pick_order(oid, WH), ApiErrorId.ERR_ORDER_STATE_INVALID)
        shipped = get_success_data(api.ship_order(oid, WH))
        assert shipped["status"] == "SHIPPED"
        validate_error(api.ship_order(oid, WH), ApiErrorId.ERR_ORDER_STATE_INVALID)
        validate_error(api.cancel_order(oid, WH), ApiErrorId.ERR_ORDER_STATE_INVALID)


class TestOrderCreateGates:
    def test_delivery_date_and_customer_status_gates(self, api):
        """PRD §3.9: "The customer must be `ACTIVE`, else
        `ERR_CUSTOMER_NOT_ACTIVE`, and the requested delivery date must not
        precede the current logical date, else `ERR_DELIVERY_DATE_IN_PAST`."

        Design: Corner/validations/shipment_order_create_date_and_customer_gates
        """
        customer_a = create_customer(name="GateA")
        formula_a = create_formula(customer_a["id"], approve=False)
        customer_b = create_customer(name="GateB", approve=False)
        formula_b = create_formula(customer_b["id"], approve=False)
        # default logical date is 2026-08-01: yesterday is in the past
        resp = api.create_shipment_order(
            factories.create_shipment_order_payload(
                customer_a["id"], formula_a["id"], channel="DIRECT_RETAIL",
                requested_delivery_date="2026-07-31", units_requested=100), CSR)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_DATE_IN_PAST)
        assert resp.status_code == 422
        # the current logical date itself is allowed
        ok = get_success_data(api.create_shipment_order(
            factories.create_shipment_order_payload(
                customer_a["id"], formula_a["id"], channel="DIRECT_RETAIL",
                requested_delivery_date="2026-08-01", units_requested=100), CSR))
        assert ok["status"] == "PLACED"
        # a PENDING_CREDIT customer cannot place orders
        resp = api.create_shipment_order(
            factories.create_shipment_order_payload(
                customer_b["id"], formula_b["id"], channel="DIRECT_RETAIL",
                requested_delivery_date="2026-08-10", units_requested=100), CSR)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)
        assert resp.status_code == 409


class TestOrderAllocateOcc:
    def test_allocate_stale_version_rejected(self, api):
        """PRD §2.7: "Allocating or topping up a shipment order (`POST
        /v1/shipment-orders/{id}/allocate`) requires
        `expected_shipment_order_version` equal to the order's current `version`."
        and "the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no
        part of the write is applied."

        Design: Corner/cross_cutting_layers/occ_order_allocate_stale
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=473)
        order = place_order(ctx["customer"]["id"], ctx["formula"]["id"],
                            channel="DIRECT_RETAIL", requested_delivery_date="2026-08-20",
                            units_requested=400)
        allocated = allocate_order(order["id"])
        assert allocated["status"] == "ALLOCATED"
        assert allocated["version"] == order["version"] + 1
        resp = api.allocate_order(
            order["id"], {"expected_shipment_order_version": order["version"]}, WH)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

    def test_allocate_on_allocated_order_fails_state_gate(self, api):
        """PRD §3.9: "performed by a `WarehouseLead` on an order standing in
        `PLACED` or `BACKORDERED` (else `ERR_ORDER_STATE_INVALID`)" and "every
        allocation advances the order's `version` by one."

        Design: Corner/cross_cutting_layers/occ_order_allocate_stale
        """
        ctx = setup_completed_run(actual_units_filled=1000, avg_fill_ml=473)
        order = place_order(ctx["customer"]["id"], ctx["formula"]["id"],
                            channel="DIRECT_RETAIL", requested_delivery_date="2026-08-20",
                            units_requested=400)
        allocated = allocate_order(order["id"])
        # with the CURRENT version OCC passes; the state gate fires on ALLOCATED
        resp = api.allocate_order(
            order["id"], {"expected_shipment_order_version": allocated["version"]}, WH)
        validate_error(resp, ApiErrorId.ERR_ORDER_STATE_INVALID)
        assert resp.status_code == 409
