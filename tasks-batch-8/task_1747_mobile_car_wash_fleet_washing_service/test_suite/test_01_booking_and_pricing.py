"""Booking and pricing: booking quotes, discount tiers, reclaim surcharge,
quote-vs-completion dual variants (PRD §3.3, §3.5)."""
from test_helpers import (
    TEST_USERS, add_stop_to_route, confirm_order, create_customer,
    create_route, create_site, create_technician, create_van, create_vehicles,
    create_wash_order, get_order, make_technician_headers, order_event,
    request_rewash, route_event, setup_completed_order, setup_customer_site_vehicles,
    stop_event, validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestWashQuoteBookingVsCompletion:
    def test_booking_quote_prices_booked_set(self, api):
        """PRD §3.3: "At booking, the order is priced into `quote_cents`."
        PRD §3.3: "Then a volume discount percentage is chosen by the booked count:
        fifteen percent when the count is at least twenty, ten percent when at least
        ten, five percent when at least five, and no discount below five; the discount
        amount is the subtotal multiplied by that percentage, rounded half-up to
        integer cents."

        Design: Difficulty/dual_variant_calc/wash_quote_booking_vs_completion
        """
        ctx = setup_customer_site_vehicles(num_vehicles=10, vehicle_class="SEDAN")
        order = create_wash_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
            scheduled_window_start="2026-08-05T13:00:00Z",
            scheduled_window_end="2026-08-05T15:00:00Z",
        )
        # 10 x 3500 = 35000 subtotal; 10% tier at exactly 10 -> -3500
        assert order["quote_cents"] == 31500, (
            f"booked-set quote must be 31500, got {order['quote_cents']}"
        )
        assert order["vehicle_count"] == 10
        assert order["status"] == "DRAFT"

    def test_completion_final_prices_washed_set(self, api):
        """PRD §3.5: "`final_cents` is computed with the same pricing routine as §3.3
        but over the washed subset, so the washed count — not the booked count — drives
        the discount tier, and identical order data yields a different amount whenever
        the washed count crosses a tier boundary or drops a vehicle"

        Design: Difficulty/dual_variant_calc/wash_quote_booking_vs_completion
        """
        ctx2 = setup_customer_site_vehicles(num_vehicles=10, vehicle_class="SEDAN")
        order = create_wash_order(
            ctx2["customer"]["id"], ctx2["site"]["id"], ctx2["vehicle_ids"],
            scheduled_window_start="2026-08-05T13:00:00Z",
            scheduled_window_end="2026-08-05T15:00:00Z",
        )
        order = confirm_order(order["id"])
        assert order["quote_cents"] == 31500
        van = create_van(reclaim_system="BASIC", tank_capacity_gal=100, load_gallons=96)
        tech = create_technician(certified=True)
        route = create_route("2026-08-05", van["id"], tech["id"])
        stop = add_stop_to_route(route["id"], order["id"])
        route_event(route["id"], "PUBLISH")
        stop_event(route["id"], stop["id"], "ARRIVE", tech["id"])
        order_event(order["id"], "START", make_technician_headers(tech["id"]))
        washed = ctx2["vehicle_ids"][:9]
        completed = order_event(
            order["id"], "COMPLETE", make_technician_headers(tech["id"]),
            vehicles_washed_ids=washed,
        )
        # washed set: 9 x 3500 = 31500 subtotal; 5% tier -> -1575
        assert completed["final_cents"] == 29925, (
            f"washed-set final must be 29925, got {completed['final_cents']}"
        )
        assert completed["final_cents"] != completed["quote_cents"]
        assert completed["status"] == "COMPLETED"
        assert completed["billing_status"] == "UNBILLED"


