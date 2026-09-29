"""The four-input pneumatic fill plan run at allocation (PRD §3.6)."""

from test_helpers import (
    FLOUR_HRW_INDEXED,
    ApiErrorId,
    add_order_line,
    allocate_order,
    api_client,
    assert_lot_inventory_conservation,
    create_customer,
    create_product,
    create_zone,
    deallocate_order,
    open_order,
    publish_index_quote,
    read_lot,
    read_order,
    read_order_line,
    read_silo,
    receive_lot,
    record_residual_reading,
    register_silo,
    set_clock,
    setup_active_contract,
    submit_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import WO


def _bulk_order_at_exact_headroom(residual_lb=10000):
    """Silo capacity 30000 with `residual_lb` blown in, against a 20000 lb line.

    Headroom is 30000 - residual; contract room is 25000 - 20000 + 20000; the
    compartment ceiling is 48000; the line itself is 20000.
    """
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer()
    product = create_product(FLOUR_HRW_INDEXED)
    publish_index_quote(
        index_code="HRW_WHEAT", effective_on="2026-07-01T00:00:00Z", price_cents_per_lb=38
    )
    zone = create_zone(allergen_class="GLUTEN")
    lot = receive_lot(product["id"], zone["id"], quantity_received_lb=50000)
    silo = register_silo(customer["id"], product["id"], capacity_lb=30000, min_fill_lb=2000)
    record_residual_reading(silo["id"], residual_lb)
    bundle = setup_active_contract(
        customer,
        product["id"],
        volume_committed_lb=25000,
        basis_cents_per_lb=6,
        pricing_mode="ORDER_DATE_INDEX",
        term_start_on="2026-08-01T00:00:00Z",
        term_end_on="2026-12-31T00:00:00Z",
    )
    order = open_order(
        customer,
        delivery_mode="BULK",
        contract_id=bundle["contract"]["id"],
        requested_delivery_on="2026-09-15T00:00:00Z",
    )
    line = add_order_line(customer, order["id"], product["id"], 20000)
    submit_order(customer, order["id"])
    return {
        "customer": customer,
        "product": product,
        "lot": lot,
        "silo": silo,
        "order": order,
        "order_line": line,
        "contract_line": bundle["contract_line"],
    }


def test_bulk_allocation_succeeds_when_the_fillable_amount_equals_the_line():
    """PRD §3.6: "The fillable amount is the smallest of those four. If the
    fillable amount is less than the line's `quantity_lb`, the allocation is
    rejected with `ERR_SILO_HEADROOM_INSUFFICIENT` (HTTP 422)."

    Headroom 30000 - 10000 = 20000 exactly equals the 20000 lb line, and the
    remaining three terms (contract room 25000, compartment ceiling 48000, the
    line itself) are all at least that, so the fill plan clears and the line is
    bound to the silo.

    Design: Difficulty/combinatorial_formula/combinatorial_mode_a_silo_fill_nested_min_over_four_inputs_at_exact_headroom_boundary
    """
    scenario = _bulk_order_at_exact_headroom(residual_lb=10000)

    allocated = validate_success(api_client.allocate_order(scenario["order"]["id"], {}, WO))

    assert allocated["fulfillment_status"] == "ALLOCATED", (
        f"Expected ALLOCATED, got {allocated['fulfillment_status']}"
    )
    line = read_order_line(scenario["order_line"]["id"])
    assert line["silo_id"] == scenario["silo"]["id"], (
        f"Expected silo_id {scenario['silo']['id']}, got {line['silo_id']}"
    )
    assert line["allocation_status"] == "RESERVED", (
        f"Expected RESERVED, got {line['allocation_status']}"
    )


def test_bulk_allocation_rejected_when_headroom_falls_one_pound_short():
    """PRD §3.6: "Headroom is the silo's `capacity_lb` less its current
    `residual_lb`."

    A level probe of 10001 lb leaves headroom of 19999 lb against the same
    20000 lb line, so the fillable amount is now below the line quantity and the
    allocation is rejected.

    Design: Difficulty/combinatorial_formula/combinatorial_mode_a_silo_fill_nested_min_over_four_inputs_at_exact_headroom_boundary
    """
    scenario = _bulk_order_at_exact_headroom(residual_lb=10000)
    allocate_order(scenario["order"]["id"])
    deallocate_order(scenario["order"]["id"])
    record_residual_reading(scenario["silo"]["id"], 10001)

    response = api_client.allocate_order(scenario["order"]["id"], {}, WO)

    validate_error(response, ApiErrorId.ERR_SILO_HEADROOM_INSUFFICIENT)
    order = read_order(scenario["order"]["id"])
    assert order["fulfillment_status"] == "NEW", (
        f"Expected the order to stay NEW, got {order['fulfillment_status']}"
    )
    line = read_order_line(scenario["order_line"]["id"])
    assert line["allocation_status"] == "UNALLOCATED", (
        f"Expected UNALLOCATED, got {line['allocation_status']}"
    )
    assert line["silo_id"] is None, f"Expected silo_id null, got {line['silo_id']}"
    assert read_silo(scenario["silo"]["id"])["residual_lb"] == 10001


def test_deallocation_restores_every_pound_bucket_on_the_picked_lot():
    """PRD §3.5: "Each line's `allocation_status` returns to `UNALLOCATED` with
    `lot_id` and `silo_id` cleared to null; on each released lot,
    `quantity_reserved_lb` decreases by the line's `quantity_lb` and
    `quantity_on_hand_lb` increases by the same amount, while
    `quantity_received_lb` is untouched."

    Design: Difficulty/combinatorial_formula/combinatorial_mode_a_silo_fill_nested_min_over_four_inputs_at_exact_headroom_boundary
    """
    scenario = _bulk_order_at_exact_headroom(residual_lb=10000)
    allocate_order(scenario["order"]["id"])

    deallocate_order(scenario["order"]["id"])

    lot = read_lot(scenario["lot"]["id"])
    assert lot["quantity_on_hand_lb"] == 50000, (
        f"Expected on-hand back at 50000, got {lot['quantity_on_hand_lb']}"
    )
    assert lot["quantity_reserved_lb"] == 0, (
        f"Expected reserved back at 0, got {lot['quantity_reserved_lb']}"
    )
    assert lot["quantity_consumed_lb"] == 0
    assert_lot_inventory_conservation(lot)
