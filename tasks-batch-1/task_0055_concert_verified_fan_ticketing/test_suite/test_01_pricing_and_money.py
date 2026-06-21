"""Dynamic pricing, demand bands, service fee, and refund-amount calculations.

Covers difficulty queue A rules dual_variant_calc, combinatorial_formula,
boundary_precision_check and corner queue B calculation claims.
"""
from test_helpers import (
    api_client,
    validate_success,
    setup_event_with_tier,
    register_and_verify_fan,
    create_pending_order,
    create_paid_order,
    pre_sell_seats,
    make_fan_headers,
)


def test_presale_order_prices_at_tier_price_no_surcharge(api):
    """PRD §3.4: "One presale variant overrides the demand band: if the event
    is in PRESALE at order creation, the demand surcharge is forced to 0 basis
    points regardless of the sold ratio, so presale buyers pay the tier price
    with no surcharge."
    PRD §3.4: "the tier-priced base is the face value multiplied by the tier's
    base_multiplier_bps divided by 10000, rounded half up."

    Design: Difficulty/dual_variant_calc/dynamic_price_presale_vs_general_band
    """
    event, tier = setup_event_with_tier(phase="PRESALE", face_value_cents=10000,
                                        venue_capacity=100, base_multiplier_bps=15000)
    fan = register_and_verify_fan("a@x.com", device="dev-a")
    _qe, order = create_pending_order(event, tier, fan, requested_qty=2)
    assert order["unit_price_cents"] == 15000, order
    assert order["subtotal_cents"] == 30000, order


def test_general_order_applies_demand_surcharge_band(api):
    """PRD §3.4: "when it is at least 0.80 (including a ratio of 1.00 or more)
    the surcharge is 3000 basis points. The unit price is then the tier-priced
    base multiplied by the sum of 10000 and the demand basis points, divided by
    10000, rounded half up."

    Same tier inputs as the presale case, but in GENERAL the surcharge applies.

    Design: Difficulty/dual_variant_calc/dynamic_price_presale_vs_general_band
    """
    # cap=7, pre-sell 6 -> sold_ratio 6/7 = 0.857 -> band2 (30%). tier mult 10000.
    event, tier = setup_event_with_tier(phase="GENERAL", face_value_cents=10000,
                                        venue_capacity=7, allocation=7,
                                        base_multiplier_bps=10000)
    pre_sell_seats(event, tier, 6, base_email="seed1", device="dev-seed1")
    fan = register_and_verify_fan("b@x.com", device="dev-b")
    _qe, order = create_pending_order(event, tier, fan, requested_qty=1)
    assert order["unit_price_cents"] == 13000, order


def test_refund_standard_tier_90pct_of_principal(api):
    """PRD §3.4: "If the holder's completed_purchase_count is at least the
    loyalty threshold of 3 prior paid purchases, the full principal is refunded;
    otherwise the standard refund of 9000 basis points (90%) of the principal is
    refunded, rounded half up."
    PRD §3.4: "the service fee is never refundable, so the refundable principal
    is the subtotal_cents."

    Design: Difficulty/dual_variant_calc/refund_loyal_vs_standard_tier
    """
    event, tier = setup_event_with_tier(phase="GENERAL", face_value_cents=10000,
                                        venue_capacity=100, base_multiplier_bps=10000)
    fan = register_and_verify_fan("a@x.com", device="dev-a")
    _qe, paid = create_paid_order(event, tier, fan, requested_qty=2)
    # completed_purchase_count == 1 (< 3) -> standard 90% of subtotal 20000 = 18000.
    refunded = validate_success(api.refund_order(
        paid["id"], {"expected_order_version": paid["version"]},
        make_fan_headers(fan["id"]),
    ), 200)
    assert refunded["refund_amount_cents"] == 18000, refunded
    assert refunded["status"] == "REFUNDED", refunded


def test_refund_loyal_tier_full_principal(api):
    """PRD §3.4: "If the holder's completed_purchase_count is at least the
    loyalty threshold of 3 prior paid purchases, the full principal is refunded;
    otherwise the standard refund of 9000 basis points (90%) of the principal is
    refunded, rounded half up."

    Design: Difficulty/dual_variant_calc/refund_loyal_vs_standard_tier
    """
    # Build a fan with 3 prior PAID orders, then a 4th PAID order to refund.
    event, tier = setup_event_with_tier(phase="GENERAL", face_value_cents=10000,
                                        venue_capacity=100, allocation=50,
                                        base_multiplier_bps=10000)
    fan = register_and_verify_fan("loyal@x.com", device="dev-l")
    headers = make_fan_headers(fan["id"])
    for _ in range(3):
        create_paid_order(event, tier, fan, requested_qty=2)
    _qe, paid = create_paid_order(event, tier, fan, requested_qty=2)
    refreshed = validate_success(api.get_fan(fan["id"], headers), 200)
    assert refreshed["completed_purchase_count"] >= 3, refreshed
    refunded = validate_success(api.refund_order(
        paid["id"], {"expected_order_version": paid["version"]}, headers
    ), 200)
    assert refunded["refund_amount_cents"] == 20000, refunded