class TestWashQuoteTieredMultiInput:
    def test_ten_sedans_plain_vs_reclaim_site(self, api):
        """PRD §3.3: "Finally, only when the site's `water_reclaim_required` is true,
        a reclamation surcharge of eight percent of the after-discount amount — again
        rounded half-up to integer cents — is added; otherwise the surcharge is zero."

        Design: Difficulty/combinatorial_formula/wash_quote_tiered_multi_input
        """
        customer = create_customer()
        plain = create_site(customer["id"], name="PLAIN")
        reclaim = create_site(
            customer["id"], name="RECLAIM", lot_size_sqft=60000,
            containment_type="BERMS", water_reclaim_required=True,
            max_discharge_gal=100,
        )
        vehicle_ids = create_vehicles(customer["id"], plain["id"], 10, "SEDAN")
        order_plain = create_wash_order(
            customer["id"], plain["id"], vehicle_ids,
            scheduled_window_start="2026-08-06T13:00:00Z",
            scheduled_window_end="2026-08-06T15:00:00Z",
        )
        order_reclaim = create_wash_order(
            customer["id"], reclaim["id"], vehicle_ids,
            scheduled_window_start="2026-08-07T13:00:00Z",
            scheduled_window_end="2026-08-07T15:00:00Z",
        )
        # plain: 35000 - 3500 tier discount, no surcharge
        assert order_plain["quote_cents"] == 31500
        # reclaim: 31500 + round_half_up(31500 * 0.08) = 31500 + 2520
        assert order_reclaim["quote_cents"] == 34020
        # surcharge applies to the post-discount amount, not the subtotal
        assert order_reclaim["quote_cents"] - order_plain["quote_cents"] == 2520

    def test_four_sedans_reclaim_site_surcharge_without_discount(self, api):
        """PRD §3.3: "First comes the subtotal, the sum of the per-vehicle rates over
        the booked vehicles. Then a volume discount percentage is chosen by the booked
        count: fifteen percent when the count is at least twenty, ten percent when at
        least ten, five percent when at least five, and no discount below five"

        Design: Difficulty/combinatorial_formula/wash_quote_tiered_multi_input
        """
        customer = create_customer()
        reclaim = create_site(
            customer["id"], name="RECLAIM", lot_size_sqft=60000,
            containment_type="BERMS", water_reclaim_required=True,
            max_discharge_gal=100,
        )
        vehicle_ids = create_vehicles(customer["id"], reclaim["id"], 4, "SEDAN")
        order = create_wash_order(
            customer["id"], reclaim["id"], vehicle_ids,
            scheduled_window_start="2026-08-08T13:00:00Z",
            scheduled_window_end="2026-08-08T15:00:00Z",
        )
        # 4 x 3500 = 14000, no tier (below five), + round_half_up(14000 * 0.08) = 1120
        assert order["quote_cents"] == 15120


class TestVolumeDiscountTierAtExactlyTenVehicles:
    def test_ten_vehicles_gets_ten_percent_tier(self, api):
        """PRD §3.3: "Then a volume discount percentage is chosen by the booked count:
        fifteen percent when the count is at least twenty, ten percent when at least
        ten, five percent when at least five, and no discount below five"

        Design: Difficulty/boundary_precision_check/volume_discount_tier_at_exactly_10_vehicles
        """
        ctx = setup_customer_site_vehicles(num_vehicles=10, vehicle_class="SEDAN")
        order = create_wash_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
            scheduled_window_start="2026-08-06T13:00:00Z",
            scheduled_window_end="2026-08-06T15:00:00Z",
        )
        # 10% tier applies at exactly 10: 35000 - 3500
        assert order["quote_cents"] == 31500

    def test_nine_vehicles_falls_to_five_percent_tier(self, api):
        """PRD §3.3: "Then a volume discount percentage is chosen by the booked count:
        fifteen percent when the count is at least twenty, ten percent when at least
        ten, five percent when at least five, and no discount below five"

        Design: Difficulty/boundary_precision_check/volume_discount_tier_at_exactly_10_vehicles
        """
        ctx = setup_customer_site_vehicles(num_vehicles=10, vehicle_class="SEDAN")
        order = create_wash_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"][:9],
            scheduled_window_start="2026-08-07T13:00:00Z",
            scheduled_window_end="2026-08-07T15:00:00Z",
        )
        # 5% tier at 9: 31500 - 1575
        assert order["quote_cents"] == 29925


