"""Load-out, the parallel temperature-compliance axis, FIFO lot selection,
dock decisions, and the shipment state gates."""
from test_helpers import (
    ApiErrorId,
    add_reading,
    add_sheet_line,
    api_client,
    assert_shipment,
    book_po,
    create_allocation_payload,
    create_customer,
    create_product,
    create_sheet,
    create_supplier,
    create_warehouse,
    deliver,
    depart,
    get_allocation,
    get_lot,
    get_shipment,
    get_po_lot,
    inspect_lot,
    load_out_shipment,
    make_customer_rep_headers,
    publish_sheet,
    receive_po,
    request_allocation,
    run_sheet,
    set_clock,
    setup_available_lot,
    setup_confirmed_allocation,
    setup_delivered_shipment,
    setup_staging_shipment,
    temperature_reading_payload,
    validate_error,
    validate_success,
)


class TestParallelTempAndDeliveryAxes:
    def test_delivery_axis_never_mutates_temperature_axis(self):
        """PRD §3.7: "Temperature surveillance runs on a second, parallel state
        axis that is independent of the shipment's `status`."
        PRD §3.7: "A reading strictly greater than the ceiling moves the axis
        to `BREACHED` — from `UNKNOWN` or from `COMPLIANT` alike — while a
        reading less than or equal to the ceiling moves an `UNKNOWN` axis to
        `COMPLIANT`."

        Design: Difficulty/non_linear_state_machine/shipment_parallel_temp_and_delivery_axes
        """
        ctx = setup_staging_shipment(shipped_lbs=500, lot_weight=1000)
        ship_id = ctx["shipment"]["id"]
        assert ctx["shipment"]["temp_compliance"] == "UNKNOWN"

        add_reading(ship_id, 38.0)  # <= required_temp_max_f 40
        mid = get_shipment(ship_id)
        assert mid["temp_compliance"] == "COMPLIANT"

        depart(ship_id)
        in_transit = get_shipment(ship_id)
        assert in_transit["status"] == "IN_TRANSIT"
        assert in_transit["temp_compliance"] == "COMPLIANT", \
            "departure must not mutate the temperature axis"

        add_reading(ship_id, 41.5, "2026-08-05T14:00:00Z")  # > 40 -> BREACHED
        breached = get_shipment(ship_id)
        assert breached["status"] == "IN_TRANSIT", \
            "a breaching reading must not mutate the delivery axis"
        assert breached["temp_compliance"] == "BREACHED"

        deliver(ship_id, ctx["customer"])
        final = get_shipment(ship_id)
        assert final["status"] == "DELIVERED"
        assert final["temp_compliance"] == "BREACHED", \
            "delivery does not clear the breach"
        assert final["max_temp_f_reading"] == 41.5

    def test_breached_axis_is_sticky(self):
        """PRD §3.7: "Once `BREACHED`, the axis is sticky: no later reading
        ever reverts it."
        PRD §3.7: "`min_temp_f_reading` and `max_temp_f_reading` fold the new
        reading into the running minimum and maximum"

        Design: Difficulty/non_linear_state_machine/shipment_parallel_temp_and_delivery_axes
        """
        ctx = setup_delivered_shipment(shipped_lbs=500, lot_weight=1000,
                                       breach=True)
        ship_id = ctx["shipment"]["id"]
        assert ctx["shipment"]["temp_compliance"] == "BREACHED"

        add_reading(ship_id, 35.0, "2026-08-06T08:00:00Z")  # compliant reading
        after = get_shipment(ship_id)
        assert after["temp_compliance"] == "BREACHED", \
            "a later compliant reading must not revert BREACHED"
        assert after["min_temp_f_reading"] == 35.0
        assert after["max_temp_f_reading"] == 41.5


