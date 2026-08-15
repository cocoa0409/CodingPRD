"""Shipments and the dock: stock reservation conservation, closed-interval window conflicts, full delivery lifecycle, booking gates, load timing, and no-show discipline."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_accepted_stock_scenario, setup_shipment_with_appointment,
    setup_booked_shipment, setup_running_scenario,
    create_shipment, create_appointment, book_shipment,
    create_shipment_payload, create_dock_appointment_payload,
    get_order_summary, set_clock, list_order_slots,
    assert_order_stock_conservation,
    api_client, ApiErrorId, TEST_USERS,
    DOCK_WINDOW_START, DOCK_WINDOW_END, DOCK_LOAD_CLOCK,
)

ADMIN = TEST_USERS["plant_admin"]
LOGISTICS = TEST_USERS["logistics_coordinator"]
SCHEDULER = TEST_USERS["production_scheduler"]


class TestStockConservation:
    def _setup_two_bookings(self, api):
        """Accepted stock 11880; shipment A (2928) BOOKED; shipment B (1000) BOOKED."""
        ctx = setup_shipment_with_appointment(quantity=2928)
        ctx["ship_a"] = book_shipment(ctx["shipment"]["id"],
                                      ctx["appointment"]["id"])
        ship_b = create_shipment(ctx["order"]["id"], 1000)
        appt_b = create_appointment(ship_b["id"], dock_door=1,
                                    window_start="2026-08-03T13:00:00Z",
                                    window_end="2026-08-03T15:00:00Z")
        ctx["ship_b"] = book_shipment(ship_b["id"], appt_b["id"])
        ctx["appt_b"] = appt_b
        return ctx

    def test_bookings_reserve_accepted_stock(self, api):
        """PRD §3.5: "`quantity_reserved` sums the `quantity` of the order's shipments in `BOOKED`, `LOADING`, or `IN_TRANSIT`, `quantity_shipped` sums those `DELIVERED`, and `quantity_unallocated` is `quantity_accepted` minus reserved minus shipped."
PRD §3.8: "Booking records the appointment in `booked_appointment_id`, reserves the quantity against the order".

Design: Difficulty/compensating_invariant/order_accepted_stock_conservation_across_book_and_cancel"""
        ctx = self._setup_two_bookings(api)
        summary = get_order_summary(ctx["order"]["id"])
        assert summary["quantity_accepted"] == 11880
        assert summary["quantity_reserved"] == 3928        # 2928 + 1000
        assert summary["quantity_unallocated"] == 7952     # 11880 - 3928
        assert summary["quantity_shipped"] == 0
        assert_order_stock_conservation(summary)

    def test_cancel_booked_shipment_releases_reservation(self, api):
        """PRD §3.8: "Cancelling a `BOOKED` one also releases its reservation on the order, cancels the booked appointment if it is still `RESERVED`, and clears `booked_appointment_id` to null."

Design: Difficulty/compensating_invariant/order_accepted_stock_conservation_across_book_and_cancel"""
        ctx = self._setup_two_bookings(api)
        cancelled = validate_success(
            api.cancel_shipment(ctx["ship_b"]["id"], LOGISTICS), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["booked_appointment_id"] is None

        summary = get_order_summary(ctx["order"]["id"])
        assert summary["quantity_accepted"] == 11880
        assert summary["quantity_reserved"] == 2928        # only A remains
        assert summary["quantity_unallocated"] == 8952     # 11880 - 2928
        assert summary["quantity_shipped"] == 0
        assert_order_stock_conservation(summary)

        appt_b = get_success_data(
            api.get_dock_appointment(ctx["appt_b"]["id"], LOGISTICS))
        assert appt_b["status"] == "CANCELLED"


class TestDockWindowClosedIntervals:
    def _setup_reserved_appointment(self, api):
        return setup_shipment_with_appointment(quantity=1000)

    def test_touching_windows_conflict(self, api):
        """PRD §3.8: "Windows on the same door must not intersect: because the intervals are closed, two appointments on one door that merely touch endpoints already conflict, and any overlap with another `RESERVED` or `OCCUPIED` appointment on that door is refused with `ERR_DOCK_WINDOW_CONFLICT`."

