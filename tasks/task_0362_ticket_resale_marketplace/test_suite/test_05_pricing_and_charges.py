"""Pricing engine and buyer-charge calculations.

Estimate-vs-final divergence, loyalty goodwill credit, dynamic scarcity pricing
with floor/cap ordering, and per-line fee flooring (PRD §3.3, §3.4, §3.9).
"""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    ApiErrorId,
    TEST_USERS, make_seller_headers, make_buyer_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
TRUST = TEST_USERS["trust_safety_headers"]


# ==========================================================================
# dual_variant_calc
# ==========================================================================
def test_buyer_charge_estimate_vs_final_diverge_on_wallet_change(api):
    """PRD §3.4: "If the wallet shrank between reservation and charge, the final
    total can exceed the estimate; the amount actually charged is
    `final_total_cents`, not `estimated_total_cents`."
    PRD §3.4: "the applied credit is recomputed against the buyer's
    `wallet_credit_cents` as of charge time."

    Design: Difficulty/dual_variant_calc/buyer_charge_estimate_vs_final_diverge_on_wallet_change
    """
    # Buyer earns a genuine 22400 credit from a qty1 CHARGED order on a cancelled event.
    earned = fx.setup_credit_earning_order(quantity=1, seat_count=1)
    buyer_id = earned["buyer_id"]
    seller_id = earned["seller_id"]
    venue_id = earned["venue_id"]
    section_id = earned["section_id"]
    credit = earned["credit"]
    assert credit["amount_cents"] == 22400

    # Fresh event2 with a FIXED listing (2 seats) for the measured order.
    event2 = fx.create_event(venue_id, doors_open_at="2026-09-02T19:00:00.000Z", title="Show2")
    event2 = fx.open_sales(event2["id"])
    listing2, _ = fx.create_active_listing(
        event2["id"], seller_id, section_id, seat_count=2, barcode_prefix="E2",
    )

    # Reserve qty2 applying the full 22400 credit (estimate reflects it).
    order = fx.reserve_order(listing2["id"], buyer_id, 2, listing2["version"],
                             applied_credit_cents=22400)
    assert order["estimated_total_cents"] == 22400, \
        f"estimate should reflect 22400 credit, got {order['estimated_total_cents']}"

    # Revoke the credit before charge → wallet shrinks to 0.
    get_success_data(api.revoke_credit(credit["id"], TRUST))

    charged = validate_success(api.charge_order(order["id"], make_buyer_headers(buyer_id)))
    assert charged["final_total_cents"] == 44800, \
        f"final recomputed against 0 credit should be 44800, got {charged['final_total_cents']}"
    assert charged["final_total_cents"] - order["estimated_total_cents"] == 22400
    assert charged["payment_status"] == "CHARGED"