class TestTemperatureBoundary:
    def test_reading_exactly_at_max_stays_compliant(self):
        """PRD §3.7: "A reading exactly equal to the ceiling therefore keeps or
        sets `COMPLIANT`; the breach comparison is strict."
        PRD §2.6: "temperature compliance comparisons are exact decimal
        comparisons at tenth-of-a-degree precision."

        Design: Difficulty/boundary_precision_check/temp_reading_exactly_at_max_stays_compliant
        """
        ctx = setup_staging_shipment(shipped_lbs=500, lot_weight=1000)
        ship_id = ctx["shipment"]["id"]

        add_reading(ship_id, 40.0)  # == required_temp_max_f
        at_max = get_shipment(ship_id)
        assert at_max["temp_compliance"] == "COMPLIANT", \
            "equality with the ceiling must not breach"
        assert at_max["max_temp_f_reading"] == 40.0

        add_reading(ship_id, 40.1, "2026-08-05T09:00:00Z")  # strictly greater
        over = get_shipment(ship_id)
        assert over["temp_compliance"] == "BREACHED"
        assert over["max_temp_f_reading"] == 40.1

    def test_repeated_compliant_readings_track_min_max(self):
        """PRD §3.7: "`min_temp_f_reading` and `max_temp_f_reading` fold the
        new reading into the running minimum and maximum, and
        `temp_compliance` re-evaluates against the product's
        `required_temp_max_f`."

        Design: Difficulty/boundary_precision_check/temp_reading_exactly_at_max_stays_compliant
        """
        ctx = setup_staging_shipment(shipped_lbs=500, lot_weight=1000)
        ship_id = ctx["shipment"]["id"]

        add_reading(ship_id, 38.0)
        add_reading(ship_id, 40.0, "2026-08-05T09:00:00Z")  # == max: compliant
        after = get_shipment(ship_id)
        assert after["temp_compliance"] == "COMPLIANT"
        assert after["min_temp_f_reading"] == 38.0
        assert after["max_temp_f_reading"] == 40.0


class TestShipmentSafetyOrdering:
    def test_quarantined_lot_plus_overshipment_reports_lot_not_available(
            self, quality_grader_headers, warehouse_operator_headers):
        """PRD §2.8: "Earlier stages mask later ones: a request that fails an
        earlier check reports that check's error and is never evaluated against
        later checks, so the reported error is always the highest-priority
        failure."
        PRD §3.7: "When `lot_ids` is supplied, each named lot must be
        `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE`), must not be `EXPIRED`
        (`ERR_LOT_EXPIRED`), and must be of the allocation line's product
        (`ERR_LOT_PRODUCT_MISMATCH`, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/shipment_safety_vs_referential_mismatch
        """
        ctx = setup_confirmed_allocation(requested_lbs=100, lot_weight=1000)
        lot_id = ctx["lot"]["id"]
        api_client.quarantine_lot(lot_id, quality_grader_headers)

        resp = api_client.create_shipment(
            {"allocation_id": ctx["allocation"]["id"], "carrier_name": "CAR-1",
             "trailer_temp_setpoint_f": 36.0, "shipped_lbs": 150,
             "lot_ids": [lot_id]},
            warehouse_operator_headers,
        )
        # Stage 9 (lot shippable) masks stage 10 (150 > 100 remaining).
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_AVAILABLE)
        assert get_allocation(ctx["allocation"]["id"])["status"] == "CONFIRMED"
        shipments = validate_success(api_client.list_shipments(
            warehouse_operator_headers,
            params={"allocation_id": ctx["allocation"]["id"]}))
        assert shipments == [], "no shipment may be persisted by the rejection"

    def test_quarantined_lot_at_exact_remaining_still_reports_lot_error(
            self, quality_grader_headers, warehouse_operator_headers):
        """PRD §3.7: "When `lot_ids` is supplied, each named lot must be
        `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE`), must not be `EXPIRED`
        (`ERR_LOT_EXPIRED`), and must be of the allocation line's product
        (`ERR_LOT_PRODUCT_MISMATCH`, HTTP 422)."
        PRD §3.4: "Beyond a failed inspection, a `QualityGrader` may manually
        quarantine an `AVAILABLE` lot — a USDA hold — recording
        `quarantine_reason` `USDA_HOLD`"

        Design: Difficulty/priority_pair_validation_conflict/shipment_safety_vs_referential_mismatch
        """
        ctx = setup_confirmed_allocation(requested_lbs=100, lot_weight=1000)
        lot_id = ctx["lot"]["id"]
        api_client.quarantine_lot(lot_id, quality_grader_headers)
        assert get_lot(lot_id)["quarantine_reason"] == "USDA_HOLD"

        resp = api_client.create_shipment(
            {"allocation_id": ctx["allocation"]["id"], "carrier_name": "CAR-1",
             "trailer_temp_setpoint_f": 36.0, "shipped_lbs": 100,
             "lot_ids": [lot_id]},
            warehouse_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_AVAILABLE)


