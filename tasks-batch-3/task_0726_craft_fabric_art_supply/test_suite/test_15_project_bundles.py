"""Project bundle materialization into order lines."""
from test_helpers import (
    validate_success, get_success_data,
    create_customer, create_product, make_customer_headers,
    create_project_bundle_payload, create_order_payload,
)


def test_bundle_materialization_creates_lines(api):
    """PRD §3.4: "If a project_bundle_id is supplied, one DRAFT order line is
    created for each entry in the bundle's bill of materials."

    Design: Corner/entities/bundle_materialization_creates_lines
    """
    customer = create_customer()
    p1 = create_product(sell_mode="UNIT", unit_price_cents=500)
    p2 = create_product(sell_mode="UNIT", unit_price_cents=300)
    headers = make_customer_headers(customer["id"])
    bom = [{"product_id": p1["id"], "quantity": 1}, {"product_id": p2["id"], "quantity": 2}]
    bundle = get_success_data(
        api.create_project_bundle(create_project_bundle_payload(customer["id"], bom), headers)
    )
    order = validate_success(
        api.create_order(
            create_order_payload(customer["id"], project_bundle_id=bundle["id"]), headers
        ),
        expected_status=201,
    )
    assert order["project_bundle_id"] == bundle["id"]
    lines = get_success_data(api.list_order_lines_by_order(order["id"], headers))
    assert len(lines) == 2
