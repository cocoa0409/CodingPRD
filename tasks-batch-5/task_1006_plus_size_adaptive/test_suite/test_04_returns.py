"""Extended-sizing returns: dual-variant refund pinning and lifecycle guards.

Queue A (Difficulty): return_provisional_vs_final_refund.
Queue B (Corner): exchange-without-variant, inspect-before-approve.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_customer_headers,
    register_customer, create_product, create_variant,
    open_order, add_line, checkout, drive_order_to_delivered,
    create_return_payload,
    setup_delivered_order,
)

SM = TEST_USERS["store_manager_headers"]


def _delivered_two_line_order_for_return(api):
    """Delivered order with lines of 6800 (v1) and 6000 (v2); restock_fee_pct 0.15."""
    customer = register_customer(api)
    product = create_product(api, base_price_cents=6000, size_min=10, size_max=34,
                             restock_fee_pct=0.15)
    v1 = create_variant(api, product["id"], size_code=22, color="Navy",
                        price_delta_cents=800, inventory_on_hand=10)
    v2 = create_variant(api, product["id"], size_code=14, color="Black",
                        price_delta_cents=0, inventory_on_hand=10)
    order = open_order(api, customer["id"])
    l1 = add_line(api, order["id"], customer["id"], v1["id"], 1)
    l2 = add_line(api, order["id"], customer["id"], v2["id"], 1)
    checkout(api, order["id"], customer["id"])
    drive_order_to_delivered(api, order["id"], customer["id"])
    return {"customer": customer, "order": order, "l1": l1, "l2": l2}


def test_return_provisional_refund_pinned_at_request(api):
    """PRD §3.4: "its `provisional_refund_cents` is pinned as an estimate: the sum of
    `line_total_cents` over the named `line_ids`, with no fees or damage yet
    accounted for."

    Design: Difficulty/dual_variant_calc/return_provisional_vs_final_refund
    """
    ctx = _delivered_two_line_order_for_return(api)
    payload = create_return_payload(
        ctx["order"]["id"], "RETURN", [ctx["l1"]["id"], ctx["l2"]["id"]]
    )
    resp = api.create_return(payload, make_customer_headers(ctx["customer"]["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["provisional_refund_cents"] == 12800


def test_return_final_refund_excludes_damaged_and_subtracts_restock_fee(api):
    """PRD §3.4: "the non-damaged returned total is the sum of `line_total_cents` over
    the returned lines excluding any in `damaged_line_ids`."
    PRD §3.4: "`restock_fee_cents` is the product's `restock_fee_pct` multiplied by
    that non-damaged total, rounded half up to whole cents. Finally
    `final_refund_cents` is the non-damaged total minus `restock_fee_cents`."

    Design: Difficulty/dual_variant_calc/return_provisional_vs_final_refund
    """
    ctx = _delivered_two_line_order_for_return(api)
    payload = create_return_payload(
        ctx["order"]["id"], "RETURN", [ctx["l1"]["id"], ctx["l2"]["id"]]
    )
    ret = validate_success(
        api.create_return(payload, make_customer_headers(ctx["customer"]["id"])),
        expected_status=201,
    )
    validate_success(api.transition_return(ret["id"], {"action": "APPROVE"}, SM))
    resp = api.transition_return(
        ret["id"], {"action": "INSPECT", "damaged_line_ids": [ctx["l2"]["id"]]}, SM
    )
    data = validate_success(resp)
    assert data["restock_fee_cents"] == 1020
    assert data["final_refund_cents"] == 5780


def test_exchange_return_without_variant_rejected(api):
    """PRD §3.4: "When `return_type` is `EXCHANGE`, the request must also carry an
    `exchange_variant_id` naming the replacement SKU; an exchange lacking it is
    rejected with `ERR_EXCHANGE_VARIANT_REQUIRED`".

    Design: Corner/validations/return_exchange_without_variant_returns_error
    """
    ctx = setup_delivered_order(api, variant_overrides={"size_code": 14, "inventory_on_hand": 10})
    payload = create_return_payload(ctx["order"]["id"], "EXCHANGE", [ctx["line"]["id"]])
    resp = api.create_return(payload, make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_EXCHANGE_VARIANT_REQUIRED.value)


def test_inspect_before_approve_returns_invalid_state(api):
    """PRD §3.4: "Inspecting it moves `APPROVED` to `INSPECTED` (permitted only while
    `APPROVED`)".
    PRD §3.4: "A transition requested from a state that does not allow it is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/return_inspect_before_approve_returns_invalid_state
    """
    ctx = setup_delivered_order(api, variant_overrides={"size_code": 14, "inventory_on_hand": 10})
    payload = create_return_payload(ctx["order"]["id"], "RETURN", [ctx["line"]["id"]])
    ret = validate_success(
        api.create_return(payload, make_customer_headers(ctx["customer"]["id"])),
        expected_status=201,
    )
    resp = api.transition_return(ret["id"], {"action": "INSPECT"}, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    result = validate_success(api.get_return(ret["id"], SM))
    assert result["status"] == "REQUESTED"
