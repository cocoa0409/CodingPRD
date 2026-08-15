"""Order lifecycle and routing: weather-hold cycle, stop remove revert, billing
dimension, van water and vehicle-slot conservation, stop planning (PRD §3.3-§3.6)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_stop_to_route, confirm_order, create_confirmed_order,
    create_customer, create_fleet_contract, create_route, create_site,
    create_technician, create_van,
    create_vehicles, create_wash_order, evaluate_weather, generate_invoice,
    get_order, get_route, get_van, invoice_event, list_route_stops,
    make_customer_headers, make_technician_headers, order_event, request_rewash,
    route_event, set_clock, setup_completed_order, setup_customer_site_vehicles,
    stop_event, validate_error, validate_paginated, validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _fleet_order_on_aug10():
    """FLEET customer with ACTIVE contract; 1 SEDAN; order window 2026-08-10
    13:00-14:00 CONFIRMED. Returns ctx."""
    customer = create_customer(customer_type="FLEET")
    site = create_site(customer["id"], name="LOT")
    vehicle_ids = create_vehicles(customer["id"], site["id"], 1, "SEDAN")
    contract = create_fleet_contract(customer["id"])
    order = create_wash_order(
        customer["id"], site["id"], vehicle_ids,
        scheduled_window_start="2026-08-10T13:00:00Z",
        scheduled_window_end="2026-08-10T14:00:00Z",
    )
    order = confirm_order(order["id"])
    return {"customer": customer, "site": site, "vehicle_ids": vehicle_ids,
            "contract": contract, "order": order}


class TestWashOrderCycleAndBillingDimension:
    def test_weather_hold_cycle_and_stop_remove_revert(self, api):
        """PRD §3.6: "Success replaces `scheduled_window_start` and
        `scheduled_window_end`, clears `hold_reason` and `held_at`, returns the order
        to `SCHEDULED`, and increments its `version`."
        PRD §3.5: "removal moves the stop to `CANCELLED`, returns the order from
        `ASSIGNED` to `SCHEDULED` with the order's `version` incremented, and releases
        the reservation."

        Design: Difficulty/non_linear_state_machine/wash_order_cycle_and_billing_dimension
        """
        ctx = _fleet_order_on_aug10()
        # freeze on the order's scheduled date holds the unrouted SCHEDULED order
        evaluate_weather("2026-08-10", 30, 10)
        held = get_order(ctx["order"]["id"])
        assert held["status"] == "WEATHER_HELD"  # cycle leg 1
        assert held["hold_reason"] == "WEATHER_FREEZE"
        rescheduled = validate_success(api.reschedule_wash_order(
            ctx["order"]["id"],
            {"scheduled_window_start": "2026-08-12T13:00:00Z",
             "scheduled_window_end": "2026-08-12T14:00:00Z",
             "expected_wash_order_version": held["version"]},
            DISPATCHER,
        ))
        assert rescheduled["status"] == "SCHEDULED"  # cycle leg 2 closes the loop
        assert rescheduled.get("hold_reason") is None
        # assign then remove the stop: ASSIGNED -> SCHEDULED revert
        van = create_van(reclaim_system="BASIC", load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-12", van["id"], tech["id"])
        stop = add_stop_to_route(route["id"], ctx["order"]["id"])
        assert get_order(ctx["order"]["id"])["status"] == "ASSIGNED"
        stop_event(route["id"], stop["id"], "REMOVE")
        assert get_order(ctx["order"]["id"])["status"] == "SCHEDULED"

    def test_billing_dimension_advances_independently_of_lifecycle(self, api):
        """PRD §3.9: "an order's `billing_status` — `UNBILLED`, `INVOICED`, `PAID`, or
        `WAIVED` — is an independent dimension living on the same WashOrder row as the
        lifecycle status; rewash orders are created already `WAIVED`, and the two
        dimensions never block each other."

        Design: Difficulty/non_linear_state_machine/wash_order_cycle_and_billing_dimension
        """
        ctx = _fleet_order_on_aug10()
        evaluate_weather("2026-08-10", 30, 10)
        held = get_order(ctx["order"]["id"])
        validate_success(api.reschedule_wash_order(
            ctx["order"]["id"],
            {"scheduled_window_start": "2026-08-12T13:00:00Z",
             "scheduled_window_end": "2026-08-12T14:00:00Z",
             "expected_wash_order_version": held["version"]},
            DISPATCHER,
        ))
        van = create_van(reclaim_system="BASIC", load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-12", van["id"], tech["id"])
        stop = add_stop_to_route(route["id"], ctx["order"]["id"])
        route_event(route["id"], "PUBLISH")
        stop_event(route["id"], stop["id"], "ARRIVE", tech["id"])
        order_event(ctx["order"]["id"], "START", make_technician_headers(tech["id"]))
        completed = order_event(
            ctx["order"]["id"], "COMPLETE", make_technician_headers(tech["id"]),
            vehicles_washed_ids=ctx["vehicle_ids"],
        )
        # contract SEDAN rate 3000, single vehicle, no tier
        assert completed["final_cents"] == 3000
        assert completed["status"] == "COMPLETED"
        invoice = generate_invoice(ctx["contract"]["id"], "2026-08", "FINAL")
        invoice_event(invoice["id"], "ISSUE")
        invoice_event(invoice["id"], "MARK_PAID")
        final = get_order(ctx["order"]["id"])
        assert final["status"] == "COMPLETED"
        assert final["billing_status"] == "PAID"


class TestVanWaterBudgetConservedOnAddRemove:
    def _scenario(self):
        ctx = setup_customer_site_vehicles(num_vehicles=5, vehicle_class="SEDAN")
        order = create_confirmed_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
            scheduled_window_start="2026-08-05T13:00:00Z",
            scheduled_window_end="2026-08-05T14:00:00Z",
        )
        van = create_van(reclaim_system="BASIC", load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-05", van["id"], tech["id"])
        ctx.update({"order": order, "van": van, "technician": tech, "route": route})
        return ctx

    def test_stop_add_reserves_projected_net_draw(self, api):
        """PRD §3.4: "The stop's `reserved_water_gal` is the projected net draw for
        its order on this route's van — the gross gallons of the order's `vehicle_ids`
        multiplied by the fraction not recovered (§2.8) — and the van's
        `water_reserved_gal` grows by the same amount."
        PRD §2.8: "At all times the loaded gallons equal the sum of used gallons,
        reserved gallons, and the free remainder, and the free remainder never goes
        negative."

        Design: Difficulty/compensating_invariant/van_water_budget_conserved_on_add_remove
        """
        ctx = self._scenario()
        stop = add_stop_to_route(ctx["route"]["id"], ctx["order"]["id"])
        # 5 sedans: 40 gross x (1 - 0.60) = 16.0
        assert stop["reserved_water_gal"] == 16.0
        van = get_van(ctx["van"]["id"])
        assert van["water_reserved_gal"] == 16.0
        assert van["water_used_gal"] == 0.0
        assert van["water_loaded_gal"] == 96.0
        # identity: 96 == 0 + 16 + 80
        assert van["water_loaded_gal"] - van["water_used_gal"] - van["water_reserved_gal"] == 80.0

    def test_stop_remove_releases_reservation_exactly(self, api):
        """PRD §3.5: "removal moves the stop to `CANCELLED`, returns the order from
        `ASSIGNED` to `SCHEDULED` with the order's `version` incremented, and releases
        the reservation."

        Design: Difficulty/compensating_invariant/van_water_budget_conserved_on_add_remove
        """
        ctx = self._scenario()
        stop = add_stop_to_route(ctx["route"]["id"], ctx["order"]["id"])
        stop_event(ctx["route"]["id"], stop["id"], "REMOVE")
        van = get_van(ctx["van"]["id"])
        assert van["water_reserved_gal"] == 0.0
        assert van["water_used_gal"] == 0.0
        assert van["water_loaded_gal"] == 96.0
        assert get_order(ctx["order"]["id"])["status"] == "SCHEDULED"


class TestRouteVehicleCapacityConservedOnAddRemove:
    def _scenario(self):
        ctx = setup_customer_site_vehicles(num_vehicles=5, vehicle_class="SEDAN")
        order_a = create_confirmed_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
            scheduled_window_start="2026-08-05T13:00:00Z",
            scheduled_window_end="2026-08-05T14:00:00Z",
        )
        order_b = create_confirmed_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
            scheduled_window_start="2026-08-05T14:00:00Z",
            scheduled_window_end="2026-08-05T15:00:00Z",
        )
        van = create_van(reclaim_system="BASIC", load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-05", van["id"], tech["id"])
        ctx.update({"order_a": order_a, "order_b": order_b, "van": van,
                    "technician": tech, "route": route})
        return ctx

    def test_counter_grows_with_each_add(self, api):
        """PRD §3.4: "`assigned_vehicle_count` sums the `vehicle_count` of orders
        whose stop on this route is `PLANNED`, `ARRIVED`, or `DONE`, and
        `reserved_water_gal` sums the `reserved_water_gal` of stops in `PLANNED` or
        `ARRIVED`. Both are recomputed whenever stops change state."

        Design: Difficulty/compensating_invariant/route_vehicle_capacity_conserved_on_add_remove
        """
        ctx = self._scenario()
        add_stop_to_route(ctx["route"]["id"], ctx["order_a"]["id"])
        assert get_route(ctx["route"]["id"])["assigned_vehicle_count"] == 5
        add_stop_to_route(ctx["route"]["id"], ctx["order_b"]["id"])
        assert get_route(ctx["route"]["id"])["assigned_vehicle_count"] == 10

    def test_remove_restores_counter_exactly(self, api):
        """PRD §3.4: "Both are recomputed whenever stops change state."

        Design: Difficulty/compensating_invariant/route_vehicle_capacity_conserved_on_add_remove
        """
        ctx = self._scenario()
        add_stop_to_route(ctx["route"]["id"], ctx["order_a"]["id"])
        stop_b = add_stop_to_route(ctx["route"]["id"], ctx["order_b"]["id"])
        stop_event(ctx["route"]["id"], stop_b["id"], "REMOVE")
        assert get_route(ctx["route"]["id"])["assigned_vehicle_count"] == 5
        assert get_order(ctx["order_b"]["id"])["status"] == "SCHEDULED"


class TestStartWithoutArriveReturnsInvalidState:
    def test_start_with_planned_stop_rejected(self, api):
        """PRD §3.5: "The order's non-cancelled stop must be `ARRIVED` (otherwise
        `ERR_INVALID_STATE`), the site must be `ACTIVE` (`ERR_SITE_SUSPENDED`), and
        when `requires_inspection` is true a `SUBMITTED` InspectionReport must already
        exist for the order (`ERR_INSPECTION_REQUIRED`)."

        Design: Corner/state_machines/start_without_arrive_returns_invalid_state
        """
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        order = create_confirmed_order(ctx["customer"]["id"], ctx["site"]["id"],
                                       ctx["vehicle_ids"])
        van = create_van(load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-05", van["id"], tech["id"])
        stop = add_stop_to_route(route["id"], order["id"])
        route_event(route["id"], "PUBLISH")
        resp = api.wash_order_event(
            order["id"], {"event_type": "START"}, make_technician_headers(tech["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(order["id"])["status"] == "ASSIGNED"
        stops = list_route_stops(route["id"])
        assert stops[0]["status"] == "PLANNED"


class TestClosedOrderRejectsFurtherEvents:
    def test_run_daily_closes_at_exactly_72h_then_terminal_lockdown(self, api):
        """PRD §3.6: "Orders still `COMPLETED` whose `completed_at` is at or before
        the logical clock minus 72 hours move to `CLOSED` — this is the guarantee
        window lapsing without a claim or rewash."
        PRD §2.6: "State eligibility — the target entity is in a valid from-state for
        the requested transition, else `ERR_INVALID_STATE`"

        Design: Corner/state_machines/closed_order_rejects_further_events
        """
        ctx = setup_completed_order(clock_pin="2026-08-05T10:00:00Z")
        set_clock("2026-08-08T10:00:00Z")  # exactly completed_at + 72h
        sweep = validate_success(api.run_daily(DISPATCHER))
        assert ctx["order"]["id"] in sweep["closed_order_ids"]
        resp = api.wash_order_event(ctx["order"]["id"], {"event_type": "CANCEL"},
                                    DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(ctx["order"]["id"])["status"] == "CLOSED"


class TestRouteUnpublishBlockedAfterArrival:
    def test_unpublish_allowed_then_blocked_after_arrive(self, api):
        """PRD §3.4: "From `DRAFT`, a dispatcher publishes the route (`DRAFT` →
        `PUBLISHED`), may unpublish it back to `DRAFT` only while no stop on it has
        reached `ARRIVED` or `DONE` (otherwise `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/route_unpublish_blocked_after_arrival
        """
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        order = create_confirmed_order(ctx["customer"]["id"], ctx["site"]["id"],
                                       ctx["vehicle_ids"])
        van = create_van(load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-05", van["id"], tech["id"])
        stop = add_stop_to_route(route["id"], order["id"])
        route_event(route["id"], "PUBLISH")
        reverted = route_event(route["id"], "UNPUBLISH")
        assert reverted["status"] == "DRAFT"
        route_event(route["id"], "PUBLISH")
        stop_event(route["id"], stop["id"], "ARRIVE", tech["id"])
        resp = api.route_event(route["id"], {"event_type": "UNPUBLISH"}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_route(route["id"])["status"] == "PUBLISHED"


class TestRewashCancelCompensatesOriginal:
    def test_cancel_open_rewash_reverts_original_to_completed(self, api):
        """PRD §3.8: "From there the pair resolves in one of two ways: the rewash
        completing closes the original (`REWASH_PENDING` → `CLOSED`, per §3.5), while
        the rewash being cancelled before completion reverts the original to
        `COMPLETED` as a compensating action."

        Design: Corner/state_machines/rewash_cancel_compensates_original
        """
        ctx = setup_completed_order(clock_pin="2026-08-05T10:00:00Z")
        rewash = request_rewash(ctx["order"]["id"], ctx["customer"]["id"])
        assert rewash["status"] == "SCHEDULED"
        cancelled = validate_success(api.wash_order_event(
            rewash["id"],
            {"event_type": "CANCEL", "cancel_reason": "CUSTOMER_REQUEST"},
            make_customer_headers(ctx["customer"]["id"]),
        ))
        assert cancelled["status"] == "CANCELLED"
        original = get_order(ctx["order"]["id"])
        assert original["status"] == "COMPLETED"


class TestStopSkipCancelsOrderNoShow:
    def test_skip_arrived_stop_cancels_order_and_releases_water(self, api):
        """PRD §3.5: "The route lead or a dispatcher may skip a stop in `PLANNED` or
        `ARRIVED`, moving it to `SKIPPED`; the order behind it is cancelled with
        `cancel_reason` `NO_SHOW` — from `ASSIGNED` when the stop was still planned,
        or from `ASSIGNED` or `IN_PROGRESS` when the crew had already arrived — and
        the stop's reservation is released with the route counters recomputed."

        Design: Corner/state_machines/stop_skip_cancels_order_no_show
        """
        ctx = setup_customer_site_vehicles(num_vehicles=5, vehicle_class="SEDAN")
        order = create_confirmed_order(ctx["customer"]["id"], ctx["site"]["id"],
                                       ctx["vehicle_ids"])
        van = create_van(load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-05", van["id"], tech["id"])
        stop = add_stop_to_route(route["id"], order["id"])
        route_event(route["id"], "PUBLISH")
        stop_event(route["id"], stop["id"], "ARRIVE", tech["id"])
        skipped = stop_event(route["id"], stop["id"], "SKIP", tech["id"])
        assert skipped["status"] == "SKIPPED"
        order = get_order(order["id"])
        assert order["status"] == "CANCELLED"
        assert order["cancel_reason"] == "NO_SHOW"
        assert get_van(van["id"])["water_reserved_gal"] == 0.0
        assert get_route(route["id"])["assigned_vehicle_count"] == 0


class TestRouteManualCancelReturnsOrdersToScheduled:
    def test_manual_cancel_returns_order_and_releases_water(self, api):
        """PRD §3.4: "Cancelling a route cascades: its stops in `PLANNED` or `ARRIVED`
        move to `CANCELLED` and release their reserved water from the van, and the
        orders behind those stops leave `ASSIGNED` — back to `SCHEDULED` on a manual
        cancellation, each such return incrementing the order's `version`, or to
        `WEATHER_HELD` with `hold_reason` `WEATHER_FREEZE` and `held_at` set on a
        weather one."

        Design: Corner/state_machines/route_manual_cancel_returns_orders_to_scheduled
        """
        ctx = setup_customer_site_vehicles(num_vehicles=5, vehicle_class="SEDAN")
        order = create_confirmed_order(ctx["customer"]["id"], ctx["site"]["id"],
                                       ctx["vehicle_ids"])
        van = create_van(load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-05", van["id"], tech["id"])
        stop = add_stop_to_route(route["id"], order["id"])
        route_event(route["id"], "PUBLISH")
        cancelled = route_event(route["id"], "CANCEL", cancel_reason="DISPATCH")
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "DISPATCH"
        order = get_order(order["id"])
        assert order["status"] == "SCHEDULED"
        assert get_van(van["id"])["water_reserved_gal"] == 0.0
        stops = list_route_stops(route["id"])
        assert stops[0]["status"] == "CANCELLED"


class TestRouteStopSequenceAndFirstWindowComputed:
    def test_first_stop_sequence_and_planned_window(self, api):
        """PRD §3.4: "The first stop's `planned_start_at` is the route's
        `shift_start_at` (or its 08:00:00 UTC default); each later stop starts twenty
        minutes of drive time after the previous stop's `planned_end_at`; and a stop's
        `planned_end_at` is its start plus setup plus service minutes."

        Design: Corner/entities/route_stop_sequence_and_first_window_computed
        """
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        order = create_confirmed_order(ctx["customer"]["id"], ctx["site"]["id"],
                                       ctx["vehicle_ids"])
        van = create_van(load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-05", van["id"], tech["id"])
        stop = add_stop_to_route(route["id"], order["id"])
        assert stop["sequence"] == 1
        # 8000 sqft lot: 15 setup + 20 service = 35 minutes
        assert stop["planned_start_at"] == "2026-08-05T08:00:00.000Z"
        assert stop["planned_end_at"] == "2026-08-05T08:35:00.000Z"
        # 8 gross x (1 - 0.60)
        assert stop["reserved_water_gal"] == 3.2


class TestLotSetupMinutesBoundary10000Sqft:
    def test_9999_takes_small_tier_10000_takes_medium(self, api):
        """PRD §3.4: "Setup time comes from the site's `lot_size_sqft`: 15 minutes
        under 10,000 square feet, 25 minutes from 10,000 up to 49,999, and 40 minutes
        at 50,000 or more."

        Design: Corner/calculations/lot_setup_minutes_boundary_10000_sqft
        """
        customer = create_customer()
        site_small = create_site(customer["id"], name="SMALL", lot_size_sqft=9999)
        site_medium = create_site(customer["id"], name="MEDIUM", lot_size_sqft=10000)
        veh_small = create_vehicles(customer["id"], site_small["id"], 1, "SEDAN")
        veh_medium = create_vehicles(customer["id"], site_medium["id"], 1, "SEDAN")
        order_small = create_confirmed_order(
            customer["id"], site_small["id"], veh_small,
            scheduled_window_start="2026-08-05T13:00:00Z",
            scheduled_window_end="2026-08-05T14:00:00Z",
        )
        order_medium = create_confirmed_order(
            customer["id"], site_medium["id"], veh_medium,
            scheduled_window_start="2026-08-06T13:00:00Z",
            scheduled_window_end="2026-08-06T14:00:00Z",
        )
        van_a = create_van(name="VAN-A", load_gallons=96)
        van_b = create_van(name="VAN-B", load_gallons=96)
        tech_a = create_technician(name="Tech A")
        tech_b = create_technician(name="Tech B")
        route_a = create_route("2026-08-05", van_a["id"], tech_a["id"])
        route_b = create_route("2026-08-06", van_b["id"], tech_b["id"])
        stop_small = add_stop_to_route(route_a["id"], order_small["id"])
        stop_medium = add_stop_to_route(route_b["id"], order_medium["id"])
        assert stop_small["planned_end_at"] == "2026-08-05T08:35:00.000Z"
        assert stop_medium["planned_end_at"] == "2026-08-06T08:45:00.000Z"


class TestStartWithoutRequiredInspection:
    def test_start_blocked_until_submitted_report_exists(self, api):
        """PRD §3.5: "The order's non-cancelled stop must be `ARRIVED` (otherwise
        `ERR_INVALID_STATE`), the site must be `ACTIVE` (`ERR_SITE_SUSPENDED`), and
        when `requires_inspection` is true a `SUBMITTED` InspectionReport must already
        exist for the order (`ERR_INSPECTION_REQUIRED`)."

        Design: Corner/validations/start_without_required_inspection
        """
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        order = create_confirmed_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
            requires_inspection=True,
        )
        van = create_van(load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-05", van["id"], tech["id"])
        stop = add_stop_to_route(route["id"], order["id"])
        route_event(route["id"], "PUBLISH")
        stop_event(route["id"], stop["id"], "ARRIVE", tech["id"])
        resp = api.wash_order_event(
            order["id"], {"event_type": "START"}, make_technician_headers(tech["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_REQUIRED)
        assert get_order(order["id"])["status"] == "ASSIGNED"


class TestStopAddToLockedRoute:
    def test_locked_route_rejects_stop_add(self, api):
        """PRD §3.4: "the route must be `DRAFT` or `PUBLISHED`, since a `LOCKED`,
        `COMPLETED`, or `CANCELLED` route rejects the mutation with
        `ERR_ROUTE_LOCKED`"

        Design: Corner/errors/stop_add_to_locked_route
        """
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        order = create_confirmed_order(ctx["customer"]["id"], ctx["site"]["id"],
                                       ctx["vehicle_ids"])
        van = create_van(load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-05", van["id"], tech["id"])
        route_event(route["id"], "PUBLISH")
        route_event(route["id"], "LOCK")
        current = get_route(route["id"])
        resp = api.add_route_stop(
            route["id"],
            {"wash_order_id": order["id"], "expected_route_version": current["version"]},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_LOCKED)
        assert get_order(order["id"])["status"] == "SCHEDULED"
