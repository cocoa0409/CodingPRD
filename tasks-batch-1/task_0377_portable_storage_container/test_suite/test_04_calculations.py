"""Calculation tests: protection-premium floor, late-fee cap, charge-list filtering,
and immediate consistency (PRD §2.3, §3.4, §3.7, §3.9)."""
from test_helpers import (
    validate_success, validate_paginated,
    create_packing_supply_order_payload,
    TEST_USERS, make_customer_headers,
)
from test_helpers import fixtures as F

DO = TEST_USERS["dispatch_operator_headers"]
BC = TEST_USERS["billing_clerk_headers"]


def test_protection_premium_floor_applies(api):
    """PRD §3.4: "Take the plan's `base_premium_cents` and add to it the plan's `rate_bps`
    multiplied by the agreement's `declared_value_cents`, divided by 10,000, with that
    product rounded half up to whole cents; call the sum the raw premium. The locked
    `monthly_premium_cents` is the larger of the raw premium and the plan's
    `min_premium_cents`."

    Design: Corner/calculations/protection_premium_floor_applies
    """
    # PLUS: base 1500 + round(80*10000/10000=80) = 1580 raw, below min 2000 floor.
    world, ag, unit = F.setup_active_agreement(
        tier_code="PLUS", declared_value_cents=10000,
        plan_overrides={"base_premium_cents": 1500, "rate_bps": 80,
                        "min_premium_cents": 2000, "coverage_cap_cents": 100000000})
    fresh = validate_success(api.get_rental_agreement(ag["id"], BC), 200)
    assert fresh["monthly_premium_cents"] == 2000


def test_late_fee_cap_caps_at_half_balance(api):
    """PRD §3.9: "That gross is then capped: the cap is 50 percent of the agreement's
    `balance_due_cents`, rounded half up to whole cents, and the late fee charged is the
    smaller of the gross and the cap."

    Design: Corner/calculations/late_fee_cap_caps_at_half_balance
    """
    # C8 NONE FIXED_30 delivered 2026-07-16: proration 6000*16/30=3200, delivery_fee 0 -> balance 3200.
    # At 6 days overdue uncapped tier1 gross = 2500 + 200*1 = 2700; cap = round(3200*0.50)=1600 wins.
    world, ag, unit = F.setup_active_agreement(
        size_code="C8", tier_code="NONE", proration_method="FIXED_30",
        monthly_rate_cents=6000, delivery_fee_cents=0, footprint_sqft=80)
    F.advance_clock_and_sweep("2026-07-22T12:00:00Z")

    after = validate_success(api.get_rental_agreement(ag["id"], BC), 200)
    assert after["billing_status"] == "PAST_DUE"

    charges, _ = validate_paginated(
        api.list_charges(ag["id"], BC, params={"charge_type": "LATE_FEE"}))
    assert len(charges) == 1
    assert charges[0]["amount_cents"] == 1600


def test_list_charges_filtered_by_type(api):
    """PRD §3.4: "The system posts a `DELIVERY_FEE` charge equal to the `delivery_fee_cents`
    of the `ContainerModel` for the agreement's size."

    Design: Corner/endpoints/list_charges_filtered_by_type_reverse_reachability
    """
    # C16 delivery_fee_cents = 8900 (default model).
    world, ag, unit = F.setup_active_agreement(tier_code="NONE")
    charges, _ = validate_paginated(
        api.list_charges(ag["id"], BC, params={"charge_type": "DELIVERY_FEE"}))
    assert len(charges) == 1
    assert charges[0]["charge_type"] == "DELIVERY_FEE"
    assert charges[0]["amount_cents"] == 8900


def test_immediate_balance_visible_after_packing_order(api):
    """PRD §3.7: "On placement the system posts a `PACKING_SUPPLIES` charge equal to
    `total_cents` and recomputes the agreement's `balance_due_cents`." PRD §2.4: "When the
    server recomputes a derived field on a resource ... that recomputation is a mutation of
    the owning resource".

    Design: Corner/consistency_model/immediate_balance_visible_in_same_response_chain
    """
    # NONE-tier C16 balance after activation = 8900 + 10271 + 0 = 19171.
    # Packing order of three 733-cent lines sum-then-tax @825bps = total 2380 -> balance 21551.
    world, ag, unit = F.setup_active_agreement(tier_code="NONE")
    cust_id = world["customer"]["id"]
    lines = [
        {"sku": "BUBBLE", "qty": 1, "unit_price_cents": 733, "bulk_threshold": 5, "bulk_pct": 0},
        {"sku": "PAPER", "qty": 1, "unit_price_cents": 733, "bulk_threshold": 5, "bulk_pct": 0},
        {"sku": "TAPE", "qty": 1, "unit_price_cents": 733, "bulk_threshold": 5, "bulk_pct": 0},
    ]
    validate_success(api.create_packing_supply_order(
        create_packing_supply_order_payload(ag["id"], lines=lines, tax_rate_bps=825),
        make_customer_headers(cust_id)), 201)

    fresh = validate_success(api.get_rental_agreement(ag["id"], BC), 200)
    assert fresh["balance_due_cents"] == 21551