Design: Difficulty/resource_temporal_overlap/dock_window_closed_interval_touching_conflict"""
        ctx = self._setup_reserved_appointment(api)
        # existing [10:00, 12:00]; new window starts exactly at 12:00
        res = api.create_dock_appointment(
            create_dock_appointment_payload(ctx["shipment"]["id"], 1,
                                            "2026-08-03T12:00:00Z",
                                            "2026-08-03T14:00:00Z"),
            LOGISTICS)
        validate_error(res, ApiErrorId.ERR_DOCK_WINDOW_CONFLICT)

    def test_one_minute_clearance_allowed(self, api):
        """PRD §3.8: "because the intervals are closed, two appointments on one door that merely touch endpoints already conflict". A start one minute after the existing window's end does not touch. "A new appointment starts `RESERVED`."

Design: Difficulty/resource_temporal_overlap/dock_window_closed_interval_touching_conflict"""
        ctx = self._setup_reserved_appointment(api)
        res = api.create_dock_appointment(
            create_dock_appointment_payload(ctx["shipment"]["id"], 1,
                                            "2026-08-03T12:01:00Z",
                                            "2026-08-03T14:00:00Z"),
            LOGISTICS)
        appt = validate_success(res, 201)
        assert appt["status"] == "RESERVED"


class TestDeliveryLifecycle:
    def test_summary_after_delivery_and_complete(self, api):
        """PRD §3.8: "The same computation, persisted, happens when a real shipment is created against an order". "delivery moves it from `IN_TRANSIT` to `DELIVERED`, completes the appointment (`OCCUPIED` → `COMPLETED`), and settles the order's `quantity_shipped`, `quantity_reserved`, and `quantity_unallocated`."
PRD §3.5: "completion moves the order's `IN_PROGRESS` slot to `COMPLETED` and again rests the line at `CHANGEOVER`." "A computed summary read on the order exposes `quantity_produced`, `quantity_good`, `quantity_scrapped`, `quantity_accepted`, `quantity_qc_scrapped`, `quantity_reserved`, `quantity_shipped`, and `quantity_unallocated` in one payload."

Design: Corner/endpoints/order_summary_after_delivery_and_complete"""
        ctx = setup_shipment_with_appointment(quantity=2928)
        # persisted at creation: chargeable 2000.0 kg -> 500*120+1500*90
        assert ctx["shipment"]["freight_cost_cents"] == 195000
        assert ctx["shipment"]["status"] == "QUOTED"

        book_shipment(ctx["shipment"]["id"], ctx["appointment"]["id"])
        set_clock(DOCK_LOAD_CLOCK)  # inside [10:00, 12:00]
        validate_success(api.load_shipment(ctx["shipment"]["id"], LOGISTICS), 200)
        validate_success(api.dispatch_shipment(ctx["shipment"]["id"], LOGISTICS), 200)
        delivered = validate_success(
            api.deliver_shipment(ctx["shipment"]["id"], LOGISTICS), 200)
        assert delivered["status"] == "DELIVERED"

        appt = get_success_data(
            api.get_dock_appointment(ctx["appointment"]["id"], LOGISTICS))
        assert appt["status"] == "COMPLETED"

        completed = validate_success(
            api.complete_production_order(ctx["order"]["id"], SCHEDULER), 200)
        assert completed["status"] == "COMPLETED"

        slots = list_order_slots(ctx["order"]["id"])
        assert slots[0]["status"] == "COMPLETED"
        line = get_success_data(
            api.get_machine_line(ctx["line"]["id"], SCHEDULER))
        assert line["status"] == "CHANGEOVER"

        summary = get_order_summary(ctx["order"]["id"])
        assert summary["quantity_produced"] == 12000      # 11880 good + 120 scrap
        assert summary["quantity_good"] == 11880
        assert summary["quantity_scrapped"] == 120
        assert summary["quantity_accepted"] == 11880
        assert summary["quantity_reserved"] == 0
        assert summary["quantity_shipped"] == 2928
        assert summary["quantity_unallocated"] == 8952
        assert_order_stock_conservation(summary)


class TestBookingGates:
    def test_book_more_than_unallocated_rejected(self, api):
        """PRD §3.8: "the shipment's `quantity` must not exceed the order's `quantity_unallocated`, else `ERR_INSUFFICIENT_ACCEPTED_STOCK`."

