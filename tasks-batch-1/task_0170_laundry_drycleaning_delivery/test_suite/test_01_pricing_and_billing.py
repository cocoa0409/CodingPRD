"""Pricing and subscription-billing calculations.

Covers dual-variant order totals, the combinatorial per-line price formula, the
round-per-line-then-sum rule, and the read-before-write subscription-billing
order. All literal expected values are copied from the design indices.
"""
import test_helpers as th


def test_estimate_and_final_totals_diverge(api):
    """PRD §3.3: "the order's `estimate_total_cents` is set to the sum of the
    estimate line prices of all garments on the order (none are lost at schedule
    time)."
    PRD §3.5: "Entering `QC_HOLD` recomputes the order's `final_total_cents` as
    the sum of the `final_line_cents` of all garments on the order that are not
    lost - lost garments are excluded entirely - and this sum of already-rounded
    integer line prices receives no further rounding."

    Estimate from declared (4000g WF + 3 DRY_CLEAN pieces): WF 4kg*400=1600,
    DRY 3*900=2700, total 4300. Final from actuals (6000g WF + 2 pieces):
    WF 5*400+1*300=2300, DRY 2*900=1800, total 4100.

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_total_diverge
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[
            {"service_type": "WASH_FOLD", "declared_weight_grams": 4000},
            {"service_type": "DRY_CLEAN", "declared_piece_count": 3},
        ],
        actuals=[{"actual_weight_grams": 6000}, {"actual_piece_count": 2}],
    )
    # estimate was computed at schedule
    after_schedule = th.get_order(order["id"], customer["id"])
    assert after_schedule["estimate_total_cents"] == 4300, \
        f"estimate should be 4300, got {after_schedule['estimate_total_cents']}"

    for g in garments:
        th.finish_clean(order, g)
    held = th.validate_success(api.qc_hold(order["id"], th.plant_headers()))
    assert held["estimate_total_cents"] == 4300, "estimate must remain declared-derived 4300"
    assert held["final_total_cents"] == 4100, \
        f"final should be 4100, got {held['final_total_cents']}"


def test_estimate_and_final_totals_diverge_estimate_immutable(api):
    """PRD §3.3: "each garment's `estimate_line_cents` is computed from its
    declared measurements, and the order's `estimate_total_cents` is set to the
    sum of the estimate line prices of all garments on the order (none are lost
    at schedule time)."

    The estimate is locked to declared values and is unaffected by the actuals
    logged later: declared (4000g WF + 3 pieces) => 4300 throughout.

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_total_diverge
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[
            {"service_type": "WASH_FOLD", "declared_weight_grams": 4000},
            {"service_type": "DRY_CLEAN", "declared_piece_count": 3},
        ],
        actuals=[{"actual_weight_grams": 6000}, {"actual_piece_count": 2}],
    )
    for g in garments:
        th.finish_clean(order, g)
    held = th.validate_success(api.qc_hold(order["id"], th.plant_headers()))
    assert held["estimate_total_cents"] == 4300, \
        f"estimate stays declared-derived 4300, got {held['estimate_total_cents']}"


def test_garment_line_price_discount_then_rush(api):
    """PRD §3.3: "a subscriber discount applies only to `DRY_CLEAN` and
    `ALTERATION` lines and never to `WASH_FOLD`: when the order belongs to an
    active subscription, the base for those two service types is multiplied by
    one minus the plan's `dryclean_discount_pct`. Then, if the order is a rush
    order and the plan does not waive rush, the line is multiplied by the rush
    surcharge factor of 1.25"

    DRY_CLEAN 4 pieces: 4*900=3600, *0.75 (25% sub discount)=2700, *1.25 (rush)
    =3375.

    Design: Difficulty/combinatorial_formula/garment_line_price_tiered_discount_rush_modeA
    """
    plan = th.create_plan(tier="PLUS", monthly_fee_cents=6000,
                          included_wash_fold_grams=5000, overage_rate_cents_per_kg=350,
                          dryclean_discount_pct=0.25, rush_waived=False)
    customer, pickup, delivery = th.create_zone_setup()
    th.create_subscription(customer["id"], plan["id"])
    sub = th.api_client.list_subscriptions(th.make_customer_headers(customer["id"]),
                                            params={"customer_id": customer["id"]})
    sub_id = th.validate_paginated(sub)[0][0]["id"]

    _, _, _, order, garments = th.order_in_processing(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 4}],
        actuals=[{"actual_piece_count": 4}],
        order_overrides={"subscription_id": sub_id, "rush": True},
    )
    finished = th.validate_success(api.finish_clean(order["id"], garments[0]["id"], th.plant_headers()))
    assert finished["final_line_cents"] == 3375, \
        f"line should be 3375, got {finished['final_line_cents']}"