class TestTerminalLockdown:
    def test_delivered_shipment_rejects_all_actions(self,
                                                    warehouse_operator_headers):
        """PRD §3.7: "Departure, delivery, and rejection move the shipment's
        `status` axis through `STAGING`, `IN_TRANSIT`, `DELIVERED`, and
        `REJECTED_AT_RECEIVING`, with the latter two terminal."
        PRD §3.7: "A `WarehouseOperator` departs a `STAGING` shipment — else
        `ERR_SHIPMENT_NOT_STAGING` — only after at least one temperature
        reading exists, else `ERR_NO_TEMPERATURE_READING`"
        PRD §3.7: "Acceptance requires `IN_TRANSIT`, else
        `ERR_SHIPMENT_NOT_IN_TRANSIT`"
        PRD §3.7: "Refusal likewise requires `IN_TRANSIT`, else
        `ERR_SHIPMENT_NOT_IN_TRANSIT`"

        Design: Corner/state_machines/terminal_lockdown_delivered_shipment
        """
        ctx = setup_delivered_shipment(shipped_lbs=100, lot_weight=1000)
        ship_id = ctx["shipment"]["id"]
        rep = make_customer_rep_headers(ctx["customer"]["id"])

        depart_again = api_client.depart_shipment(ship_id,
                                                  warehouse_operator_headers)
        validate_error(depart_again, ApiErrorId.ERR_SHIPMENT_NOT_STAGING)
        deliver_again = api_client.deliver_shipment(ship_id, rep)
        validate_error(deliver_again, ApiErrorId.ERR_SHIPMENT_NOT_IN_TRANSIT)
        reject = api_client.reject_shipment(ship_id,
                                            {"rejection_reason": "late"}, rep)
        validate_error(reject, ApiErrorId.ERR_SHIPMENT_NOT_IN_TRANSIT)
        assert get_shipment(ship_id)["status"] == "DELIVERED"


class TestDepartureGate:
    def test_depart_without_reading_returns_409(self, warehouse_operator_headers):
        """PRD §3.7: "A `WarehouseOperator` departs a `STAGING` shipment —
        else `ERR_SHIPMENT_NOT_STAGING` — only after at least one temperature
        reading exists, else `ERR_NO_TEMPERATURE_READING`; departure moves the
        shipment to `IN_TRANSIT`"

        Design: Corner/validations/depart_without_reading_returns_409
        """
        ctx = setup_staging_shipment(shipped_lbs=100, lot_weight=500)
        ship_id = ctx["shipment"]["id"]

        resp = api_client.depart_shipment(ship_id, warehouse_operator_headers)
        validate_error(resp, ApiErrorId.ERR_NO_TEMPERATURE_READING)

        add_reading(ship_id, 37.0)
        ok = api_client.depart_shipment(ship_id, warehouse_operator_headers)
        assert validate_success(ok)["status"] == "IN_TRANSIT"


