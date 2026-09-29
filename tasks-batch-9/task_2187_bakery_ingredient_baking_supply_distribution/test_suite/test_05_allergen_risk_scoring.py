"""In-flight versus closed-book allergen risk scoring (PRD §3.7)."""

from test_helpers import (
    ALMOND_FLOUR,
    RICE_FLOUR,
    add_order_line,
    allocate_order,
    append_stop,
    create_customer,
    create_product,
    create_route,
    create_zone,
    deliver_stop,
    dispatch_route,
    open_order,
    read_customer,
    read_order,
    read_order_line,
    receive_lot,
    seal_route,
    set_clock,
    submit_order,
)


def _bakery_with_one_nut_order_dispatched():
    """1000 lb tree-nut on a dispatched order, 3000 lb allergen-free left behind."""
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer()
    almond = create_product(ALMOND_FLOUR)
    rice = create_product(RICE_FLOUR)
    nut_zone = create_zone(allergen_class="TREE_NUT")
    plain_zone = create_zone(allergen_class="NONE")
    receive_lot(almond["id"], nut_zone["id"], quantity_received_lb=10000)
    receive_lot(rice["id"], plain_zone["id"], quantity_received_lb=20000)

    order_a = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
    line_a = add_order_line(customer, order_a["id"], almond["id"], 1000)
    submit_order(customer, order_a["id"])
    allocate_order(order_a["id"])

    order_b = open_order(customer, requested_delivery_on="2026-09-20T00:00:00Z")
    line_b = add_order_line(customer, order_b["id"], rice["id"], 3000)
    submit_order(customer, order_b["id"])
    allocate_order(order_b["id"])

    route = create_route(service_on="2026-09-15T00:00:00Z", vehicle_capacity_lb=24000)
    stop_a = append_stop(
        route["id"], order_a["id"], "2026-09-15T08:00:00Z", "2026-09-15T10:00:00Z"
    )
    seal_route(route["id"])
    set_clock("2026-09-15T00:00:00Z")
    dispatch_route(route["id"])
    return {
        "customer": customer,
        "order_a": order_a,
        "order_b": order_b,
        "line_a": line_a,
        "line_b": line_b,
        "stop_a": stop_a,
    }


def test_in_flight_score_averages_every_unshipped_order_line():
    """PRD §3.7: "its input set is the order lines whose owning order has
    `fulfillment_status` in `NEW`, `ALLOCATED`, `ROUTED` or `LOADED`".

    1000 lb of tree-nut at weight 0.90 against 3000 lb of allergen-free stock
    averages to 22.50 across the two in-flight orders, which is below the 25.00
    amber floor.

    Design: Difficulty/dual_variant_calc/dual_variant_allergen_risk_exposure_provisional_vs_exposure_audited
    """
    scenario = _bakery_with_one_nut_order_dispatched()

    customer = read_customer(scenario["customer"]["id"])

    assert float(customer["allergen_risk_score"]) == 22.50, (
        f"Expected in-flight score 22.50, got {customer['allergen_risk_score']}"
    )
    assert customer["risk_tier"] == "GREEN", (
        f"Expected GREEN below 25.00, got {customer['risk_tier']}"
    )


def test_closed_book_score_counts_only_the_delivered_order_lines():
    """PRD §3.7: "its input set is the order lines whose owning order has
    `fulfillment_status` of `DELIVERED` or `SHORT_SHIPPED`, so the audited score
    never includes in-flight pounds."

    Once the tree-nut drop is confirmed, the audited set is that 1000 lb line
    alone, giving 90.00 and a `RED` tier, while the untouched 3000 lb order stays
    `ALLOCATED` and drops out of the score.

    Design: Difficulty/dual_variant_calc/dual_variant_allergen_risk_exposure_provisional_vs_exposure_audited
    """
    scenario = _bakery_with_one_nut_order_dispatched()

    deliver_stop(scenario["stop_a"]["id"])

    customer = read_customer(scenario["customer"]["id"])
    assert float(customer["allergen_risk_score"]) == 90.00, (
        f"Expected audited score 90.00, got {customer['allergen_risk_score']}"
    )
    assert customer["risk_tier"] == "RED", (
        f"Expected RED at 60.00 and above, got {customer['risk_tier']}"
    )
    assert read_order(scenario["order_a"]["id"])["fulfillment_status"] == "DELIVERED"
    assert read_order(scenario["order_b"]["id"])["fulfillment_status"] == "ALLOCATED"
    assert read_order_line(scenario["line_a"]["id"])["allocation_status"] == "SHIPPED"
    assert read_order_line(scenario["line_b"]["id"])["allocation_status"] == "RESERVED"
