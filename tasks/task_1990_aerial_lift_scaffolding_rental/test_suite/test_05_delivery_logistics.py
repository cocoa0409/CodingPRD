"""Delivery and pickup logistics: standby charges, labor charges, route
buffers, trip failure/reschedule, and rentability at completion."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, create_delivery_trip_payload, create_trip_completion_payload,
    create_trip_failure_payload, create_trip_reschedule_payload,
    create_customer, create_equipment_class, create_equipment_unit,
    create_contract, add_line, activate_contract, set_clock,
    schedule_trip, start_trip, setup_active_rental,
    setup_draft_contract_with_line, get_line, get_trip, get_unit, get_invoice,
    make_driver_headers, assert_delivery_trip, assert_invoice,
)


def _en_route_delivery(api, at_clock="2026-08-10T09:00:00Z", **rental_kwargs):
    """Active contract, RESERVED line, DELIVERY trip started (EN_ROUTE) with
    the logical clock advanced to at_clock. Returns (ctx, trip)."""
    ctx = setup_draft_contract_with_line(**rental_kwargs)
    activate_contract(ctx["contract"]["id"])
    trip = schedule_trip(ctx["contract"]["id"], ctx["line"]["id"], "DELIVERY",
                         "drv-1")
    set_clock(at_clock)
    start_trip(trip["id"], "drv-1")
    return ctx, trip


class TestStandbyCharges:
    def test_standby_exactly_thirty_minutes_is_free(self, api):
        """PRD §3.5: "a `standby_charge_cents` that grants the first thirty
        minutes of standby free and bills each minute beyond thirty at 250
        cents (a trip reporting twenty-five standby minutes pays nothing; one
        reporting ninety pays for sixty)".

        Design: Difficulty/boundary_precision_check/standby_free_window_boundary
        """
        ctx, trip = _en_route_delivery(api)
        completed = validate_success(api.complete_delivery_trip(
            trip["id"], create_trip_completion_payload(standby_minutes=30),
            make_driver_headers("drv-1")))
        assert_delivery_trip(completed)
        assert completed["standby_charge_cents"] == 0, (
            "the free window is inclusive of the thirtieth minute")

    def test_standby_thirty_one_minutes_bills_one(self, api):
        """PRD §3.5: "a `standby_charge_cents` that grants the first thirty
        minutes of standby free and bills each minute beyond thirty at 250
        cents".

        Design: Difficulty/boundary_precision_check/standby_free_window_boundary
        """
        ctx, trip = _en_route_delivery(api)
        completed = validate_success(api.complete_delivery_trip(
            trip["id"], create_trip_completion_payload(standby_minutes=31),
            make_driver_headers("drv-1")))
        assert completed["standby_charge_cents"] == 250, "(31 - 30) * 250"

    def test_standby_under_free_window(self, api):
        """PRD §3.5: "a trip reporting twenty-five standby minutes pays
        nothing" — the same rule bills ten minutes at zero.

        Design: Corner/calculations/standby_under_free_window
        """
        ctx, trip = _en_route_delivery(api)
        completed = validate_success(api.complete_delivery_trip(
            trip["id"], create_trip_completion_payload(standby_minutes=10),
            make_driver_headers("drv-1")))
        assert completed["standby_charge_cents"] == 0, "max(0, 10-30) * 250"


class TestLaborCharges:
    def test_scaffold_labor_on_invoice(self, api, rental_coordinator_headers):
        """PRD §3.5: "a `labor_charge_cents` that applies only to scaffolds —
        when the line's class has `category` `SCAFFOLD`, the labor charge is
        `crew_labor_hours` multiplied by 9,500 cents per hour, rounded half-up
        to whole cents" and "the contract's `logistics_subtotal_cents` — the
        sum of trip fee, standby charge, and labor charge across the
        contract's `COMPLETED` trips — is recomputed".

        Design: Corner/endpoints/invoice_logistics_subtotal_with_scaffold_labor
        """
        ctx, trip = _en_route_delivery(
            api,
            class_kwargs={
                "class_code": "SCAF5X5L", "category": "SCAFFOLD",
                "max_working_height_ft": 20, "min_rental_days": 2,
                "daily_rate_cents": 8000, "weekly_rate_cents": 30000,
                "monthly_rate_cents": 90000, "replacement_value_cents": 500000,
                "requires_engineering": True},
            requested_start_date="2026-08-10", requested_end_date="2026-08-20",
            required_working_height_ft=15,
            engineering_plan_ref="ENG-2026-114",
            ansi_standard_ref="OSHA 1926.451")
        completed = validate_success(api.complete_delivery_trip(
            trip["id"], create_trip_completion_payload(standby_minutes=20,
                                                       crew_labor_hours=2.5),
            make_driver_headers("drv-1")))
        assert completed["trip_fee_cents"] == 15000
        assert completed["standby_charge_cents"] == 0, "20 <= 30 free minutes"
        assert completed["labor_charge_cents"] == 23750, (
            "round_half_up(2.5 * 9500)")

        invoice = get_invoice(ctx["contract"]["id"])
        assert_invoice(invoice)
        assert invoice["logistics_subtotal_cents"] == 38750, "15000 + 0 + 23750"
        # OUT_ON_RENT provisional: on_rent 2026-08-10T09:00:00Z to
        # 2026-08-21T00:00:00Z = 10d15h -> 11 days ->
        # min(8000*11=88000, 30000*2=60000, 90000*1) = 60000.
        assert invoice["rental_subtotal_cents"] == 60000
        assert invoice["invoice_total_cents"] == 98750

    def test_aerial_labor_hours_ignored(self, api):
        """PRD §3.5: "while for `AERIAL_LIFT` lines the labor charge is zero
        regardless of the hours reported."

        Design: Corner/endpoints/aerial_labor_hours_ignored
        """
        ctx, trip = _en_route_delivery(api)
        completed = validate_success(api.complete_delivery_trip(
            trip["id"], create_trip_completion_payload(standby_minutes=0,
                                                       crew_labor_hours=3.0),
            make_driver_headers("drv-1")))
        assert completed["labor_charge_cents"] == 0, "AERIAL_LIFT category gate"


class TestTripFailureAndReschedule:
    def test_fail_then_reschedule_cycle(self, api, rental_coordinator_headers):
        """PRD §3.5: "The assigned driver may fail an `EN_ROUTE` trip — an
        access issue, a refused delivery — by supplying a `failure_reason`; a
        missing reason is rejected with `ERR_INVALID_REQUEST`, and the trip
        moves from `EN_ROUTE` to `FAILED` with its `version` incrementing and
        no charges or cascades. A `RentalCoordinator` may then reschedule a
        `FAILED` trip into a fresh `planned_start_utc`/`planned_end_utc`
        window, which must clear the route buffer against the trip's assigned
        driver (`ERR_ROUTE_WINDOW_CONFLICT`); rescheduling replaces the
        planned window, returns the trip to `SCHEDULED`, and increments its
        `version`."

        Design: Corner/state_machines/trip_fail_then_reschedule_cycle
        """
        ctx, trip = _en_route_delivery(api)
        failed = validate_success(api.fail_delivery_trip(
            trip["id"], create_trip_failure_payload("jobsite gate locked"),
            make_driver_headers("drv-1")))
        assert failed["status"] == "FAILED"

        rescheduled = validate_success(api.reschedule_delivery_trip(
            trip["id"], create_trip_reschedule_payload(
                "2026-08-11T08:00:00Z", "2026-08-11T10:00:00Z"),
            rental_coordinator_headers))
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["planned_start_utc"].startswith("2026-08-11T08:00:00")
        assert rescheduled["planned_end_utc"].startswith("2026-08-11T10:00:00")

        set_clock("2026-08-11T09:00:00Z")
        start_trip(trip["id"], "drv-1")
        completed = validate_success(api.complete_delivery_trip(
            trip["id"], create_trip_completion_payload(0, 0),
            make_driver_headers("drv-1")))
        assert completed["status"] == "COMPLETED"
        assert get_line(ctx["line"]["id"])["status"] == "OUT_ON_RENT", (
            "failed delivery did not consume the line")


class TestDriverRouteBuffer:
    def _three_line_contract(self):
        """Contract ACTIVE with RESERVED lines on three units (drv-9's first
        trip 2026-08-10T09:00:00Z-11:00:00Z buffered to [08:15, 11:45))."""
        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("Route Co", "ops@route.example")
        cls = create_equipment_class(class_code="S19R")
        units = [create_equipment_unit(cls["id"], f"S19R-00{i}")
                 for i in (1, 2, 3)]
        contract = create_contract(customer["id"], "40 Route Ct")
        lines = [add_line(contract["id"], u["id"], "2026-08-10",
                          "2026-08-15", 20) for u in units]
        activate_contract(contract["id"])
        trip_a = schedule_trip(contract["id"], lines[0]["id"], "DELIVERY",
                               "drv-9", "2026-08-10T09:00:00Z",
                               "2026-08-10T11:00:00Z")
        return contract, lines, trip_a

    def test_trip_inside_buffer_rejected(self, api, rental_coordinator_headers):
        """PRD §2.9: "A new trip for a given `driver_id` is rejected with
        `ERR_ROUTE_WINDOW_CONFLICT` (HTTP 409) when its planned window
        intersects the buffered window of any other trip assigned to the same
        driver in `SCHEDULED` or `EN_ROUTE` status, where the buffered window
        extends forty-five minutes before that trip's `planned_start_utc` and
        forty-five minutes after its `planned_end_utc`."

        Design: Difficulty/resource_temporal_overlap/driver_route_buffered_window
        """
        contract, lines, _trip_a = self._three_line_contract()
        res = api.create_delivery_trip(
            create_delivery_trip_payload(contract["id"], lines[1]["id"],
                                         "DELIVERY", "drv-9",
                                         "2026-08-10T11:30:00Z",
                                         "2026-08-10T13:00:00Z"),
            rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_ROUTE_WINDOW_CONFLICT)

    def test_trip_at_buffer_boundary_allowed(self, api,
                                             rental_coordinator_headers):
        """PRD §2.9: the buffered window "extends forty-five minutes before
        that trip's `planned_start_utc` and forty-five minutes after its
        `planned_end_utc`" — a new trip beginning exactly at the buffer end
        does not intersect it.

        Design: Difficulty/resource_temporal_overlap/driver_route_buffered_window
        """
        contract, lines, _trip_a = self._three_line_contract()
        trip_c = validate_success(api.create_delivery_trip(
            create_delivery_trip_payload(contract["id"], lines[2]["id"],
                                         "DELIVERY", "drv-9",
                                         "2026-08-10T11:45:00Z",
                                         "2026-08-10T13:00:00Z"),
            rental_coordinator_headers), 201)
        assert trip_c["status"] == "SCHEDULED"


class TestRentabilityAtCompletion:
    def test_delivery_completion_overdue_inspection_rejected(
            self, api, rental_coordinator_headers):
        """PRD §2.10: "A serialized unit is rentable only while two conditions
        hold: its `status` is `AVAILABLE`, and the logical-clock date is on or
        before its `next_inspection_due_date`. Any attempt to put an
        unrentable unit out on rent is rejected with `ERR_UNIT_NOT_RENTABLE`
        (HTTP 422) at the moment the delivery completes."

        Design: Corner/validations/delivery_completion_overdue_inspection_rejected
        """
        set_clock("2025-08-01T09:00:00Z")
        cls = create_equipment_class(class_code="S19OD")
        unit = create_equipment_unit(cls["id"], "S19OD-001")
        assert unit["next_inspection_due_date"] == "2026-08-01"

        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("Overdue Co", "ops@od.example")
        contract = create_contract(customer["id"], "17 Due Ln")
        line = add_line(contract["id"], unit["id"], "2026-08-10",
                        "2026-08-15", 20)
        activate_contract(contract["id"])
        trip = schedule_trip(contract["id"], line["id"], "DELIVERY", "drv-1",
                             "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")
        # Completion is attempted on 2026-08-10, past the 2026-08-01 due date.
        set_clock("2026-08-10T09:00:00Z")
        start_trip(trip["id"], "drv-1")
        res = api.complete_delivery_trip(
            trip["id"], create_trip_completion_payload(0, 0),
            make_driver_headers("drv-1"))
        validate_error(res, ApiErrorId.ERR_UNIT_NOT_RENTABLE)

        assert get_line(line["id"])["status"] == "RESERVED", (
            "rejected completion does not move the line")
        assert get_unit(unit["id"])["status"] == "AVAILABLE", (
            "rejected completion does not move the unit")
