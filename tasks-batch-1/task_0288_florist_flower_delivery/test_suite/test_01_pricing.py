"""Pricing: quote estimate, final total, surge, discounts, refunds.

Translates queue-A Difficulty rules dual_variant_calc & combinatorial_formula,
and queue-B Corner calculations instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    make_customer_headers, make_florist_headers,
    set_clock, create_zone, create_arrangement, create_holiday_window,
    create_customer, create_florist, create_draft_order, quote_order,
    mark_authorized, book_order, get_order_wire_fulfillment,
    accept_wire_fulfillment, set_loyalty_tier, create_schedule, emit_schedule,
    get_emitted_order, setup_accepted_order, setup_delivered_order,
    file_claim, approve_claim, TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_estimate_excludes_wire_and_subs_final_includes_them(api):
    """PRD §3.5: "its divergence from `estimated_total_cents` is exactly the wire
    surcharge plus the accepted substitution deltas — and that divergence is
    precisely why the captured amount may differ from the authorized estimate."
    PRD §3.2: "the florist's wire surcharge is deliberately not part of the
    estimate, because no florist has been chosen yet."

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_diverge_on_wire_and_subs
    """
    set_clock("2026-02-10T08:00:00Z")
    zone = create_zone(zone_code="Z1", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="A-PREM", display_name="Lux Roses", base_price_cents=10000,
                             premium_tier="PREMIUM", substitution_policy="FLORIST_CHOICE",
                             substitution_cap_pct=0.15)
    create_holiday_window(name="Valentines", start_date="2026-02-14", end_date="2026-02-14",
                          surge_multiplier=1.5, applies_to_standard=False, surge_cutoff_hour_utc=20)
    cust = create_customer(email="g@x.com", full_name="Gold C")
    set_loyalty_tier(cust["id"], "GOLD")
    flor = create_florist(zone["id"], shop_name="Shop A", daily_capacity=5,
                          quality_rating=4.5, wire_surcharge_cents=500)
    order = create_draft_order(cust, arr, zone, occasion="ROMANCE", card_message="Happy V-Day",
                               delivery_date="2026-02-14", window_start_minute=540,
                               window_end_minute=720)
    order = quote_order(order, cust)
    assert order["estimated_total_cents"] == 14300, order["estimated_total_cents"]

    order = mark_authorized(order["id"])
    order = book_order(order, cust, order["version"])
    wf = get_order_wire_fulfillment(order)
    accept_wire_fulfillment(wf, flor)
    validate_success(api.create_substitution(
        {"order_id": order["id"], "florist_id": flor["id"], "removed_stem": "carnation",
         "added_stem": "peony", "price_delta_cents": 1200},
        make_florist_headers(flor["id"])), 201)

    dispatched = validate_success(api.dispatch_order(order["id"], make_florist_headers(flor["id"])), 200)
    assert dispatched["final_total_cents"] == 16000, dispatched["final_total_cents"]
    assert dispatched["estimated_total_cents"] == 14300
    assert dispatched["final_total_cents"] != dispatched["estimated_total_cents"]


def test_refund_amount_and_loyalty_tier_are_distinct_subjects(api):
    """PRD §3.7: "the captured `final_total_cents` is multiplied by the reason's
    fraction and rounded half-up to a whole cent."
    PRD §3.5: "A customer with exactly 5 delivered orders is `SILVER`".

    Design: Difficulty/dual_variant_calc/claim_refund_vs_loyalty_promotion_distinct_subjects
    """
    ctx, order, _wf = setup_delivered_order(
        "2026-03-01T08:00:00Z",
        zone_overrides={"zone_code": "Z2", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A-STD", "display_name": "Daisy Bunch",
                               "base_price_cents": 5000, "premium_tier": "STANDARD",
                               "substitution_policy": "NONE"},
        order_overrides={"delivery_date": "2026-03-05", "window_start_minute": 540,
                         "window_end_minute": 720})
    # final_total_cents = base 5000 + delivery 800 = 5800 (STANDARD, no surge/subs/wire)
    claim = file_claim(order, ctx["customer"], "DAMAGED", "REFUND")
    approved = approve_claim(claim)
    assert approved["refund_cents"] == 4350, approved["refund_cents"]

    cust = validate_success(api.get_customer(ctx["customer"]["id"], DISPATCHER), 200)
    assert cust["loyalty_tier"] == "STANDARD"
    assert cust["lifetime_delivered_count"] == 1


def test_estimate_pinned_eval_order_surge_then_discount_then_delivery(api):
    """PRD §3.2: "the surged subtotal is the base price multiplied by the window's
    `surge_multiplier`, rounded half-up to a whole cent".
    PRD §3.2: "the zone's `base_delivery_fee_cents` is added after discounts and is
    itself neither surged nor discounted."

    Design: Difficulty/combinatorial_formula/estimate_pinned_eval_order_surge_then_discount_then_delivery
    """
    set_clock("2026-02-10T08:00:00Z")
    zone = create_zone(zone_code="Z3", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="A-P2", display_name="Lux2", base_price_cents=10000,
                             premium_tier="PREMIUM", substitution_policy="SAME_VALUE")
    create_holiday_window(name="Vday2", start_date="2026-02-14", end_date="2026-02-14",
                          surge_multiplier=1.5, applies_to_standard=False, surge_cutoff_hour_utc=20)
    cust = create_customer(email="g2@x.com", full_name="Gold2")
    # Dispatcher drafts on behalf of the customer.
    order = validate_success(api.create_order(
        {"customer_id": cust["id"], "arrangement_id": arr["id"], "zone_id": zone["id"],
         "delivery_date": "2026-02-14", "window_start_minute": 540, "window_end_minute": 720},
        DISPATCHER), 201)
    quoted = validate_success(api.quote_order(order["id"], DISPATCHER), 200)
    # base 10000 * 1.5 = 15000 (STANDARD customer, no discount) + delivery 800 = 15800
    assert quoted["estimated_total_cents"] == 15800, quoted["estimated_total_cents"]
    assert quoted["is_same_day"] is False


def test_discount_stacking_additive_then_clamped(api):
    """PRD §3.2: "The loyalty and recurring fractions are summed, then the combined
    fraction is capped at 0.30."
    PRD §3.2: "The discounted subtotal is the surged subtotal multiplied by one
    minus the combined discount fraction, rounded half-up to a whole cent."

    Design: Difficulty/combinatorial_formula/discount_stacking_additive_then_clamped_min_max
    """
    set_clock("2026-04-01T08:00:00Z")
    zone = create_zone(zone_code="Z4", base_delivery_fee_cents=600,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="A-R", display_name="Recur Mix", base_price_cents=8000,
                             premium_tier="STANDARD", substitution_policy="SAME_VALUE")
    cust = create_customer(email="gr@x.com", full_name="GoldRecur")
    set_loyalty_tier(cust["id"], "GOLD")
    sched = create_schedule(cust, arr, zone, cadence="MONTHLY", next_delivery_date="2026-04-10",
                            window_start_minute=540, window_end_minute=720,
                            occurrences_remaining=3, recurring_discount_pct=0.25)
    emit_schedule(sched)
    emitted = get_emitted_order(sched)
    quoted = validate_success(api.quote_order(emitted["id"], DISPATCHER), 200)
    # GOLD 0.10 + recurring 0.25 = 0.35 clamp 0.30; 8000*0.70=5600 + delivery 600 = 6200
    assert quoted["estimated_total_cents"] == 6200, quoted["estimated_total_cents"]


def test_standard_arrangement_does_not_surge_when_window_excludes_standard(api):
    """PRD §3.2: "Surge applies when such a window exists and either the
    arrangement's `premium_tier` is `PREMIUM` or the window's `applies_to_standard`
    is true."
    PRD §3.2: "when surge does not apply, the surged subtotal is simply the base
    price."

    Design: Corner/calculations/standard_arrangement_does_not_surge_when_window_excludes_standard
    """
    set_clock("2027-02-01T08:00:00Z")
    zone = create_zone(zone_code="ZK3", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="CK3", display_name="CK3", base_price_cents=5000,
                             premium_tier="STANDARD")
    create_holiday_window(name="VK3", start_date="2027-02-14", end_date="2027-02-14",
                          surge_multiplier=1.5, applies_to_standard=False, surge_cutoff_hour_utc=20)
    cust = create_customer(email="ns@x.com", full_name="NS C")
    order = create_draft_order(cust, arr, zone, delivery_date="2027-02-14",
                               window_start_minute=540, window_end_minute=720)
    quoted = quote_order(order, cust)
    # No surge for STANDARD when applies_to_standard=false: 5000 + delivery 800 = 5800
    assert quoted["estimated_total_cents"] == 5800, quoted["estimated_total_cents"]


def test_selector_picks_highest_rating_florist(api):
    """PRD §3.4: "Candidates are ranked by `quality_rating` from highest to lowest;
    ties on rating are broken by `wire_surcharge_cents` from lowest to highest
    (cheaper to the customer wins); any remaining tie is broken by earliest
    `created_at`. The resource `id` is never a decision input."

    Design: Corner/calculations/selector_picks_highest_rating_then_cheapest
    """
    set_clock("2027-03-10T08:00:00Z")
    zone = create_zone(zone_code="ZK5", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="CK5", display_name="CK5", base_price_cents=5000)
    cust = create_customer(email="sel@x.com", full_name="Sel C")
    low = create_florist(zone["id"], shop_name="LowRate", daily_capacity=5,
                         quality_rating=4.2, wire_surcharge_cents=0)
    high = create_florist(zone["id"], shop_name="HighRate", daily_capacity=5,
                          quality_rating=4.8, wire_surcharge_cents=0)
    order = create_draft_order(cust, arr, zone, delivery_date="2027-03-15",
                               window_start_minute=540, window_end_minute=720)
    order = quote_order(order, cust)
    order = mark_authorized(order["id"])
    order = book_order(order, cust, order["version"])
    wf = get_order_wire_fulfillment(order)
    assert wf["florist_id"] == high["id"], (
        f"selector must pick the 4.8-rated florist {high['id']}, got {wf['florist_id']}")
    assert wf["florist_id"] != low["id"]