def test_garment_line_price_discount_excludes_wash_fold(api):
    """PRD §3.3: "a subscriber discount applies only to `DRY_CLEAN` and
    `ALTERATION` lines and never to `WASH_FOLD`"
    PRD §3.3: "a garment at or under 5 kilograms is simply its kilogram weight
    times 400 cents"

    A subscriber's 4kg WASH_FOLD line: the subscriber discount must NOT apply, so
    the line is 4*400=1600 (no discount factor) even on a discount plan.

    Design: Difficulty/combinatorial_formula/garment_line_price_tiered_discount_rush_modeA
    """
    plan = th.create_plan(tier="PLUS", monthly_fee_cents=6000,
                          included_wash_fold_grams=0, overage_rate_cents_per_kg=350,
                          dryclean_discount_pct=0.25, rush_waived=False)
    customer, pickup, delivery = th.create_zone_setup()
    sub = th.create_subscription(customer["id"], plan["id"])
    _, _, _, order, garments = th.order_in_processing(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 4000}],
        actuals=[{"actual_weight_grams": 4000}],
        order_overrides={"subscription_id": sub["id"], "rush": False},
    )
    finished = th.validate_success(api.finish_clean(order["id"], garments[0]["id"], th.plant_headers()))
    assert finished["final_line_cents"] == 1600, \
        f"wash-fold gets no subscriber discount: 1600, got {finished['final_line_cents']}"


