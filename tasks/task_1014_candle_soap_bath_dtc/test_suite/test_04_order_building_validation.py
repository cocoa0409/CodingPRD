"""Add-line and checkout guard rails: inventory, safety, existence, editability, empty order."""
import test_helpers as H


def test_add_line_insufficient_inventory(api):
    """PRD §3.6: "Finally, inventory sufficiency: the batch's `quantity_available` must be at
    least the requested `quantity`, otherwise the line is rejected with
    `ERR_INSUFFICIENT_INVENTORY`."

    Design: Corner/validations/add_line_insufficient_inventory
    """
    cat = H.released_catalog(product_type="SOAP", list_price_cents=1000, quantity=5)
    customer = H.new_customer()
    order = H.new_order(customer["id"])
    resp = api.add_line(order["id"], H.create_line_payload(cat["sku"]["id"], cat["batch"]["id"], 10),
                        H.make_customer_headers(customer["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_INSUFFICIENT_INVENTORY)


def test_add_line_safety_label_required(api):
    """PRD §3.6: "First, safety labeling: if the sku's `requires_safety_label` is true, the
    chosen batch must have `is_safety_labeled` true, otherwise the line is rejected with
    `ERR_SAFETY_LABEL_REQUIRED`."

    Design: Corner/validations/add_line_safety_label_required
    """
    # CANDLE sku (safety-required); batch RELEASED directly from CREATED (never labeled).
    cat = H.released_catalog(product_type="CANDLE", list_price_cents=4000, quantity=10, labeled=False)
    assert cat["batch"]["is_safety_labeled"] is False
    customer = H.new_customer()
    order = H.new_order(customer["id"])
    resp = api.add_line(order["id"], H.create_line_payload(cat["sku"]["id"], cat["batch"]["id"], 1),
                        H.make_customer_headers(customer["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_SAFETY_LABEL_REQUIRED)


def test_add_line_batch_not_found(api):
    """PRD §2.10: "Body-supplied foreign keys — for example the `sku_id` and `batch_id` on an
    order line — are validated the same way."
    PRD §2.10: "each returning HTTP 404."

    Design: Corner/validations/add_line_batch_not_found
    """
    sku = H.new_sku(H.new_product(product_type="SOAP")["id"], list_price_cents=1000)
    customer = H.new_customer()
    order = H.new_order(customer["id"])
    resp = api.add_line(order["id"], H.create_line_payload(sku["id"], H.NON_EXISTENT_UUID, 1),
                        H.make_customer_headers(customer["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_BATCH_NOT_FOUND)


def test_add_line_to_checked_out_order_not_editable(api):
    """PRD §3.6: "Lines may only be added while the order's `fulfillment_status` is `PENDING`;
    adding a line to an order in any other fulfillment state is rejected with
    `ERR_ORDER_NOT_EDITABLE`."

    Design: Corner/state_machines/add_line_to_checked_out_order_not_editable
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=1000, quantity=1, batch_quantity=20)
    assert ctx["order"]["fulfillment_status"] == "ALLOCATED"
    resp = api.add_line(ctx["order"]["id"],
                        H.create_line_payload(ctx["sku"]["id"], ctx["batch"]["id"], 1),
                        H.make_customer_headers(ctx["customer"]["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_ORDER_NOT_EDITABLE)


def test_return_request_requires_delivered_order(api):
    """PRD §3.8: "the request captures the target as `order_id` and requires that order's
    `fulfillment_status` to be `DELIVERED`, otherwise it is rejected with
    `ERR_ORDER_NOT_DELIVERED`."

    Design: Corner/state_machines/return_request_requires_delivered_order
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=1000, quantity=1, batch_quantity=10)
    # Order is ALLOCATED (paid), not yet DELIVERED.
    resp = api.request_return(ctx["order"]["id"], H.create_return_payload(reason="too soon"),
                              H.make_customer_headers(ctx["customer"]["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_ORDER_NOT_DELIVERED)


def test_checkout_empty_order_rejected(api):
    """PRD §3.7: "Checkout requires the order to be `PENDING` and `UNPAID`, to contain at least
    one `RESERVED` line (an order with zero reserved lines is rejected with `ERR_EMPTY_ORDER`)".

    Design: Corner/state_machines/empty_order_checkout_rejected
    """
    customer = H.new_customer()
    order = H.new_order(customer["id"])
    resp = api.checkout_order(order["id"], order["version"], H.make_customer_headers(customer["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_EMPTY_ORDER)
    assert H.fetch_order(order["id"])["payment_status"] == "UNPAID"