class TestLoadOutSupplyRules:
    def test_over_shipment_returns_422(self, warehouse_operator_headers):
        """PRD §3.7: "The loaded weight may not exceed the allocation's
        remaining unshipped balance — its `allocated_lbs` minus the weight
        already shipped on earlier shipments — else
        `ERR_SHIPMENT_EXCEEDS_ALLOCATION` (HTTP 422)."

        Design: Corner/validations/over_shipment_returns_422
        """
        ctx = setup_confirmed_allocation(requested_lbs=500, lot_weight=1000)
        resp = api_client.create_shipment(
            {"allocation_id": ctx["allocation"]["id"], "carrier_name": "CAR-1",
             "trailer_temp_setpoint_f": 36.0, "shipped_lbs": 600},
            warehouse_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_EXCEEDS_ALLOCATION)
        assert get_lot(ctx["lot"]["id"])["current_weight_lbs"] == 1000, \
            "a rejected load-out must not draw any lot down"

    def test_insufficient_supply_returns_409(self, warehouse_operator_headers):
        """PRD §3.7: "If the total `AVAILABLE` weight of the product cannot
        cover `shipped_lbs`, the whole request is rejected with
        `ERR_INSUFFICIENT_SUPPLY` and nothing is decremented."

        Design: Corner/validations/insufficient_supply_returns_409
        """
        ctx = setup_confirmed_allocation(requested_lbs=500, lot_weight=100)
        resp = api_client.create_shipment(
            {"allocation_id": ctx["allocation"]["id"], "carrier_name": "CAR-1",
             "trailer_temp_setpoint_f": 36.0, "shipped_lbs": 500},
            warehouse_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SUPPLY)
        assert get_lot(ctx["lot"]["id"])["current_weight_lbs"] == 100

    def test_explicit_lot_product_mismatch_returns_422(
            self, warehouse_operator_headers):
        """PRD §3.7: "When `lot_ids` is supplied, each named lot must be
        `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE`), must not be `EXPIRED`
        (`ERR_LOT_EXPIRED`), and must be of the allocation line's product
        (`ERR_LOT_PRODUCT_MISMATCH`, HTTP 422)."

        Design: Corner/validations/explicit_lot_product_mismatch_returns_422
        """
        # AVAILABLE lot of a DIFFERENT product than the allocation's line.
        chuck_ctx = setup_available_lot(product_code="CHUCK-MX",
                                        max_fat_pct=18.0, weight=500,
                                        measured_fat_pct=15.0)
        rib_ctx = setup_confirmed_allocation(requested_lbs=100, lot_weight=100)

        resp = api_client.create_shipment(
            {"allocation_id": rib_ctx["allocation"]["id"],
             "carrier_name": "CAR-1", "trailer_temp_setpoint_f": 36.0,
             "shipped_lbs": 100, "lot_ids": [chuck_ctx["lot"]["id"]]},
            warehouse_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LOT_PRODUCT_MISMATCH)
        shipments = validate_success(api_client.list_shipments(
            warehouse_operator_headers,
            params={"allocation_id": rib_ctx["allocation"]["id"]}))
        assert shipments == []


class TestFifoLotSelection:
    def test_fifo_lot_selection_oldest_first(self):
        """PRD §3.7: "eligible lots are the `AVAILABLE` lots of the
        allocation's product across all warehouses, ranked by `production_date`
        ascending with earlier `created_at` breaking ties; the selector walks
        that ranked list drawing from each lot the lesser of the remaining need
        and the lot's `current_weight_lbs` until the shipped weight is covered,
        and any lot drawn to zero moves to `DEPLETED`."

        Design: Corner/calculations/fifo_lot_selection_oldest_first
        """
        product = create_product(product_code="RIBEYE-FI", max_fat_pct=12.0,
                                 shelf_life_days=30)
        supplier = create_supplier(establishment_number="EST-FI")
        warehouse = create_warehouse()
        customer = create_customer(customer_code="CUST-FI")
        sheet = create_sheet()
        line = add_sheet_line(sheet["id"], product["id"], 700, 100_000)
        publish_sheet(sheet["id"])
        set_clock("2026-08-06T00:00:00Z")

        po_old = book_po(supplier["id"], product["id"], ordered_weight_lbs=300,
                         required_delivery_date="2026-08-03")
        _, lot_old = receive_po(po_old["id"], warehouse["id"], 300,
                                lot_code="LOT-OLD",
                                production_date="2026-08-01")
        po_new = book_po(supplier["id"], product["id"], ordered_weight_lbs=300,
                         required_delivery_date="2026-08-06")
        _, lot_new = receive_po(po_new["id"], warehouse["id"], 300,
                                lot_code="LOT-NEW",
                                production_date="2026-08-05")
        inspect_lot(lot_old["id"], 10.0)
        inspect_lot(lot_new["id"], 10.0)

        alloc = request_allocation(customer, line["id"], 400)
        run_sheet(sheet["id"])
        shipment = load_out_shipment(alloc["id"], 400)
        assert_shipment(shipment)

        old_after = get_lot(lot_old["id"])
        assert old_after["status"] == "DEPLETED"
        assert old_after["current_weight_lbs"] == 0, \
            "the oldest lot is drained first"
        new_after = get_lot(lot_new["id"])
        assert new_after["status"] == "AVAILABLE"
        assert new_after["current_weight_lbs"] == 200, \
            "400 shipped: 300 drained from the older lot, 100 from this one"
