"""Delivery slot capacity/equipment guard and delivery-fee boundaries."""
from test_helpers import (
    TEST_USERS,
    assert_delivery,
    confirm_order,
    convert_to_order,
    create_quoted_takeoff,
    make_account,
    make_branch,
    make_job,
    make_lot,
    make_product,
    make_slot,
    setup_order_scenario,
    validate_error,
    validate_success,
    ApiErrorId,
)

DISPATCH = TEST_USERS["dispatcher_headers"]


class TestSlotCapacityThreshold:
    def test_second_delivery_into_full_slot_rejected(self, api):
        """PRD §3.5: "The delivery's equipment must match the slot's
        `equipment_type`, and the slot must still have room — its
        `booked_count` below its `capacity`; both conditions are guarded by
        `ERR_SLOT_FULL`."

        Slot capacity 1 already holds one SCHEDULED delivery; a second
        delivery into the same bucket is rejected.

        Design: Difficulty/resource_temporal_overlap/delivery_slot_capacity_threshold
        """
        branch = make_branch("BR-O1")
        product = make_product("SH-O1", price=2000)
        make_lot(branch["id"], product["id"], on_hand=500)
        account = make_account(name="Overlap Co")
        job = make_job(account["id"])
        takeoff_a = create_quoted_takeoff(job["id"], product["id"], 5.0, 0, 0)
        order_a = convert_to_order(takeoff_a["id"], branch["id"],
                                   account["id"])
        confirm_order(order_a["id"], account["id"])
        slot = make_slot(branch["id"], slot_date="2026-08-15",
                         equipment_type="GROUND", capacity=1)
        first = validate_success(api.schedule_delivery(
            order_a["id"], slot["id"], "GROUND", DISPATCH), expected_status=201)
        assert_delivery(first)

        takeoff_b = create_quoted_takeoff(job["id"], product["id"], 5.0, 0, 0)
        order_b = convert_to_order(takeoff_b["id"], branch["id"],
                                   account["id"])
        confirm_order(order_b["id"], account["id"])
        resp = api.schedule_delivery(order_b["id"], slot["id"], "GROUND",
                                     DISPATCH)
        validate_error(resp, ApiErrorId.ERR_SLOT_FULL)

    def test_equipment_mismatch_rejected_even_with_free_capacity(self, api):
        """PRD §3.5: "The delivery's equipment must match the slot's
        `equipment_type`, and the slot must still have room — its
        `booked_count` below its `capacity`; both conditions are guarded by
        `ERR_SLOT_FULL`."

        A GROUND delivery aimed at a ROOFTOP_CONVEYOR slot with free capacity
        is rejected by the same error.

        Design: Difficulty/resource_temporal_overlap/delivery_slot_capacity_threshold
        """
        ctx = setup_order_scenario(branch_code="BR-O2", sku="SH-O2",
                                   roof_squares=5.0, company_name="Mismatch Co")
        slot = make_slot(ctx["branch"]["id"], slot_date="2026-08-15",
                         equipment_type="ROOFTOP_CONVEYOR", capacity=3)
        resp = api.schedule_delivery(ctx["order"]["id"], slot["id"], "GROUND",
                                     DISPATCH)
        validate_error(resp, ApiErrorId.ERR_SLOT_FULL)


class TestDeliveryFeeBoundaries:
    def test_exactly_forty_bundles_pays_no_weight_surcharge(self, api):
        """PRD §3.5: "A weight surcharge applies only above the heavy-load
        line of forty bundles: the surcharge is the excess over forty bundles
        times 350 cents per bundle, the boundary is strict, and a delivery of
        exactly forty bundles pays no surcharge at all."
        PRD §3.5: "Crane work adds a flat `crane_fee_cents` of 60,000 cents
        ($600.00) whenever the equipment type is `CRANE`, independent of how
        many bundles ride the hook, and zero otherwise; the fee is the base
        plus the surcharge plus the crane component, all in integer cents."

        10.0 squares * 4.0 = exactly 40 bundles on ROOFTOP_CONVEYOR:
        fee = 22500, crane component 0.

        Design: Difficulty/boundary_precision_check/delivery_fee_at_exactly_40_bundles_no_surcharge
        """
        ctx = setup_order_scenario(branch_code="BR-B1", sku="SH-B1",
                                   price=3000, bps=4.0, roof_squares=10.0,
                                   company_name="Boundary Co")
        slot = make_slot(ctx["branch"]["id"], slot_date="2026-08-14",
                         equipment_type="ROOFTOP_CONVEYOR", capacity=2)
        delivery = validate_success(api.schedule_delivery(
            ctx["order"]["id"], slot["id"], "ROOFTOP_CONVEYOR", DISPATCH),
            expected_status=201)
        assert delivery["bundle_count"] == 40
        assert delivery["fee_cents"] == 22500
        assert delivery["crane_fee_cents"] == 0

    def test_forty_one_bundles_pays_one_bundle_surcharge(self, api):
        """PRD §3.5: "A weight surcharge applies only above the heavy-load
        line of forty bundles: the surcharge is the excess over forty bundles
        times 350 cents per bundle, the boundary is strict, and a delivery of
        exactly forty bundles pays no surcharge at all."

        10.25 squares * 4.0 = 41 bundles on ROOFTOP_CONVEYOR:
        fee = 22500 + 1*350 = 22850.

        Design: Difficulty/boundary_precision_check/delivery_fee_at_exactly_40_bundles_no_surcharge
        """
        ctx = setup_order_scenario(branch_code="BR-B1B", sku="SH-B1B",
                                   price=3000, bps=4.0, roof_squares=10.25,
                                   company_name="Boundary Plus")
        slot = make_slot(ctx["branch"]["id"], slot_date="2026-08-14",
                         equipment_type="ROOFTOP_CONVEYOR", capacity=2)
        delivery = validate_success(api.schedule_delivery(
            ctx["order"]["id"], slot["id"], "ROOFTOP_CONVEYOR", DISPATCH),
            expected_status=201)
        assert delivery["bundle_count"] == 41
        assert delivery["fee_cents"] == 22850
        assert delivery["crane_fee_cents"] == 0

    def test_crane_fee_is_flat_regardless_of_bundle_count(self, api):
        """PRD §3.5: "Crane work adds a flat `crane_fee_cents` of 60,000 cents
        ($600.00) whenever the equipment type is `CRANE`, independent of how
        many bundles ride the hook, and zero otherwise; the fee is the base
        plus the surcharge plus the crane component, all in integer cents."

        10.0 squares * 5.0 = 50 bundles on CRANE:
        fee = 22500 + (50-40)*350 + 60000 = 86000; crane component 60000.

        Design: Corner/calculations/delivery_fee_crane_flat_regardless_of_bundles
        """
        ctx = setup_order_scenario(branch_code="BR-CA3", sku="SH-CA3",
                                   price=2000, bps=5.0, roof_squares=10.0,
                                   on_hand=200, company_name="Calc3 Co")
        slot = make_slot(ctx["branch"]["id"], slot_date="2026-08-16",
                         equipment_type="CRANE", capacity=2)
        delivery = validate_success(api.schedule_delivery(
            ctx["order"]["id"], slot["id"], "CRANE", DISPATCH),
            expected_status=201)
        assert delivery["bundle_count"] == 50
        assert delivery["fee_cents"] == 86000
        assert delivery["crane_fee_cents"] == 60000
