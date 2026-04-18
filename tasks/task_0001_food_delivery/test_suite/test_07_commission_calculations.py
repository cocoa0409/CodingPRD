"""Commission calculations (PRD §3.4, §3.7).

Covers:
- Tiered commission formula at placement: 15% / 18% / 22% across 20 000 / 50 000 caps
- Round half-up after the tier sum (not per-tier)
- At delivery, tiered recomputed when commission_rate_override is null
- At delivery, flat override applied to entire subtotal when override is set
- Diverges from provisional when override changed mid-order
"""

import pytest

from test_helpers import (
    api_client,
    create_active_restaurant,
    get_success_data,
    make_customer_headers,
    make_restaurant_headers,
    place_order,
    restaurant_accept_order,
    run_order_to_delivered,
    setup_customer_restaurant_menu,
    setup_restaurant_with_menu,
    start_preparing,
    validate_success,
)


def _tiered_commission(subtotal: int) -> int:
    """Reference implementation of the PRD §3.4 tiered formula.

    Matches the PRD exactly: sum decimal products first, then round half-up to whole cent.
    """
    tier1 = min(subtotal, 20000)
    tier2 = max(0, min(subtotal, 50000) - 20000)
    tier3 = max(0, subtotal - 50000)
    total = tier1 * 0.15 + tier2 * 0.18 + tier3 * 0.22
    # round half-up: standard Python round() is banker's; mimic half-up explicitly.
    import math
    return int(math.floor(total + 0.5))


class TestProvisionalCommissionTiered:
    def test_single_tier(self, api):
        """PRD §3.4: "the first 20 000 cents of subtotal_cents is billed at 15%".

        Claim: subtotal=10 000 → provisional_commission_cents == 1500.
        """
        restaurant, items = setup_restaurant_with_menu(
            menu_items=[{"price_cents": 10000, "name": "D"}]
        )
        from test_helpers import create_customer, build_order_item, create_order_payload
        customer = create_customer()
        order = place_order(customer, restaurant, items[0], quantity=1, unit_price_cents=10000)
        assert order["subtotal_cents"] == 10000
        assert order["provisional_commission_cents"] == _tiered_commission(10000)
        assert order["provisional_commission_cents"] == 1500

    def test_two_tiers(self, api):
        """PRD §3.4: "the portion of the subtotal strictly between 20 000 and 50 000
        cents is billed at 18%".

        Claim: subtotal=30 000 → commission == 20 000*0.15 + 10 000*0.18 = 3000 + 1800 = 4800.
        """
        restaurant, items = setup_restaurant_with_menu(
            menu_items=[{"price_cents": 30000, "name": "D"}]
        )
        from test_helpers import create_customer
        customer = create_customer()
        order = place_order(customer, restaurant, items[0], quantity=1, unit_price_cents=30000)
        assert order["subtotal_cents"] == 30000
        assert order["provisional_commission_cents"] == 4800
        assert order["provisional_commission_cents"] == _tiered_commission(30000)

    def test_three_tiers(self, api):
        """PRD §3.4: "any portion above 50 000 cents is billed at 22%."

        Claim: subtotal=60 000 → commission == 20 000*0.15 + 30 000*0.18 + 10 000*0.22
              = 3000 + 5400 + 2200 = 10 600.
        """
        restaurant, items = setup_restaurant_with_menu(
            menu_items=[{"price_cents": 60000, "name": "D"}]
        )
        from test_helpers import create_customer
        customer = create_customer()
        order = place_order(customer, restaurant, items[0], quantity=1, unit_price_cents=60000)
        assert order["subtotal_cents"] == 60000
        assert order["provisional_commission_cents"] == 10600

    def test_boundary_at_20000(self, api):
        """PRD §3.4: "The computation proceeds in a fixed evaluation order — first the
        tier-1 amount is determined as the minimum of subtotal_cents and 20 000".

        Claim: subtotal=20 000 → commission == 3000 (all tier 1).
        """
        restaurant, items = setup_restaurant_with_menu(
            menu_items=[{"price_cents": 20000, "name": "D"}]
        )
        from test_helpers import create_customer
        customer = create_customer()
        order = place_order(customer, restaurant, items[0], quantity=1, unit_price_cents=20000)
        assert order["provisional_commission_cents"] == 3000

    def test_rounding_is_half_up_on_total(self, api):
        """PRD §3.4: "Each tier's amount is multiplied by its rate, the three products are
        summed in decimal, and only the final sum is rounded half-up to a whole cent.
        Rounding each tier independently and then summing is forbidden because it produces
        a different answer on boundary subtotals."

        Claim: pick a subtotal whose tier-sum has a fractional .5 and ensure half-up.
        subtotal=25 003 → tier1=20000*0.15=3000, tier2=5003*0.18=900.54, sum=3900.54,
        round half-up to 3901.
        """
        restaurant, items = setup_restaurant_with_menu(
            menu_items=[{"price_cents": 25003, "name": "D"}]
        )
        from test_helpers import create_customer
        customer = create_customer()
        order = place_order(customer, restaurant, items[0], quantity=1, unit_price_cents=25003)
        expected = _tiered_commission(25003)
        assert order["provisional_commission_cents"] == expected
        assert expected == 3901