def test_event_credit_goodwill_bonus_vs_face_diverge_on_loyalty(api):
    """PRD §3.9: "a buyer whose `lifetime_orders_count` is at least the loyalty
    threshold of 3 receives a credit equal to the floor of the base times the
    goodwill bonus multiplier of 1.10 — a 110% credit — and the credit's
    `bonus_applied` flag is true; a buyer below that threshold receives a credit
    equal to the base, a 100% face credit, with `bonus_applied` false."

    Design: Difficulty/dual_variant_calc/event_credit_goodwill_bonus_vs_face_diverge_on_loyalty
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=10)
    venue_id, section_id, event_id, seller_id = (
        base["venue_id"], base["section_id"], base["event_id"], base["seller_id"])
    loyal = fx.create_buyer("Loyal")
    fresh = fx.create_buyer("Fresh")
    listing, _ = fx.create_active_listing(
        event_id, seller_id, section_id, seat_count=10, barcode_prefix="LOY",
    )

    # Loyal buyer reaches lifetime_orders_count == 3 via three qty1 charged orders.
    for _ in range(3):
        lv = fx.get_listing_version(listing["id"], loyal["id"])
        fx.reserve_and_charge(listing["id"], loyal["id"], 1, lv)

    # Loyal buyer's measured qty2 order (gross 40000 → final 44800).
    lv = fx.get_listing_version(listing["id"], loyal["id"])
    loyal_order = fx.reserve_and_charge(listing["id"], loyal["id"], 2, lv)
    assert loyal_order["final_total_cents"] == 44800

    # Fresh buyer's measured qty2 order (lifetime 0 before this).
    lv = fx.get_listing_version(listing["id"], fresh["id"])
    fresh_order = fx.reserve_and_charge(listing["id"], fresh["id"], 2, lv)
    assert fresh_order["final_total_cents"] == 44800

    get_success_data(api.cancel_event(event_id, ADMIN))

    loyal_credit = fx.get_credit_for_source_order(loyal_order["id"])
    fresh_credit = fx.get_credit_for_source_order(fresh_order["id"])

    assert loyal_credit["amount_cents"] == 49280, \
        f"loyal goodwill credit floor(44800*1.10)=49280, got {loyal_credit['amount_cents']}"
    assert loyal_credit["bonus_applied"] is True
    assert fresh_credit["amount_cents"] == 44800, \
        f"non-loyal face credit 44800, got {fresh_credit['amount_cents']}"
    assert fresh_credit["bonus_applied"] is False


# ==========================================================================
# combinatorial_formula
# ==========================================================================
def test_dynamic_price_scarcity_floor_cap_ordering(api):
    """PRD §3.3: "form a demand multiplier of 1.0 plus 0.50 times that sold ratio,
    so the multiplier ranges from 1.00 at an empty listing up to 1.50 at a fully
    taken one; multiply the `ask_price_cents` by that demand multiplier and take
    the floor; then take whichever is larger, that floored figure or the
    `dynamic_floor_cents`."
    PRD §3.3: "For a `DYNAMIC` listing the `effective_price_cents` is refreshed
    whenever the listing is read, since the sold ratio drifts as seats move."

    Design: Difficulty/combinatorial_formula/dynamic_price_scarcity_floor_cap_ordering_mode_a
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=4)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=4, pricing_mode="DYNAMIC", ask_price_cents=20000,
        dynamic_floor_cents=12000, barcode_prefix="DYN",
    )
    # Sell 2 of 4 seats → sold_ratio 0.5.
    order = fx.reserve_order(listing["id"], base["buyer_id"], 2, listing["version"])
    fx.charge_order(order["id"], base["buyer_id"])

    refreshed = validate_success(
        api.get_listing(listing["id"], make_buyer_headers(base["buyer_id"]))
    )
    # demand_mult = 1.0 + 0.5*0.5 = 1.25; raw = floor(20000*1.25)=25000; cap=30000 → 25000.
    assert refreshed["available_seat_count"] == 2
    assert refreshed["effective_price_cents"] == 25000, \
        f"min(max(12000, floor(20000*1.25)), 30000)=25000, got {refreshed['effective_price_cents']}"


