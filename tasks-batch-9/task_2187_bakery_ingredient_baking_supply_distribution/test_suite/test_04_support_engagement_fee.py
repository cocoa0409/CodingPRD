"""Marginally tiered bench fees and their attachment to an order (PRD §3.11)."""

from test_helpers import (
    ALMOND_FLOUR,
    add_order_line,
    allocate_order,
    api_client,
    attach_engagement,
    create_customer,
    create_product,
    create_zone,
    log_hours,
    open_engagement,
    read_customer,
    read_engagement,
    read_order,
    receive_lot,
    set_clock,
    submit_order,
    open_order,
)


def _red_tier_bakery_with_engagement(hours=12.5):
    """A bakery whose only in-flight line is tree-nut, so its tier reads `RED`."""
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer()
    product = create_product(ALMOND_FLOUR)
    zone = create_zone(allergen_class="TREE_NUT")
    receive_lot(product["id"], zone["id"], quantity_received_lb=10000)
    order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
    line = add_order_line(customer, order["id"], product["id"], 1000)
    submit_order(customer, order["id"])
    allocate_order(order["id"])
    engagement = open_engagement(customer, product["id"], specialist_user_id="ts-1")
    engagement = log_hours(engagement["id"], hours, specialist_user_id="ts-1")
    return {
        "customer": customer,
        "product": product,
        "order": order,
        "order_line": line,
        "engagement": engagement,
    }


def test_attach_fee_bands_are_marginal_and_scaled_by_the_red_tier_multiplier():
    """PRD §3.11: "Of those billable hours, the first eight bill at one hundred
    eighty-five dollars per hour — 18500 cents — and every billable hour beyond
    the eighth bills at the lower rate of one hundred forty-five dollars per
    hour, or 14500 cents."

    PRD §3.11: "when the owning bakery's `risk_tier` as persisted at computation
    time reads `RED`, the gross is multiplied by one and a quarter".

    12.5 logged hours leave 10.5 billable, so the gross is 8 × 18500 plus
    2.5 × 14500 = 184250, and the RED multiplier gives 230312.5 rounded half-up
    once to 230313.

    Design: Difficulty/combinatorial_formula/combinatorial_mode_a_attach_fee_marginal_tiers_times_red_tier_multiplier
    """
    scenario = _red_tier_bakery_with_engagement(hours=12.5)

    customer = read_customer(scenario["customer"]["id"])
    assert float(customer["allergen_risk_score"]) == 90.00, (
        f"Expected in-flight score 90.00, got {customer['allergen_risk_score']}"
    )
    assert customer["risk_tier"] == "RED", (
        f"Expected RED, got {customer['risk_tier']}"
    )
    engagement = scenario["engagement"]
    assert engagement["status"] == "BILLABLE", (
        f"Expected BILLABLE after 12.5 hours, got {engagement['status']}"
    )
    assert float(engagement["hours_logged"]) == 12.5
    assert engagement["attach_fee_cents"] == 230313, (
        f"Expected attach fee 230313, got {engagement['attach_fee_cents']}"
    )


def test_attaching_the_fee_reprices_the_order_and_recomputes_open_exposure():
    """PRD §3.11: "Attachment sets the engagement's `order_id`, copies
    `attach_fee_cents` into the order's `tech_attach_fee_cents`, reprices the
    order through the `PROVISIONAL` self-loop so the fee lands inside
    `total_cents`, recomputes the bakery's `open_exposure_cents`, and increments
    the order's `version` by 1."

    Subtotal 890000 plus surcharge 22250 plus fee 230313 less rebate 8900 gives
    1133663.

    Design: Difficulty/combinatorial_formula/combinatorial_mode_a_attach_fee_marginal_tiers_times_red_tier_multiplier
    """
    scenario = _red_tier_bakery_with_engagement(hours=12.5)

    attach_engagement(
        scenario["engagement"]["id"], scenario["order"]["id"], specialist_user_id="ts-1"
    )

    engagement = read_engagement(scenario["engagement"]["id"])
    assert engagement["status"] == "ATTACHED", (
        f"Expected ATTACHED, got {engagement['status']}"
    )
    assert engagement["order_id"] == scenario["order"]["id"]
    order = read_order(scenario["order"]["id"])
    assert order["tech_attach_fee_cents"] == 230313, (
        f"Expected tech_attach_fee_cents 230313, got {order['tech_attach_fee_cents']}"
    )
    assert order["subtotal_cents"] == 890000
    assert order["fuel_surcharge_cents"] == 22250
    assert order["volume_rebate_cents"] == 8900
    assert order["total_cents"] == 1133663, (
        f"Expected total 1133663, got {order['total_cents']}"
    )
    customer = read_customer(scenario["customer"]["id"])
    assert customer["open_exposure_cents"] == 1133663, (
        f"Expected open exposure 1133663, got {customer['open_exposure_cents']}"
    )