class TestFinalCommissionTieredBranch:
    def test_null_override_uses_tiered_formula(self, api):
        """PRD §3.7: "If commission_rate_override is null at delivery time, the same
        tiered formula described in §3.4 runs again."

        Claim: restaurant with null override → final_commission_cents equals tiered
        formula on subtotal.
        """
        ctx = run_order_to_delivered(distance_km=2.0, menu_price_cents=10000)
        order = ctx["order"]
        assert order["final_commission_cents"] == _tiered_commission(order["subtotal_cents"])


class TestFinalCommissionFlatOverride:
    def test_override_applied_to_entire_subtotal(self, api):
        """PRD §3.7: "If, at the moment of delivery, the owning restaurant's
        commission_rate_override is a non-null decimal, commission is computed as a flat
        rate: the subtotal multiplied by that override rate, rounded half-up to a whole
        cent. The override applies to the entire subtotal, not just the portion above any
        tier threshold."

        Claim: override=0.12, subtotal=30 000 → final_commission_cents == 3600 and
        provisional_commission_cents (computed at placement when override was null) == 4800.

        # difficulty: dual_variant_calc/commission_tiered_vs_flat_override
        """
        # Create ACTIVE restaurant with null override; place order; admin PATCHes override
        # to 0.12 before delivery.
        from test_helpers import (
            api_client as _api,
            create_customer,
            create_listed_menu_item,
            dispatch_order_as_admin,
            advance_clock_seconds,
            accept_assignment_as_rider,
            pickup_assignment_as_rider,
            deliver_assignment_as_rider,
            mark_ready,
            create_available_rider,
        )
        from test_helpers import take_other_riders_offline
        restaurant = create_active_restaurant()
        menu_item = create_listed_menu_item(restaurant, price_cents=30000)
        customer = create_customer(distance_km=2.0)
        rider = create_available_rider()
        # Narrow the AVAILABLE candidate pool so dispatch targets THIS rider — PRD §3.6
        # does not prescribe a tie-breaker among AVAILABLE riders and prior tests may
        # have left others in AVAILABLE.
        take_other_riders_offline(keep_rider_id=rider["id"])

        order = place_order(customer, restaurant, menu_item, quantity=1)
        assert order["subtotal_cents"] == 30000
        assert order["provisional_commission_cents"] == 4800

        restaurant_accept_order(order, restaurant)
        # Dispatch + accept before start-preparing per PRD §3.6 (accept legal in
        # RESTAURANT_ACCEPTED state and avoids start-preparing's implicit dispatch
        # clashing with an explicit handle).
        assignment = dispatch_order_as_admin(order)
        assignment = accept_assignment_as_rider(assignment, rider)
        start_preparing(order, restaurant)
        mark_ready(order, restaurant)
        assignment = pickup_assignment_as_rider(assignment, rider)

        # Admin updates override BEFORE delivery.
        from test_helpers import TEST_USERS as _TU
        _api.patch_restaurant(
            restaurant["id"], {"commission_rate_override": 0.12}, _TU["admin_headers"]
        )

        deliver_assignment_as_rider(assignment, rider)
        updated_order = get_success_data(_api.get_order(order["id"], _TU["admin_headers"]))
        assert updated_order["final_commission_cents"] == 3600, (
            "flat rate 30000 * 0.12 rounded half-up = 3600"
        )
        assert updated_order["provisional_commission_cents"] == 4800
        assert updated_order["final_commission_cents"] != updated_order["provisional_commission_cents"]

    def test_settlement_uses_final_commission(self, api):
        """PRD §3.7: "the owning restaurant's pending_settlement_cents is incremented by
        subtotal_cents minus final_commission_cents — the restaurant's slice of the order."

        Claim: after a flat-override delivery (subtotal=30000, override=0.12, final=3600),
        restaurant.pending_settlement_cents increases by exactly 26 400.

        # difficulty: dual_variant_calc/commission_tiered_vs_flat_override
        """
        from test_helpers import (
            api_client as _api,
            create_customer,
            create_listed_menu_item,
            dispatch_order_as_admin,
            accept_assignment_as_rider,
            pickup_assignment_as_rider,
            deliver_assignment_as_rider,
            mark_ready,
            create_available_rider,
            TEST_USERS as _TU,
        )
        from test_helpers import take_other_riders_offline
        restaurant = create_active_restaurant()
        menu_item = create_listed_menu_item(restaurant, price_cents=30000)
        customer = create_customer(distance_km=2.0)
        rider = create_available_rider()
        take_other_riders_offline(keep_rider_id=rider["id"])
        before = get_success_data(
            _api.get_restaurant(restaurant["id"], _TU["admin_headers"])
        )
        baseline = before["pending_settlement_cents"]

        order = place_order(customer, restaurant, menu_item, quantity=1)
        restaurant_accept_order(order, restaurant)
        # Dispatch + accept before start-preparing.
        assignment = dispatch_order_as_admin(order)
        assignment = accept_assignment_as_rider(assignment, rider)
        start_preparing(order, restaurant)
        mark_ready(order, restaurant)
        assignment = pickup_assignment_as_rider(assignment, rider)

        _api.patch_restaurant(
            restaurant["id"], {"commission_rate_override": 0.12}, _TU["admin_headers"]
        )
        deliver_assignment_as_rider(assignment, rider)

        after = get_success_data(
            _api.get_restaurant(restaurant["id"], _TU["admin_headers"])
        )
        assert after["pending_settlement_cents"] == baseline + (30000 - 3600)