def test_buyer_charge_per_line_fee_floor_then_sum(api):
    """PRD §3.4: "the base is `quantity` times `locked_unit_price_cents`; the
    `buyer_fee_cents` is the floor of that base times the buyer fee rate of 0.12;
    the gross is the base plus the `buyer_fee_cents`."

    Design: Difficulty/combinatorial_formula/buyer_charge_per_line_fee_floor_then_sum_ordering_mode_b
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=2)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=2, ask_price_cents=20000, barcode_prefix="FEE",
    )
    order = fx.reserve_order(listing["id"], base["buyer_id"], 2, listing["version"])
    charged = validate_success(api.charge_order(order["id"], make_buyer_headers(base["buyer_id"])))
    # base=40000; fee=floor(40000*0.12)=4800; final=44800.
    assert charged["buyer_fee_cents"] == 4800, \
        f"fee floor(40000*0.12)=4800, got {charged['buyer_fee_cents']}"
    assert charged["final_total_cents"] == 44800


# ==========================================================================
# Companion tests (second test per Difficulty instance)
# ==========================================================================
def test_buyer_charge_estimate_locked_at_reservation_qty2(api):
    """PRD §3.4: "the base is `quantity` times `locked_unit_price_cents`; the
    `buyer_fee_cents` is the floor of that base times the buyer fee rate of 0.12;
    the gross is the base plus the `buyer_fee_cents`; and the applied credit is
    the smallest of the elected `applied_credit_cents`, that gross, and the
    buyer's `wallet_credit_cents` as of reservation time, with the estimated
    total being the gross minus that applied credit."

    Design: Difficulty/dual_variant_calc/buyer_charge_estimate_vs_final_diverge_on_wallet_change
    """
    # No credit at all → estimate equals gross with no divergence to final.
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=2)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=2, ask_price_cents=20000, barcode_prefix="EST",
    )
    order = fx.reserve_order(listing["id"], base["buyer_id"], 2, listing["version"])
    # base 40000, fee 4800, gross 44800, no credit → estimate 44800.
    assert order["estimated_total_cents"] == 44800
    assert order["buyer_fee_cents"] == 4800
    charged = validate_success(api.charge_order(order["id"], make_buyer_headers(base["buyer_id"])))
    assert charged["final_total_cents"] == 44800, "no wallet change → final equals estimate"


def test_event_credit_face_only_when_not_loyal(api):
    """PRD §3.9: "a buyer below that threshold receives a credit equal to the base,
    a 100% face credit, with `bonus_applied` false."

    Design: Difficulty/dual_variant_calc/event_credit_goodwill_bonus_vs_face_diverge_on_loyalty
    """
    # A single non-loyal buyer (lifetime 1) → exactly face credit, no bonus.
    earned = fx.setup_credit_earning_order(quantity=2, seat_count=2)
    credit = earned["credit"]
    assert credit["amount_cents"] == 44800, \
        f"non-loyal cancel credit equals final 44800, got {credit['amount_cents']}"
    assert credit["bonus_applied"] is False


def test_dynamic_price_at_zero_scarcity_equals_ask(api):
    """PRD §3.3: "a demand multiplier of 1.0 plus 0.50 times that sold ratio, so
    the multiplier ranges from 1.00 at an empty listing up to 1.50 at a fully
    taken one; multiply the `ask_price_cents` by that demand multiplier and take
    the floor; then take whichever is larger, that floored figure or the
    `dynamic_floor_cents`."

    Design: Difficulty/combinatorial_formula/dynamic_price_scarcity_floor_cap_ordering_mode_a
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=4)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=4, pricing_mode="DYNAMIC", ask_price_cents=20000,
        dynamic_floor_cents=12000, barcode_prefix="DZ",
    )
    # 0 sold → sold_ratio 0 → demand 1.0 → raw floor(20000*1.0)=20000; floor 12000; cap 30000 → 20000.
    read = validate_success(api.get_listing(listing["id"], make_buyer_headers(base["buyer_id"])))
    assert read["available_seat_count"] == 4
    assert read["effective_price_cents"] == 20000, \
        f"empty listing → effective equals ask 20000, got {read['effective_price_cents']}"


def test_buyer_charge_qty1_fee_floor(api):
    """PRD §3.4: "the `buyer_fee_cents` is the floor of that base times the buyer
    fee rate of 0.12; the gross is the base plus the `buyer_fee_cents`."

    Design: Difficulty/combinatorial_formula/buyer_charge_per_line_fee_floor_then_sum_ordering_mode_b
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=1, ask_price_cents=20000, barcode_prefix="FE1",
    )
    order = fx.reserve_order(listing["id"], base["buyer_id"], 1, listing["version"])
    charged = validate_success(api.charge_order(order["id"], make_buyer_headers(base["buyer_id"])))
    # base 20000, fee floor(20000*0.12)=2400, final 22400.
    assert charged["buyer_fee_cents"] == 2400, \
        f"fee floor(20000*0.12)=2400, got {charged['buyer_fee_cents']}"
    assert charged["final_total_cents"] == 22400