def test_loyal_full_refund_amount_corner(api):
    """PRD §3.4: "If the holder's completed_purchase_count is at least the
    loyalty threshold of 3 prior paid purchases, the full principal is refunded".

    Design: Corner/calculations/refund_loyal_full_principal
    """
    event, tier = setup_event_with_tier(phase="GENERAL", face_value_cents=10000,
                                        venue_capacity=100, allocation=50,
                                        base_multiplier_bps=10000)
    fan = register_and_verify_fan("loyal2@x.com", device="dev-l2")
    headers = make_fan_headers(fan["id"])
    for _ in range(3):
        create_paid_order(event, tier, fan, requested_qty=2)
    _qe, paid = create_paid_order(event, tier, fan, requested_qty=2)
    refunded = validate_success(api.refund_order(
        paid["id"], {"expected_order_version": paid["version"]}, headers
    ), 200)
    assert refunded["refund_amount_cents"] == 20000, refunded


def test_unit_price_nested_band_and_tier_multiplier(api):
    """PRD §3.4: "the tier-priced base is the face value multiplied by the
    tier's base_multiplier_bps divided by 10000, rounded half up. It then
    determines a demand band from the event's sold ratio ... The unit price is
    then the tier-priced base multiplied by the sum of 10000 and the demand
    basis points, divided by 10000, rounded half up."

    Design: Difficulty/combinatorial_formula/dynamic_price_nested_band_and_multiplier
    """
    # face 10000, mult 10000 -> tier_priced 10000; cap 7 pre-sold 6 -> band2 30% -> 13000.
    event, tier = setup_event_with_tier(phase="GENERAL", face_value_cents=10000,
                                        venue_capacity=7, allocation=7,
                                        base_multiplier_bps=10000)
    pre_sell_seats(event, tier, 6, base_email="seedc", device="dev-seedc")
    fan = register_and_verify_fan("bb@x.com", device="dev-bb")
    _qe, order = create_pending_order(event, tier, fan, requested_qty=1)
    assert order["unit_price_cents"] == 13000, order


def test_order_total_service_fee_sum_then_fee_rounding(api):
    """PRD §3.4: "The subtotal_cents is the locked unit_price_cents multiplied by
    quantity, computed exactly with no rounding. The service_fee_cents is the
    service fee applied to that summed subtotal — the subtotal multiplied by 1200
    basis points divided by 10000, rounded half up once — never applied per seat.
    The total_cents is the subtotal plus the service fee."

    Design: Difficulty/combinatorial_formula/order_total_sum_then_fee_rounding
    """
    # PRESALE, mult 11500 -> unit 11500; qty 3 -> subtotal 34500;
    # fee round(34500*1200/10000)=4140; total 38640.
    event, tier = setup_event_with_tier(phase="PRESALE", face_value_cents=10000,
                                        venue_capacity=100, base_multiplier_bps=11500)
    fan = register_and_verify_fan("c@x.com", device="dev-c")
    _qe, order = create_pending_order(event, tier, fan, requested_qty=3)
    assert order["unit_price_cents"] == 11500, order
    assert order["subtotal_cents"] == 34500, order
    assert order["service_fee_cents"] == 4140, order
    assert order["total_cents"] == 38640, order


def test_demand_band_at_exact_80pct_uses_band2(api):
    """PRD §3.4: "when it is at least 0.80 (including a ratio of 1.00 or more)
    the surcharge is 3000 basis points."

    sold_ratio exactly 0.80 (4/5) is inclusive at the lower edge -> 30% surcharge.

    Design: Difficulty/boundary_precision_check/dynamic_price_band_at_exact_80_pct
    """
    event, tier = setup_event_with_tier(phase="GENERAL", face_value_cents=10000,
                                        venue_capacity=5, allocation=5,
                                        base_multiplier_bps=10000)
    pre_sell_seats(event, tier, 4, base_email="seedk", device="dev-seedk")
    fan = register_and_verify_fan("k@x.com", device="dev-k")
    _qe, order = create_pending_order(event, tier, fan, requested_qty=1)
    assert order["unit_price_cents"] == 13000, order


def test_demand_band_below_50pct_no_surcharge(api):
    """PRD §3.4: "When the sold ratio is below 0.50 the demand surcharge is 0
    basis points".

    sold_ratio 0.06 (6/100) -> band0 -> unit equals tier price 10000.

    Design: Corner/calculations/dynamic_price_band0_below_50pct
    """
    event, tier = setup_event_with_tier(phase="GENERAL", face_value_cents=10000,
                                        venue_capacity=100, allocation=100,
                                        base_multiplier_bps=10000)
    pre_sell_seats(event, tier, 6, base_email="seedd", device="dev-seedd")
    fan = register_and_verify_fan("bd@x.com", device="dev-bd")
    _qe, order = create_pending_order(event, tier, fan, requested_qty=1)
    assert order["unit_price_cents"] == 10000, order