class TestWashOrderInitialStateDraft:
    def test_created_order_is_draft_unbilled_with_quote(self, api):
        """PRD §3.3: "A new order is `DRAFT` with `billing_status` `UNBILLED`;
        `vehicle_count` is the length of `vehicle_ids`; `final_cents` stays null
        until completion; `rewash_of_id` is null and `is_rewash` is false."

        Design: Corner/state_machines/wash_order_initial_state_draft
        """
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        order = create_wash_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
            scheduled_window_start="2026-08-06T13:00:00Z",
            scheduled_window_end="2026-08-06T14:00:00Z",
        )
        assert order["status"] == "DRAFT"
        assert order["billing_status"] == "UNBILLED"
        assert order["quote_cents"] == 3500
        assert order["is_rewash"] is False
        assert order.get("rewash_of_id") is None
        assert order.get("final_cents") is None


class TestRewashOrderPricingZeroWaived:
    def test_rewash_prices_zero_and_waived(self, api):
        """PRD §3.3: "Rewash orders always price zero regardless of this routine."
        PRD §3.8: "`billing_status` is `WAIVED`; `quote_cents` is 0; and the status is
        `SCHEDULED` with a window of the next day — the logical clock date plus one
        day — from 08:00:00 to 10:00:00 UTC."

        Design: Corner/calculations/rewash_order_pricing_zero_waived
        """
        ctx = setup_completed_order(
            num_vehicles=2, vehicle_class="SEDAN", clock_pin="2026-08-05T10:00:00Z",
            site_overrides={
                "name": "RW", "lot_size_sqft": 60000, "containment_type": "BERMS",
                "water_reclaim_required": True, "max_discharge_gal": 1000,
            },
        )
        # original: 2 x 3500 = 7000, no tier, + round_half_up(7000 x 0.08) = 560
        assert ctx["order"]["quote_cents"] == 7560
        rewash = request_rewash(ctx["order"]["id"], ctx["customer"]["id"])
        assert rewash["quote_cents"] == 0
        assert rewash["billing_status"] == "WAIVED"
        assert rewash["is_rewash"] is True
        assert rewash["rewash_of_id"] == ctx["order"]["id"]
        assert rewash["scheduled_window_start"] == "2026-08-06T08:00:00.000Z"
        assert rewash["scheduled_window_end"] == "2026-08-06T10:00:00.000Z"


class TestImmediateConsistencyQuoteVisibleInCreateResponse:
    def test_create_response_carries_computed_quote(self, api):
        """PRD §3.3: "At booking, the order is priced into `quote_cents`."
        PRD §3.3: "Finally, only when the site's `water_reclaim_required` is true, a
        reclamation surcharge of eight percent of the after-discount amount — again
        rounded half-up to integer cents — is added; otherwise the surcharge is zero."

        Design: Corner/consistency_model/immediate_consistency_quote_visible_in_create_response
        """
        customer = create_customer()
        site = create_site(
            customer["id"], name="Y1S", lot_size_sqft=60000,
            containment_type="BERMS", water_reclaim_required=True,
            max_discharge_gal=1000,
        )
        vehicle_ids = create_vehicles(customer["id"], site["id"], 1, "SEDAN")
        resp = api.create_wash_order(
            {
                "customer_id": customer["id"],
                "site_id": site["id"],
                "vehicle_ids": vehicle_ids,
                "scheduled_window_start": "2026-08-06T13:00:00Z",
                "scheduled_window_end": "2026-08-06T14:00:00Z",
            },
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        # 3500 + round_half_up(3500 x 0.08) = 3500 + 280, visible in the response itself
        assert data["quote_cents"] == 3780
        assert data["status"] == "DRAFT"
