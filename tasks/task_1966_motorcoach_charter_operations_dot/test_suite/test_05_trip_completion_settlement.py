"""Trip completion: extra-hours billing, fuel surcharge boundaries, final
settlement chaining, and the completion cascade across vehicle/driver/customer."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_paginated,
    ApiErrorId, TEST_USERS, make_customer_headers,
    assert_completed_order,
    set_clock, make_customer, get_customer, get_vehicle, get_driver,
    setup_confirmed_order, setup_in_progress_order, setup_completed_order,
)

DISPATCH = TEST_USERS["dispatch_manager_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]


class TestFuelSurchargeBoundary:
    def test_100_actual_miles_no_surcharge(self, api):
        """PRD §3.5: "A fuel surcharge on the quoted `subtotal_cents` scales with
        the actual mileage: nothing when `actual_miles` is 100 or fewer". PRD
        §3.5: "Hours beyond the quote's `estimated_hours` (itself possibly
        revised by itinerary changes), floored at zero, are recorded as
        `extra_hours` and billed into `extra_hours_charge_cents` at one and a
        half times the quote's `hourly_rate_cents`, rounded half-up to integer
        cents."

        100 actual miles on a 100 mi / 4 h quote -> surcharge 0, extra hours 0.

        Design: Difficulty/boundary_precision_check/fuel_surcharge_boundary_100_miles
        """
        ctx = setup_completed_order(actual_miles=100, actual_hours=4)
        order = ctx["order"]
        assert order["status"] == "COMPLETED"
        assert order["fuel_surcharge_cents"] == 0
        assert order["extra_hours"] == 0.0
        assert order["extra_hours_charge_cents"] == 0

    def test_101_actual_miles_three_percent_surcharge(self, api):
        """PRD §3.5: "three percent when it exceeds 100 but not 300 ... each
        figure rounded half-up into `fuel_surcharge_cents`". PRD §3.5:
        "`final_subtotal_cents` is the quoted subtotal plus the extra-hours
        charge plus the fuel surcharge, less any breakdown compensation credited
        under §3.7".

        101 actual miles on the 100 mi / 4 h quote (subtotal 60000): surcharge =
        round(60000 * 0.03) = 1800; final_subtotal = 60000 + 0 + 1800 = 61800.

        Design: Difficulty/boundary_precision_check/fuel_surcharge_boundary_100_miles
        """
        ctx = setup_completed_order(actual_miles=101, actual_hours=4)
        order = ctx["order"]
        assert order["fuel_surcharge_cents"] == 1800
        assert order["final_subtotal_cents"] == 61800


class TestCompletionCascade:
    def test_completion_cascade_across_vehicle_driver_customer(self, api):
        """PRD §3.5: "The vehicle's `odometer_miles` accrues the trip's
        `actual_miles`; if the new reading reaches or exceeds
        `maintenance_due_miles`, the vehicle drops to `IN_MAINTENANCE`" and
        "Every assigned driver — primary and relief alike — moves to `OFF_DUTY`
        with `last_rest_start` stamped at completion" and "On the account,
        `total_completed_trips` increases by one".

        Vehicle created with maintenance_due_miles = 150; the 200-mile trip
        pushes the odometer to 200 >= 150 -> IN_MAINTENANCE.

        Design: Difficulty/transitive_cascade/trip_completion_cascade_depth3
        """
        ctx = setup_completed_order(
            actual_miles=200, actual_hours=4,
            quote_overrides={"estimated_miles": 200, "estimated_hours": 4},
            vehicle_overrides={"maintenance_due_miles": 150})
        assert ctx["order"]["status"] == "COMPLETED"
        vehicle = get_vehicle(ctx["vehicle"]["id"])
        assert vehicle["status"] == "IN_MAINTENANCE"
        assert vehicle["odometer_miles"] == 200
        driver = get_driver(ctx["driver"]["id"])
        assert driver["status"] == "OFF_DUTY"
        customer = get_customer(ctx["customer"]["id"])
        assert customer["total_completed_trips"] == 1

    def test_maintenance_record_auto_scheduled_when_threshold_crossed(self, api):
        """PRD §3.5: "if the new reading reaches or exceeds
        `maintenance_due_miles`, the vehicle drops to `IN_MAINTENANCE` and a
        `PREVENTIVE` maintenance record is automatically scheduled against it".

        Design: Difficulty/transitive_cascade/trip_completion_cascade_depth3
        """
        ctx = setup_completed_order(
            actual_miles=200, actual_hours=4,
            quote_overrides={"estimated_miles": 200, "estimated_hours": 4},
            vehicle_overrides={"maintenance_due_miles": 150})
        data, meta = validate_paginated(
            api.list_maintenance_records(ctx["vehicle"]["id"], FLEET))
        assert meta["total_count"] == 1
        assert data[0]["maintenance_type"] == "PREVENTIVE"
        assert data[0]["vehicle_id"] == ctx["vehicle"]["id"]


class TestCompletionDerivedFields:
    def test_customer_derived_fields_update_on_completion(self, api):
        """PRD §3.1: "`lifetime_revenue_cents` accumulates the money the
        relationship has produced — it grows by the deposit amount received when
        a deposit is paid, and again by the `final_invoice_cents` when a trip
        completes". PRD §3.5: "`total_completed_trips` increases by one".

        100 mi / 4 h quote: total 64950; accepted 216 h before trip -> 50%
        deposit = 32475. Completion at actuals 100/4: final_invoice 64950.
        lifetime_revenue = 32475 + 64950 = 97425.

        Design: Corner/cross_cutting/cascading_trip_completion_updates_customer_derived_fields
        """
        ctx = setup_completed_order(actual_miles=100, actual_hours=4)
        assert ctx["order"]["status"] == "COMPLETED"
        assert ctx["order"]["deposit_paid_cents"] == 32475
        assert ctx["order"]["final_invoice_cents"] == 64950
        customer = ctx["customer"]
        assert customer["total_completed_trips"] == 1
        assert customer["lifetime_revenue_cents"] == 97425
        assert ctx["vehicle"]["status"] == "AVAILABLE"
        assert ctx["driver"]["status"] == "OFF_DUTY"

    def test_settlement_fields_immediate_in_completion_response(self, api):
        """PRD §3.5: "`final_subtotal_cents` is the quoted subtotal plus the
        extra-hours charge plus the fuel surcharge, less any breakdown
        compensation credited under §3.7; `final_tax_cents` is 8.25 percent of
        that final subtotal, rounded half-up, or zero for a tax-exempt customer;
        `final_invoice_cents` is the final subtotal plus the final tax; and
        `balance_due_cents` is the final invoice less the `deposit_paid_cents`
        already collected."

        Actuals 120 mi / 5 h on the 100 mi / 4 h quote (hourly rate 15000):
        extra_hours 1.0 -> charge round(1.0 * 15000 * 1.5) = 22500; fuel 3% of
        60000 = 1800; final_subtotal 84300; tax round(84300*0.0825) = 6955;
        invoice 91255; balance = 91255 - 32475 = 58780 — all in one response.

        Design: Corner/consistency_model/immediate_consistency_trip_completion
        """
        ctx = setup_in_progress_order(
            quote_overrides={"trip_date": "2026-07-10T08:00:00Z",
                             "return_date": "2026-07-10T14:00:00Z",
                             "estimated_miles": 100, "estimated_hours": 4},
            clock_iso="2026-07-01T00:00:00Z")
        completed = validate_success(api.complete_trip(
            ctx["order"]["id"], {"actual_miles": 120, "actual_hours": 5},
            DISPATCH))
        assert_completed_order(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["actual_miles"] == 120
        assert completed["actual_hours"] == 5
        assert completed["extra_hours"] == 1.0
        assert completed["extra_hours_charge_cents"] == 22500
        assert completed["fuel_surcharge_cents"] == 1800
        assert completed["final_subtotal_cents"] == 84300
        assert completed["final_tax_cents"] == 6955
        assert completed["final_invoice_cents"] == 91255
        assert completed["balance_due_cents"] == 58780


class TestItineraryChanges:
    def test_itinerary_change_appends_to_order(self, api):
        """PRD §3.6: "Every change appends an entry — a timestamp and the
        description — to the order's `itinerary_changes`".

        Design: Corner/endpoints/itinerary_change_appends_to_order
        """
        ctx = setup_confirmed_order()
        updated = validate_success(api.record_itinerary_change(
            ctx["order"]["id"], {"description": "Add stop at Waco TX"},
            make_customer_headers(ctx["customer"]["id"])))
        assert len(updated["itinerary_changes"]) == 1
        assert updated["itinerary_changes"][0]["description"] == "Add stop at Waco TX"
