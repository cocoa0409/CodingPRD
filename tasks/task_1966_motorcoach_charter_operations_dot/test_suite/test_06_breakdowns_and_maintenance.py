"""Breakdown response forks, replacement dispatch cascades, delay compensation,
and the maintenance-record lifecycle."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_customer_headers,
    assert_breakdown_event,
    set_clock, make_vehicle, make_driver, get_vehicle, get_driver,
    get_order, setup_in_progress_order, setup_order_with_breakdown,
)

DISPATCH = TEST_USERS["dispatch_manager_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]


class TestBreakdownForks:
    def test_resolve_in_place_branch(self, api):
        """PRD §3.7: "resolving in place — again with a non-negative
        `delay_minutes` — moves `REPORTED` directly to `RESOLVED_IN_PLACE`". PRD
        §3.7: "at least 60 but under 120 minutes, five percent of the quoted
        `subtotal_cents`".

        90-minute delay on a quote with subtotal 75000 -> compensation
        round(75000 * 0.05) = 3750.

        Design: Difficulty/non_linear_state_machine/breakdown_event_fork_to_replace_or_resolve
        """
        ctx = setup_order_with_breakdown()
        resolved = validate_success(api.resolve_breakdown_in_place(
            ctx["breakdown"]["id"], {"delay_minutes": 90}, DISPATCH))
        assert resolved["status"] == "RESOLVED_IN_PLACE"
        assert resolved["delay_minutes"] == 90
        assert resolved["customer_compensation_cents"] == 3750

    def test_dispatch_en_route_replacement_branch(self, api):
        """PRD §3.7: "Marking the replacement as en route moves `DISPATCHED` →
        `REPLACEMENT_EN_ROUTE`. Completing the replacement ... moves the event
        to `REPLACED`, and hands the order over: the order's
        `assigned_vehicle_id` becomes the replacement vehicle ... the
        replacement vehicle moves to `IN_TRIP`".

        Design: Difficulty/non_linear_state_machine/breakdown_event_fork_to_replace_or_resolve
        """
        ctx = setup_order_with_breakdown()
        replacement = make_vehicle()
        dispatched = validate_success(api.dispatch_breakdown(
            ctx["breakdown"]["id"], {"replacement_vehicle_id": replacement["id"]},
            DISPATCH))
        assert dispatched["status"] == "DISPATCHED"
        en_route = validate_success(api.breakdown_en_route(
            ctx["breakdown"]["id"], DISPATCH))
        assert en_route["status"] == "REPLACEMENT_EN_ROUTE"
        replaced = validate_success(api.complete_replacement(
            ctx["breakdown"]["id"], {"delay_minutes": 90}, DISPATCH))
        assert replaced["status"] == "REPLACED"
        assert replaced["customer_compensation_cents"] == 3750
        order = get_order(ctx["order"]["id"])
        assert order["assigned_vehicle_id"] == replacement["id"]
        assert get_vehicle(replacement["id"])["status"] == "IN_TRIP"


class TestDispatchCascade:
    def test_dispatch_moves_replacement_and_original_vehicles(self, api):
        """PRD §3.7: "A successful dispatch moves the event `REPORTED` →
        `DISPATCHED`, records the replacement identifiers, marks the replacement
        vehicle `ASSIGNED`, puts any named replacement driver
        `ON_DUTY_NOT_DRIVING`, moves the stricken original vehicle to
        `IN_MAINTENANCE`".

        Design: Difficulty/transitive_cascade/breakdown_dispatch_cascade_depth2
        """
        ctx = setup_order_with_breakdown()
        replacement = make_vehicle()
        dispatched = validate_success(api.dispatch_breakdown(
            ctx["breakdown"]["id"], {"replacement_vehicle_id": replacement["id"]},
            DISPATCH))
        assert_breakdown_event(dispatched)
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["replacement_vehicle_id"] == replacement["id"]
        assert get_vehicle(replacement["id"])["status"] == "ASSIGNED"
        assert get_vehicle(ctx["vehicle"]["id"])["status"] == "IN_MAINTENANCE"

    def test_dispatch_schedules_repair_record_for_original_vehicle(self, api):
        """PRD §3.7: dispatch "moves the stricken original vehicle to
        `IN_MAINTENANCE`, and schedules a `REPAIR` maintenance record against
        it."

        Design: Difficulty/transitive_cascade/breakdown_dispatch_cascade_depth2
        """
        ctx = setup_order_with_breakdown()
        replacement = make_vehicle()
        validate_success(api.dispatch_breakdown(
            ctx["breakdown"]["id"], {"replacement_vehicle_id": replacement["id"]},
            DISPATCH))
        data, meta = validate_paginated(
            api.list_maintenance_records(ctx["vehicle"]["id"], FLEET))
        assert meta["total_count"] == 1
        assert data[0]["maintenance_type"] == "REPAIR"
        assert data[0]["vehicle_id"] == ctx["vehicle"]["id"]


class TestBreakdownCompensationInvariant:
    def test_compensation_tier_and_deposit_cap_inequality(self, api):
        """PRD §3.7: "Delay compensation scales with the recorded
        `delay_minutes`: under 60 minutes, nothing; at least 60 but under 120
        minutes, five percent of the quoted `subtotal_cents`" and "each figure
        rounded half-up to integer cents and capped at the order's
        `deposit_paid_cents`."

        90 min on subtotal 75000 -> 3750, which is <= deposit_paid 40594.

        Design: Difficulty/compensating_invariant/breakdown_compensation_conserves_invoice_integrity
        """
        ctx = setup_order_with_breakdown()
        resolved = validate_success(api.resolve_breakdown_in_place(
            ctx["breakdown"]["id"], {"delay_minutes": 90}, DISPATCH))
        assert resolved["status"] == "RESOLVED_IN_PLACE"
        assert resolved["customer_compensation_cents"] == 3750
        order = get_order(ctx["order"]["id"])
        assert 0 <= resolved["customer_compensation_cents"] <= order["deposit_paid_cents"]

    def test_compensation_credits_final_subtotal_at_settlement(self, api):
        """PRD §3.5: "`final_subtotal_cents` is the quoted subtotal plus the
        extra-hours charge plus the fuel surcharge, less any breakdown
        compensation credited under §3.7".

        Quote subtotal 75000; resolve-in-place credit 3750; completion at actuals
        300 mi / 5 h adds fuel round(75000 * 0.03) = 2250: final_subtotal =
        75000 + 0 + 2250 - 3750 = 73500; final_tax = round(73500*0.0825) = 6064;
        final_invoice = 79564; balance = 79564 - 40594 = 38970.

        Design: Difficulty/compensating_invariant/breakdown_compensation_conserves_invoice_integrity
        """
        ctx = setup_order_with_breakdown()
        validate_success(api.resolve_breakdown_in_place(
            ctx["breakdown"]["id"], {"delay_minutes": 90}, DISPATCH))
        completed = validate_success(api.complete_trip(
            ctx["order"]["id"], {"actual_miles": 300, "actual_hours": 5},
            DISPATCH))
        assert completed["final_subtotal_cents"] == 73500
        assert completed["final_tax_cents"] == 6064
        assert completed["final_invoice_cents"] == 79564
        assert completed["balance_due_cents"] == 38970

    def test_compensation_capped_at_deposit_paid(self, api):
        """PRD §3.7: "and 480 minutes or more, thirty-five percent — each figure
        rounded half-up to integer cents and capped at the order's
        `deposit_paid_cents`."

        Trip accepted 45 days ahead -> 10% deposit tier on total 81188 -> 8119
        paid. A 500-minute delay earns round(75000 * 0.35) = 26250 raw, which the
        cap pulls down to the 8119 deposit actually paid.

        Design: Difficulty/compensating_invariant/breakdown_compensation_conserves_invoice_integrity
        """
        ctx = setup_order_with_breakdown(
            quote_overrides={"trip_date": "2026-08-15T08:00:00Z",
                             "return_date": "2026-08-15T16:00:00Z"})
        order = get_order(ctx["order"]["id"])
        assert order["deposit_paid_cents"] == 8119
        resolved = validate_success(api.resolve_breakdown_in_place(
            ctx["breakdown"]["id"], {"delay_minutes": 500}, DISPATCH))
        assert resolved["customer_compensation_cents"] == 8119
        assert (resolved["customer_compensation_cents"]
                == order["deposit_paid_cents"])


class TestBreakdownInvalidTransitions:
    def test_cancel_dispatch_from_reported_returns_invalid_state(self, api):
        """PRD §3.7: "A dispatch may be called off while the event still stands
        in `DISPATCHED`". PRD §2.8: "4. State validity: the target entity is in
        a state from which the requested transition exists per Section 3, else
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/breakdown_cancel_dispatch_from_reported_returns_invalid_state
        """
        ctx = setup_order_with_breakdown()
        res = api.cancel_breakdown_dispatch(ctx["breakdown"]["id"], DISPATCH)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestMaintenanceLifecycle:
    def test_start_completed_record_returns_invalid_state(self, api):
        """PRD §3.8: "Work begins only while the vehicle stands in
        `IN_MAINTENANCE`, moving the record `SCHEDULED` → `IN_PROGRESS`." and
        "`COMPLETED` is terminal for a maintenance record." PRD §2.8: "4. State
        validity: the target entity is in a state from which the requested
        transition exists per Section 3, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/maintenance_record_start_from_completed_returns_invalid_state
        """
        set_clock()
        vehicle = make_vehicle()
        validate_success(api.send_vehicle_to_maintenance(vehicle["id"], FLEET))
        record = validate_success(api.create_maintenance_record(
            vehicle["id"],
            {"maintenance_type": "PREVENTIVE",
             "scheduled_date": "2026-08-01T00:00:00Z",
             "description": "Oil change", "technician": "Tech A",
             "cost_cents": 50000, "odometer_at_service": 10000},
            FLEET), 201)
        validate_success(api.start_maintenance(record["id"], FLEET))
        validate_success(api.complete_maintenance(
            record["id"], {"odometer_at_service": 10000}, FLEET))
        res = api.start_maintenance(record["id"], FLEET)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_decommission_in_trip_vehicle_returns_invalid_state(self, api):
        """PRD §3.2: a fleet manager "may decommission a coach — the request
        carries a `reason` — from either `AVAILABLE` or `IN_MAINTENANCE` into
        `OUT_OF_SERVICE`, from which there is no return." PRD §2.8: "4. State
        validity: the target entity is in a state from which the requested
        transition exists per Section 3, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/vehicle_decommission_from_in_trip_returns_invalid_state
        """
        ctx = setup_in_progress_order(
            quote_overrides={"trip_date": "2026-07-10T08:00:00Z",
                             "return_date": "2026-07-10T14:00:00Z",
                             "estimated_miles": 300, "estimated_hours": 5},
            clock_iso="2026-07-01T00:00:00Z")
        assert get_vehicle(ctx["vehicle"]["id"])["status"] == "IN_TRIP"
        res = api.decommission_vehicle(ctx["vehicle"]["id"],
                                       {"reason": "End of life"}, FLEET)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
