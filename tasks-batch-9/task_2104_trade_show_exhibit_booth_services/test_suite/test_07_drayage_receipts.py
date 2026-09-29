"""Drayage receipts: the three receipt guards, the material-handling price and the
shipment lifecycle that is derived from the crates it covers."""
from test_helpers import (
    DRAYAGE,
    TEST_USERS,
    ApiErrorId,
    advance_show,
    assert_crate,
    assert_drayage_shipment,
    create_drayage_shipment_payload,
    create_exhibitor,
    get_crate,
    get_shipment,
    make_warehouse_agent_headers,
    move_crate,
    receive_shipment,
    register_crate,
    setup_show_ground,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["show_operations_headers"]

# Every scenario below stands a venue whose forklift lifts 6000 lb and an advance
# warehouse, and leaves the show on the calendar declared in the show factory,
# whose advance_warehouse_deadline is 2026-09-10T00:00:00Z.
VENUE_FORKLIFT_6000 = {"max_forklift_capacity_lbs": 6000}


def _freight_ground(dock_capacity_cwt=300):
    return setup_show_ground(
        show_status="DRAFT",
        with_warehouse=True,
        warehouse_overrides={"dock_capacity_cwt": dock_capacity_cwt},
        venue_overrides=VENUE_FORKLIFT_6000,
    )


class TestDrayageAdditiveSurchargeStack:
    """A 2080 lb advance receipt tendered at 18:30 on 2026-09-12, two days past the
    advance warehouse deadline."""

    LATE_AFTER_HOURS = {
        "received_at": "2026-09-12T18:30:00Z",
        "dock_window_start": "2026-09-12T18:00:00Z",
        "dock_window_end": "2026-09-12T20:00:00Z",
        "declared_value_coverage": False,
    }

    def _receipt(self):
        ground = _freight_ground()
        exhibitor_id = ground["exhibitor"]["id"]
        ground["crate_a"] = register_crate(exhibitor_id, crate_label="ACME-C1",
                                           crate_type="WOOD_CRATE", weight_lbs=1250)
        ground["crate_b"] = register_crate(exhibitor_id, crate_label="ACME-C2",
                                           crate_type="WOOD_CRATE", weight_lbs=830)
        ground["shipment"] = receive_shipment(
            ground["show"]["id"], exhibitor_id,
            [ground["crate_a"]["id"], ground["crate_b"]["id"]],
            warehouse_id=ground["warehouse"]["id"], **self.LATE_AFTER_HOURS)
        return ground

    def test_two_crate_receipt_sums_gross_pounds_and_ceils_to_twenty_one_cwt(self, api):
        """PRD §3.6: "`gross_weight_lbs` is the exact sum of `weight_lbs` over every crate whose id appears in `crate_ids`, taken regardless of each crate's current `status`; crates sitting at the same warehouse but absent from the list never contribute a pound."
        PRD §3.6: "`billable_cwt` is the greater of two and the gross weight in pounds divided by one hundred rounded up to a whole number — a two-hundredweight minimum applies to even the lightest shipment."

        Design: Difficulty/combinatorial_formula/drayage_additive_surcharge_stack_with_cwt_ceiling
        """
        ground = self._receipt()
        shipment = get_shipment(ground["shipment"]["id"])

        assert_drayage_shipment(shipment)
        assert shipment["gross_weight_lbs"] == 2080, (
            "gross_weight_lbs is the exact sum of the 1250 lb and 830 lb crates, "
            f"got {shipment['gross_weight_lbs']}"
        )
        assert shipment["billable_cwt"] == 21, (
            "2080 pounds divided by one hundred rounds up to 21 hundredweight, "
            f"got {shipment['billable_cwt']}"
        )

    def test_late_after_hours_advance_receipt_adds_surcharges_without_compounding(self, api):
        """PRD §3.6: "The base rate is 9800 cents per hundredweight when `channel` is `ADVANCE_WAREHOUSE` and 11500 cents per hundredweight when it is `DIRECT_TO_SHOW`."
        PRD §3.6: "Three independent surcharge fractions are then accumulated onto a running total that starts at zero: thirty percent is added when any crate in `crate_ids` has `crate_type` `LOOSE_UNCRATED`; twenty-five percent is added when the UTC hour of `received_at` is below 8 or is 16 or greater; and thirty-five percent is added when `channel` is `ADVANCE_WAREHOUSE` and `received_at` falls strictly after the show's `advance_warehouse_deadline`."
        PRD §3.6: "`drayage_charge_cents` is then `billable_cwt` multiplied by the base rate, multiplied by one plus the accumulated surcharge fraction, rounded half up to a whole cent."
        PRD §3.6: "The surcharges are additive on the base and are never compounded: a loose, after-hours receipt carries a combined fraction of 0.55 and therefore a multiplier of 1.55, not the 1.625 that multiplying 1.30 by 1.25 would give."

        Design: Difficulty/combinatorial_formula/drayage_additive_surcharge_stack_with_cwt_ceiling
        """
        ground = self._receipt()
        shipment = get_shipment(ground["shipment"]["id"])

        assert shipment["drayage_charge_cents"] == 329280, (
            "an 18:30 receipt tendered after the advance warehouse deadline carries the "
            "after-hours and late fractions added onto the 9800 cent advance rate, "
            f"got {shipment['drayage_charge_cents']}"
        )
        assert shipment["drayage_charge_cents"] != 401800, (
            "the two surcharges are additive on the base and are never compounded"
        )

    def test_priced_receipt_is_born_received_and_stamps_each_listed_crate(self, api):
        """PRD §3.6: "Shipments are born `RECEIVED` with `hold_flag` false and `hold_reason` null, and every listed crate has its `shipment_id` set to the new shipment."
        PRD §3.6: "`RECEIVED → IN_TRANSIT` fires when the first crate of an `ADVANCE_WAREHOUSE` shipment leaves the warehouse for the floor, and bumps the shipment's `version`."

        Design: Difficulty/combinatorial_formula/drayage_additive_surcharge_stack_with_cwt_ceiling
        """
        ground = self._receipt()
        shipment = get_shipment(ground["shipment"]["id"])

        assert shipment["status"] == "RECEIVED", (
            "no crate has left the warehouse, so the receipt stays in its birth status, "
            f"got {shipment['status']}"
        )
        assert shipment["hold_flag"] is False, "a new receipt carries no operational hold"
        assert shipment["hold_reason"] is None, "hold_reason is null on a new receipt"

        for crate in (ground["crate_a"], ground["crate_b"]):
            stamped = get_crate(crate["id"])
            assert_crate(stamped)
            assert stamped["shipment_id"] == shipment["id"], (
                f"crate {stamped['crate_label']} must carry the new shipment's id, "
                f"got {stamped['shipment_id']}"
            )


class TestEmptyCrateIdsOnReceipt:
    """A receipt carrying zero crate ids is a collection-boundary failure, not the
    cheapest possible shipment."""

    def test_receipt_with_empty_crate_ids_is_refused_with_empty_collection(self, api):
        """PRD §2.9: "Collection inputs are non-empty — otherwise `ERR_EMPTY_COLLECTION` (422). Applies to `POST /service-orders`, `POST /drayage-shipments`, `POST /invoices` and `POST /lead-capture-licenses/{id}/lead-batches`."
        PRD §5: "Every error response carries one of the identifiers below in `data.error_id`, with the HTTP status shown."

        Design: Difficulty/boundary_precision_check/empty_crate_ids_collection_rejected_on_shipment
        """
        ground = _freight_ground()
        warehouse_id = ground["warehouse"]["id"]
        payload = create_drayage_shipment_payload(
            ground["show"]["id"], ground["exhibitor"]["id"], [],
            warehouse_id=warehouse_id, declared_value_coverage=False)

        resp = api.create_drayage_shipment(payload,
                                           make_warehouse_agent_headers(warehouse_id))
        validate_error(resp, ApiErrorId.ERR_EMPTY_COLLECTION, expected_status=422)

    def test_refused_empty_crate_ids_receipt_prices_nothing_and_persists_nothing(self, api):
        """PRD §2.9: "Collection inputs are non-empty — otherwise `ERR_EMPTY_COLLECTION` (422). Applies to `POST /service-orders`, `POST /drayage-shipments`, `POST /invoices` and `POST /lead-capture-licenses/{id}/lead-batches`."
        PRD §2.3: "`total_count` is the number of rows matching the filters before the page window is applied, and `has_more` is true when rows remain beyond the current window."

        Design: Difficulty/boundary_precision_check/empty_crate_ids_collection_rejected_on_shipment
        """
        ground = _freight_ground()
        show_id = ground["show"]["id"]
        warehouse_id = ground["warehouse"]["id"]
        payload = create_drayage_shipment_payload(
            show_id, ground["exhibitor"]["id"], [],
            warehouse_id=warehouse_id, declared_value_coverage=False)

        resp = api.create_drayage_shipment(payload,
                                           make_warehouse_agent_headers(warehouse_id))
        validate_error(resp, ApiErrorId.ERR_EMPTY_COLLECTION)

        rows, meta = validate_paginated(
            api.list_drayage_shipments(OPS, params={"show_id": show_id}))
        assert rows == [], (
            "the refused receipt must not be priced at the two-hundredweight minimum "
            f"and stored, got {rows}"
        )
        assert meta["total_count"] == 0, (
            f"no shipment exists on this show, got total_count {meta['total_count']}"
        )


class TestWarehouseDockAggregateCapacity:
    """A 30 cwt dock already holding a 13 cwt appointment from 08:00 to 12:00."""

    FIRST_APPOINTMENT = {
        "received_at": "2026-09-08T09:00:00Z",
        "dock_window_start": "2026-09-08T08:00:00Z",
        "dock_window_end": "2026-09-08T12:00:00Z",
        "declared_value_coverage": False,
    }
    OVERLAPPING_APPOINTMENT = {
        "received_at": "2026-09-08T10:00:00Z",
        "dock_window_start": "2026-09-08T10:00:00Z",
        "dock_window_end": "2026-09-08T14:00:00Z",
        "declared_value_coverage": False,
    }
    ABUTTING_APPOINTMENT = {
        "received_at": "2026-09-08T12:00:00Z",
        "dock_window_start": "2026-09-08T12:00:00Z",
        "dock_window_end": "2026-09-08T16:00:00Z",
        "declared_value_coverage": False,
    }

    def _dock_ground(self):
        ground = _freight_ground(dock_capacity_cwt=30)
        exhibitor_id = ground["exhibitor"]["id"]
        ground["crate_a"] = register_crate(exhibitor_id, crate_label="ACME-C1",
                                           crate_type="WOOD_CRATE", weight_lbs=1250)
        ground["crate_b"] = register_crate(exhibitor_id, crate_label="ACME-C2",
                                           crate_type="WOOD_CRATE", weight_lbs=2000)
        ground["crate_c"] = register_crate(exhibitor_id, crate_label="ACME-C3",
                                           crate_type="WOOD_CRATE", weight_lbs=2000)
        ground["shipment_a"] = receive_shipment(
            ground["show"]["id"], exhibitor_id, [ground["crate_a"]["id"]],
            warehouse_id=ground["warehouse"]["id"], **self.FIRST_APPOINTMENT)
        return ground

    def _attempt(self, api, ground, crate, appointment):
        payload = create_drayage_shipment_payload(
            ground["show"]["id"], ground["exhibitor"]["id"], [crate["id"]],
            warehouse_id=ground["warehouse"]["id"], **appointment)
        return api.create_drayage_shipment(
            payload, make_warehouse_agent_headers(ground["warehouse"]["id"]))

    def test_overlapping_appointment_beyond_aggregate_dock_capacity_is_refused(self, api):
        """PRD §3.1: "`dock_capacity_cwt` caps the aggregate hundredweight of receiving appointments that may overlap any single instant and defaults to 300."
        PRD §3.6: "And the receiving appointment must fit the dock: over the half-open interval from `dock_window_start` up to but not including `dock_window_end`, the sum of `billable_cwt` across this shipment and every existing shipment at the same warehouse whose `status` is `RECEIVED` or `IN_TRANSIT` and whose own half-open window intersects this one must not exceed the warehouse's `dock_capacity_cwt`; an overflow is refused with `ERR_DOCK_CAPACITY_EXCEEDED`."
        PRD §2.9: "Aggregate dock capacity at the warehouse — otherwise `ERR_DOCK_CAPACITY_EXCEEDED` (409). Applies to `POST /drayage-shipments`."

        Design: Difficulty/resource_temporal_overlap/warehouse_dock_aggregate_capacity_rejects_overlap_but_admits_abutment
        """
        ground = self._dock_ground()
        assert ground["shipment_a"]["billable_cwt"] == 13, (
            "the 1250 lb crate already occupies 13 hundredweight of the 30 cwt dock, "
            f"got {ground['shipment_a']['billable_cwt']}"
        )

        resp = self._attempt(api, ground, ground["crate_b"], self.OVERLAPPING_APPOINTMENT)
        validate_error(resp, ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED, expected_status=409)

    def test_appointment_abutting_the_end_instant_is_admitted_and_priced(self, api):
        """PRD §3.6: "Because both windows are half-open, an existing appointment ending at exactly the instant the new one starts does not intersect it."
        PRD §3.6: "The base rate is 9800 cents per hundredweight when `channel` is `ADVANCE_WAREHOUSE` and 11500 cents per hundredweight when it is `DIRECT_TO_SHOW`."
        PRD §3.6: "`drayage_charge_cents` is then `billable_cwt` multiplied by the base rate, multiplied by one plus the accumulated surcharge fraction, rounded half up to a whole cent."

        Design: Difficulty/resource_temporal_overlap/warehouse_dock_aggregate_capacity_rejects_overlap_but_admits_abutment
        """
        ground = self._dock_ground()

        resp = self._attempt(api, ground, ground["crate_c"], self.ABUTTING_APPOINTMENT)
        abutting = validate_success(resp, expected_status=201)

        assert_drayage_shipment(abutting)
        assert abutting["billable_cwt"] == 20, (
            "a 2000 lb crate is exactly 20 hundredweight, "
            f"got {abutting['billable_cwt']}"
        )
        assert abutting["drayage_charge_cents"] == 196000, (
            "a midday receipt inside the advance deadline carries no surcharge at all, "
            f"got {abutting['drayage_charge_cents']}"
        )

    def test_refused_overlap_reserves_no_dock_and_leaves_two_appointments(self, api):
        """PRD §3.6: "And the receiving appointment must fit the dock: over the half-open interval from `dock_window_start` up to but not including `dock_window_end`, the sum of `billable_cwt` across this shipment and every existing shipment at the same warehouse whose `status` is `RECEIVED` or `IN_TRANSIT` and whose own half-open window intersects this one must not exceed the warehouse's `dock_capacity_cwt`; an overflow is refused with `ERR_DOCK_CAPACITY_EXCEEDED`."
        PRD §3.6: "Because both windows are half-open, an existing appointment ending at exactly the instant the new one starts does not intersect it."

        Design: Difficulty/resource_temporal_overlap/warehouse_dock_aggregate_capacity_rejects_overlap_but_admits_abutment
        """
        ground = self._dock_ground()
        warehouse_id = ground["warehouse"]["id"]

        refused = self._attempt(api, ground, ground["crate_b"],
                                self.OVERLAPPING_APPOINTMENT)
        validate_error(refused, ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED)

        admitted = validate_success(
            self._attempt(api, ground, ground["crate_c"], self.ABUTTING_APPOINTMENT),
            expected_status=201)

        rows, meta = validate_paginated(
            api.list_drayage_shipments(OPS, params={"warehouse_id": warehouse_id}))
        assert meta["total_count"] == 2, (
            "only the first appointment and the abutting one survive at this dock, "
            f"got total_count {meta['total_count']}"
        )
        stored_ids = {row["id"] for row in rows}
        assert stored_ids == {ground["shipment_a"]["id"], admitted["id"]}, (
            f"unexpected shipments at the warehouse: {stored_ids}"
        )


class TestDrayagePricingFieldsAreServerComputed:
    def test_client_supplied_pricing_fields_never_reach_the_stored_receipt(self, api):
        """PRD §3.6: "`gross_weight_lbs` is the exact sum of `weight_lbs` over every crate whose id appears in `crate_ids`, taken regardless of each crate's current `status`; crates sitting at the same warehouse but absent from the list never contribute a pound."
        PRD §3.6: "`billable_cwt` is the greater of two and the gross weight in pounds divided by one hundred rounded up to a whole number — a two-hundredweight minimum applies to even the lightest shipment."
        PRD §3.6: "`drayage_charge_cents` is then `billable_cwt` multiplied by the base rate, multiplied by one plus the accumulated surcharge fraction, rounded half up to a whole cent."

        Design: Corner/entities/drayage_computed_pricing_fields_input_ignored
        """
        ground = _freight_ground()
        warehouse_id = ground["warehouse"]["id"]
        crate = register_crate(ground["exhibitor"]["id"], crate_label="ACME-C1",
                               crate_type="WOOD_CRATE", weight_lbs=1250)
        payload = create_drayage_shipment_payload(
            ground["show"]["id"], ground["exhibitor"]["id"], [crate["id"]],
            warehouse_id=warehouse_id, declared_value_coverage=False,
            drayage_charge_cents=1, billable_cwt=1, gross_weight_lbs=1)

        shipment = validate_success(
            api.create_drayage_shipment(payload,
                                        make_warehouse_agent_headers(warehouse_id)),
            expected_status=201)

        assert_drayage_shipment(shipment)
        assert shipment["gross_weight_lbs"] == 1250, (
            "gross_weight_lbs is summed from the crate list, not taken from the body, "
            f"got {shipment['gross_weight_lbs']}"
        )
        assert shipment["billable_cwt"] == 13, (
            "1250 pounds rounds up to 13 hundredweight regardless of what was sent, "
            f"got {shipment['billable_cwt']}"
        )
        assert shipment["drayage_charge_cents"] == 127400, (
            "the charge is recomputed from the billable weight and the advance rate, "
            f"got {shipment['drayage_charge_cents']}"
        )


class TestDrayageTwoHundredweightFloor:
    def test_ninety_pound_fiber_case_is_billed_at_the_two_hundredweight_floor(self, api):
        """PRD §3.6: "`billable_cwt` is the greater of two and the gross weight in pounds divided by one hundred rounded up to a whole number — a two-hundredweight minimum applies to even the lightest shipment."
        PRD §3.6: "The base rate is 9800 cents per hundredweight when `channel` is `ADVANCE_WAREHOUSE` and 11500 cents per hundredweight when it is `DIRECT_TO_SHOW`."

        Design: Corner/calculations/drayage_two_hundredweight_floor_applies_to_light_freight
        """
        ground = _freight_ground()
        crate = register_crate(ground["exhibitor"]["id"], crate_label="ACME-LIGHT",
                               crate_type="FIBER_CASE", weight_lbs=90)
        shipment = receive_shipment(ground["show"]["id"], ground["exhibitor"]["id"],
                                    [crate["id"]],
                                    warehouse_id=ground["warehouse"]["id"],
                                    declared_value_coverage=False)

        assert shipment["gross_weight_lbs"] == 90, (
            f"gross_weight_lbs is the single crate's 90 pounds, got {shipment['gross_weight_lbs']}"
        )
        assert shipment["billable_cwt"] == DRAYAGE["MIN_BILLABLE_CWT"], (
            "90 pounds ceils to 1 hundredweight but the two-hundredweight floor wins, "
            f"got {shipment['billable_cwt']}"
        )
        assert shipment["drayage_charge_cents"] == 19600, (
            "the floor is priced at the advance rate, not the single hundredweight the "
            f"weight alone would buy, got {shipment['drayage_charge_cents']}"
        )


class TestLooseUncratedSurcharge:
    def test_one_loose_piece_surcharges_the_whole_three_crate_shipment(self, api):
        """PRD §3.6: "Three independent surcharge fractions are then accumulated onto a running total that starts at zero: thirty percent is added when any crate in `crate_ids` has `crate_type` `LOOSE_UNCRATED`; twenty-five percent is added when the UTC hour of `received_at` is below 8 or is 16 or greater; and thirty-five percent is added when `channel` is `ADVANCE_WAREHOUSE` and `received_at` falls strictly after the show's `advance_warehouse_deadline`."
        PRD §3.6: "`billable_cwt` is the greater of two and the gross weight in pounds divided by one hundred rounded up to a whole number — a two-hundredweight minimum applies to even the lightest shipment."
        PRD §3.6: "`drayage_charge_cents` is then `billable_cwt` multiplied by the base rate, multiplied by one plus the accumulated surcharge fraction, rounded half up to a whole cent."

        Design: Corner/calculations/drayage_loose_uncrated_surcharge_applies_to_whole_shipment
        """
        ground = _freight_ground()
        exhibitor_id = ground["exhibitor"]["id"]
        crate_a = register_crate(exhibitor_id, crate_label="ACME-C1",
                                 crate_type="WOOD_CRATE", weight_lbs=1250)
        crate_b = register_crate(exhibitor_id, crate_label="ACME-C2",
                                 crate_type="WOOD_CRATE", weight_lbs=830)
        crate_c = register_crate(exhibitor_id, crate_label="ACME-C3",
                                 crate_type="LOOSE_UNCRATED", weight_lbs=300)

        shipment = receive_shipment(ground["show"]["id"], exhibitor_id,
                                    [crate_a["id"], crate_b["id"], crate_c["id"]],
                                    warehouse_id=ground["warehouse"]["id"],
                                    declared_value_coverage=False)

        assert shipment["gross_weight_lbs"] == 2380, (
            f"gross_weight_lbs sums all three crates, got {shipment['gross_weight_lbs']}"
        )
        assert shipment["billable_cwt"] == 24, (
            f"2380 pounds rounds up to 24 hundredweight, got {shipment['billable_cwt']}"
        )
        assert shipment["drayage_charge_cents"] == 305760, (
            "one LOOSE_UNCRATED piece raises the surcharge for the entire shipment, "
            f"got {shipment['drayage_charge_cents']}"
        )
        assert shipment["drayage_charge_cents"] != 235200, (
            "an unsurcharged shipment would be the wrong price when a loose piece rides along"
        )


class TestCrateWeightLimitGuard:
    def test_crate_heavier_than_the_venue_forklift_limit_is_refused(self, api):
        """PRD §3.6: "No listed crate may have a `weight_lbs` greater than the `max_forklift_capacity_lbs` of the venue hosting the destination show, or the receipt is refused with `ERR_CRATE_WEIGHT_LIMIT_EXCEEDED`."
        PRD §2.9: "No crate on the shipment exceeds the venue's forklift limit — otherwise `ERR_CRATE_WEIGHT_LIMIT_EXCEEDED` (422). Applies to `POST /drayage-shipments`."

        Design: Corner/validations/crate_over_forklift_limit_rejected_on_shipment
        """
        ground = _freight_ground()
        show_id = ground["show"]["id"]
        warehouse_id = ground["warehouse"]["id"]
        crate = register_crate(ground["exhibitor"]["id"], crate_label="ACME-HEAVY",
                               crate_type="WOOD_CRATE", weight_lbs=7000)
        payload = create_drayage_shipment_payload(
            show_id, ground["exhibitor"]["id"], [crate["id"]],
            warehouse_id=warehouse_id, declared_value_coverage=False)

        resp = api.create_drayage_shipment(payload,
                                           make_warehouse_agent_headers(warehouse_id))
        validate_error(resp, ApiErrorId.ERR_CRATE_WEIGHT_LIMIT_EXCEEDED,
                       expected_status=422)

        rows, meta = validate_paginated(
            api.list_drayage_shipments(OPS, params={"show_id": show_id}))
        assert meta["total_count"] == 0, (
            f"the refused receipt must create no shipment, got {meta['total_count']}"
        )
        assert rows == [], f"no shipment may exist on this show, got {rows}"
        assert get_crate(crate["id"])["shipment_id"] is None, (
            "a crate on a refused receipt keeps a null shipment_id"
        )


class TestCrateExhibitorGuard:
    def test_crate_owned_by_another_exhibitor_cannot_ride_on_the_receipt(self, api):
        """PRD §3.6: "Every listed crate's `exhibitor_id` must equal the shipment's own `exhibitor_id`, or it is refused with `ERR_CRATE_EXHIBITOR_MISMATCH`."
        PRD §2.9: "Every listed crate belongs to the shipment's exhibitor — otherwise `ERR_CRATE_EXHIBITOR_MISMATCH` (422). Applies to `POST /drayage-shipments`."

        Design: Corner/validations/crate_belonging_to_another_exhibitor_rejected_on_shipment
        """
        ground = _freight_ground()
        warehouse_id = ground["warehouse"]["id"]
        acme_id = ground["exhibitor"]["id"]
        acme_crate = register_crate(acme_id, crate_label="ACME-C1",
                                    crate_type="WOOD_CRATE", weight_lbs=1250)

        borealis = create_exhibitor(company_name="Borealis Robotics",
                                    contact_email="ap@borealis.test",
                                    credit_limit_cents=5000000)
        borealis_crate = register_crate(borealis["id"], crate_label="BOR-C1",
                                        crate_type="WOOD_CRATE", weight_lbs=1250)

        payload = create_drayage_shipment_payload(
            ground["show"]["id"], acme_id, [acme_crate["id"], borealis_crate["id"]],
            warehouse_id=warehouse_id, declared_value_coverage=False)

        resp = api.create_drayage_shipment(payload,
                                           make_warehouse_agent_headers(warehouse_id))
        validate_error(resp, ApiErrorId.ERR_CRATE_EXHIBITOR_MISMATCH,
                       expected_status=422)

        assert get_crate(acme_crate["id"])["shipment_id"] is None, (
            "the consignor's own crate is not stamped by a refused receipt"
        )
        assert get_crate(borealis_crate["id"])["shipment_id"] is None, (
            "the foreign crate is not stamped by a refused receipt"
        )


class TestShipmentBubblesUpFromItsCrates:
    def test_direct_receipt_reaches_delivered_only_when_the_second_crate_lands(self, api):
        """PRD §3.6: "Whenever every crate belonging to a shipment has reached `ON_SHOW_FLOOR`, that shipment bubbles up to `DELIVERED_TO_BOOTH`."
        PRD §3.6: "`DELIVERED_TO_BOOTH` is reached when every crate on the shipment has reached `ON_SHOW_FLOOR` — from `IN_TRANSIT` for advance freight, and directly from `RECEIVED` for direct-to-show freight, which never passes through `IN_TRANSIT`."
        PRD §3.6: "A crate reaches `ON_SHOW_FLOOR` from `REGISTERED`, from `IN_TRANSIT_TO_SHOW` or from `EMPTY_STORED`, again requiring a non-null `shipment_id` and requiring the shipment's show to be in `MOVE_IN`, `ON_SITE` or `MOVE_OUT`; every movement whose show-status requirement is unmet is refused with `ERR_SHOW_NOT_ACCEPTING`."
        PRD §3.6: "Reaching it recomputes no charge: `drayage_charge_cents` is frozen at receipt and never re-derived."

        Design: Corner/state_machines/shipment_bubbles_up_to_delivered_when_all_crates_reach_floor
        """
        ground = setup_show_ground(
            show_status="OPEN_FOR_ORDERS", with_warehouse=True,
            warehouse_overrides={"dock_capacity_cwt": 300},
            venue_overrides=VENUE_FORKLIFT_6000)
        show_id = ground["show"]["id"]
        exhibitor_id = ground["exhibitor"]["id"]
        crate_a = register_crate(exhibitor_id, crate_label="ACME-C1",
                                 crate_type="WOOD_CRATE", weight_lbs=1250)
        crate_b = register_crate(exhibitor_id, crate_label="ACME-C2",
                                 crate_type="WOOD_CRATE", weight_lbs=830)
        shipment = receive_shipment(show_id, exhibitor_id,
                                    [crate_a["id"], crate_b["id"]],
                                    warehouse_id=ground["warehouse"]["id"],
                                    channel="DIRECT_TO_SHOW",
                                    declared_value_coverage=False)
        for status in ("ADVANCE_CLOSED", "MOVE_IN", "ON_SITE"):
            advance_show(show_id, status)

        move_crate(crate_a["id"], "ON_SHOW_FLOOR")
        half_delivered = get_shipment(shipment["id"])
        assert half_delivered["status"] == "RECEIVED", (
            "with only one of two crates on the floor the direct receipt stays RECEIVED, "
            f"got {half_delivered['status']}"
        )

        move_crate(crate_b["id"], "ON_SHOW_FLOOR")
        delivered = get_shipment(shipment["id"])
        assert delivered["status"] == "DELIVERED_TO_BOOTH", (
            "the second crate landing on the floor bubbles the receipt up, "
            f"got {delivered['status']}"
        )
        assert delivered["drayage_charge_cents"] == 241500, (
            "the direct-to-show charge is frozen at receipt and never re-derived, "
            f"got {delivered['drayage_charge_cents']}"
        )