def test_order_total_rounds_per_line_then_sums(api):
    """PRD §2.5: "the governing rule is that each individual garment line is
    rounded to whole cents first, and order totals are then formed by plain
    integer addition of those already-rounded lines, with no further rounding
    applied to the sum."

    Three WASH_FOLD garments each 1 gram, rush: raw 0.001kg*400*1.25 = 0.5 cents
    rounds half-up to 1 cent per line; sum = 3 (not round(1.5)=2).

    Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum_modeB
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[
            {"service_type": "WASH_FOLD", "declared_weight_grams": 1},
            {"service_type": "WASH_FOLD", "declared_weight_grams": 1},
            {"service_type": "WASH_FOLD", "declared_weight_grams": 1},
        ],
        actuals=[{"actual_weight_grams": 1}, {"actual_weight_grams": 1}, {"actual_weight_grams": 1}],
        order_overrides={"rush": True},
    )
    for g in garments:
        finished = th.finish_clean(order, g)
        assert finished["final_line_cents"] == 1, \
            f"each 1g rush line rounds to 1, got {finished['final_line_cents']}"
    held = th.validate_success(api.qc_hold(order["id"], th.plant_headers()))
    assert held["final_total_cents"] == 3, \
        f"sum of three rounded 1-cent lines is 3, got {held['final_total_cents']}"


def test_per_line_round_half_up_at_estimate_stage(api):
    """PRD §2.5: "each individual garment line is rounded to whole cents first,
    and order totals are then formed by plain integer addition of those
    already-rounded lines, with no further rounding applied to the sum."

    Same round-per-line-then-sum rule on the estimate path (declared values):
    three rush WASH_FOLD lines of 1g each round to 1 cent and sum to 3.

    Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum_modeB
    """
    customer, pickup, delivery, order, garments = th.create_order_with_garments(
        garments=[
            {"service_type": "WASH_FOLD", "declared_weight_grams": 1},
            {"service_type": "WASH_FOLD", "declared_weight_grams": 1},
            {"service_type": "WASH_FOLD", "declared_weight_grams": 1},
        ],
        order_overrides={"rush": True},
    )
    scheduled = th.validate_success(
        api.schedule_order(order["id"], th.make_customer_headers(customer["id"])))
    assert scheduled["estimate_total_cents"] == 3, \
        f"estimate sum of three rounded 1-cent lines is 3, got {scheduled['estimate_total_cents']}"


def test_subscription_billing_reads_prior_usage_before_write(api):
    """PRD §3.6: "the subscriber's prior cycle usage is read from
    `cycle_wash_fold_grams_used` before this order is added. Third, the remaining
    inclusion is the plan's `included_wash_fold_grams` minus that prior usage,
    floored at zero. Fourth, the grams this order can cover is the smaller of
    this order's wash-fold grams and the remaining inclusion. Fifth, the
    `subscription_credit_cents` is the covered grams converted to kilograms
    (divided by 1000) times the tier-1 wash-fold rate of 400 cents per kilogram"

    Prior used 2000 of 5000 included => remaining 3000; this order 4000g =>
    covered 3000g => credit round_half_up(3*400)=1200. After: used becomes 6000.

    Design: Difficulty/combinatorial_formula/subscription_billing_read_before_write_modeC
    """
    plan = th.create_plan(tier="PLUS", monthly_fee_cents=6000,
                          included_wash_fold_grams=5000, overage_rate_cents_per_kg=350,
                          dryclean_discount_pct=0.25)
    customer, pickup, delivery = th.create_zone_setup()
    sub = th.create_subscription(customer["id"], plan["id"])

    # prior order: 2000g wash-fold, delivered, sets cycle_used = 2000
    th.order_delivered(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}],
        actuals=[{"actual_weight_grams": 2000}],
        order_overrides={"subscription_id": sub["id"]},
    )

    # second order: 4000g wash-fold to QC_HOLD then qc-pass triggers billing
    _, _, _, order2, _ = th.order_at_qc_hold(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 4000}],
        actuals=[{"actual_weight_grams": 4000}],
        order_overrides={"subscription_id": sub["id"]},
    )
    th.qc_pass(order2)

    invoices, _ = th.validate_paginated(
        api.get_order_invoice(order2["id"], th.make_customer_headers(customer["id"])))
    assert invoices, "qc-pass must have created an invoice"
    assert invoices[0]["subscription_credit_cents"] == 1200, \
        f"credit should be 1200, got {invoices[0]['subscription_credit_cents']}"

    refreshed_sub = th.validate_success(
        api.get_subscription(sub["id"], th.make_customer_headers(customer["id"])))
    assert refreshed_sub["cycle_wash_fold_grams_used"] == 6000, \
        f"cycle usage should advance to 6000, got {refreshed_sub['cycle_wash_fold_grams_used']}"


def test_subscription_credit_valued_at_tier1_rate(api):
    """PRD §3.6: "the `subscription_credit_cents` is the covered grams converted
    to kilograms (divided by 1000) times the tier-1 wash-fold rate of 400 cents
    per kilogram - inclusion is always valued at the tier-1 rate and never the
    tier-2 rate - rounded once with round-half-up."

    Fresh subscriber, plan includes 8000g; first order 6000g wash-fold (over the
    5kg tier-1 boundary) is fully covered, so credit = 6*400 = 2400 valued
    entirely at the tier-1 rate (not the tier-2 rate for the excess).

    Design: Difficulty/combinatorial_formula/subscription_billing_read_before_write_modeC
    """
    plan = th.create_plan(tier="PREMIUM", monthly_fee_cents=9000,
                          included_wash_fold_grams=8000, overage_rate_cents_per_kg=250,
                          dryclean_discount_pct=0.40)
    customer, pickup, delivery = th.create_zone_setup()
    sub = th.create_subscription(customer["id"], plan["id"])
    _, _, _, order, _ = th.order_at_qc_hold(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 6000}],
        actuals=[{"actual_weight_grams": 6000}],
        order_overrides={"subscription_id": sub["id"]},
    )
    th.qc_pass(order)
    invoices, _ = th.validate_paginated(
        api.get_order_invoice(order["id"], th.make_customer_headers(customer["id"])))
    assert invoices[0]["subscription_credit_cents"] == 2400, \
        f"6kg fully covered at tier-1 rate = 2400, got {invoices[0]['subscription_credit_cents']}"