Design: Corner/validations/book_more_than_unallocated_rejected"""
        ctx = setup_shipment_with_appointment(quantity=20000)
        res = api.book_shipment(
            ctx["shipment"]["id"],
            {"dock_appointment_id": ctx["appointment"]["id"]}, LOGISTICS)
        # 20000 > 11880 unallocated accepted units
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_ACCEPTED_STOCK)
        shipment = get_success_data(
            api.get_shipment(ctx["shipment"]["id"], LOGISTICS))
        assert shipment["status"] == "QUOTED"

    def test_book_with_cancelled_appointment_rejected(self, api):
        """PRD §3.8: "the appointment must be `RESERVED` and must belong to this shipment, else `ERR_APPOINTMENT_NOT_RESERVED`".

Design: Corner/validations/book_with_cancelled_appointment_rejected"""
        ctx = setup_shipment_with_appointment(quantity=1000)
        validate_success(
            api.cancel_dock_appointment(ctx["appointment"]["id"], LOGISTICS), 200)
        res = api.book_shipment(
            ctx["shipment"]["id"],
            {"dock_appointment_id": ctx["appointment"]["id"]}, LOGISTICS)
        validate_error(res, ApiErrorId.ERR_APPOINTMENT_NOT_RESERVED)


class TestLoadTiming:
    def test_load_outside_window_rejected(self, api):
        """PRD §3.8: "the coordinator may start loading only while the logical clock sits inside the booked appointment's window, from `window_start` through `window_end` inclusive at both ends — outside the window the attempt is `ERR_OUTSIDE_DOCK_WINDOW`".

Design: Corner/endpoints/load_outside_window_rejected"""
        ctx = setup_booked_shipment(quantity=1000)
        set_clock("2026-08-03T13:00:00Z")  # past the [10:00, 12:00] window
        res = api.load_shipment(ctx["shipment"]["id"], LOGISTICS)
        validate_error(res, ApiErrorId.ERR_OUTSIDE_DOCK_WINDOW)
        shipment = get_success_data(
            api.get_shipment(ctx["shipment"]["id"], LOGISTICS))
        assert shipment["status"] == "BOOKED"
        appt = get_success_data(
            api.get_dock_appointment(ctx["appointment"]["id"], LOGISTICS))
        assert appt["status"] == "RESERVED"


class TestShipmentCreation:
    def test_mode_mismatch_rejected(self, api):
        """PRD §3.8: "a `shipment_mode` consistent with the order's `logistics_mode`: `WAREHOUSE` orders ship `FINISHED_BOTTLES`, `BLOW_ON_SITE` orders ship `PREFORMS`, and a crossed pairing is `ERR_MODE_MISMATCH`."

Design: Corner/endpoints/shipment_mode_mismatch_rejected"""
        ctx = setup_running_scenario(with_rate_card=True)
        res = api.create_shipment(
            create_shipment_payload(ctx["order"]["id"], 1000, "PREFORMS"),
            LOGISTICS)
        validate_error(res, ApiErrorId.ERR_MODE_MISMATCH)

    def test_zero_quantity_shipment_rejected(self, api):
        """PRD §3.8: "a positive integer `quantity`, else `ERR_ZERO_QUANTITY`".

Design: Corner/endpoints/zero_quantity_shipment_rejected"""
        ctx = setup_running_scenario(with_rate_card=True)
        res = api.create_shipment(
            create_shipment_payload(ctx["order"]["id"], 0, "FINISHED_BOTTLES"),
            LOGISTICS)
        validate_error(res, ApiErrorId.ERR_ZERO_QUANTITY)


class TestNoShowTiming:
    def test_no_show_inside_window_rejected(self, api):
        """PRD §3.8: "the coordinator marks the appointment no-show — allowed only once the logical clock has passed `window_end` strictly, else `ERR_INVALID_STATE`".

Design: Corner/state_machines/dock_no_show_inside_window_rejected"""
        ctx = setup_shipment_with_appointment(
            quantity=1000, appointment_kwargs={"dock_door": 2})
        set_clock("2026-08-03T11:00:00Z")  # inside the [10:00, 12:00] window
        res = api.no_show_dock_appointment(ctx["appointment"]["id"], LOGISTICS)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        appt = get_success_data(
            api.get_dock_appointment(ctx["appointment"]["id"], LOGISTICS))
        assert appt["status"] == "RESERVED"
