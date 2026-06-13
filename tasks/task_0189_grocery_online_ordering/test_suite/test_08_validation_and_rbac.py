"""Auth, referential validation, and RBAC (corner queue B).

Covers missing user context, existence-before-state ordering, pick-quantity
validation, cross-store/discontinued/suspended/closed referential rejections, and
role-exclusive operation enforcement.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    make_customer_headers,
    make_picker_headers,
    set_clock,
    create_store,
    create_customer,
    create_picker,
    create_product,
    create_slot,
    place_order,
    get_line_ids,
    claim_order,
    pick_line,
    stage_order,
    discontinue_product,
    suspend_customer,
    close_store,
    setup_single_unit_order_staged,
    ADMIN,
    OPS,
)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "A request missing or malforming either header is rejected with `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/validations/val_missing_user_context_header
    """
    resp = api.create_store({"name": "NoAuth"}, headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT.value, 401)


def test_existence_checked_before_state_on_stage(api):
    """PRD §2.10: "(3) existence — every resource named by a path identifier must exist, else the corresponding not-found error; ... (5) state — the target resource must be in the correct state for the requested transition ... a check earlier in this ordering always preempts a later one ... "

    Design: Corner/validations/val_existence_before_state_order_not_found
    """
    store = create_store()
    picker = create_picker(store["id"])
    resp = api.stage_order("00000000-0000-4000-8000-000000000001",
                           make_picker_headers(picker["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)


def test_pick_without_quantity_rejected(api):
    """PRD §3.3: "For a `UNIT` product, `picked_qty` must be present and greater than 0; for a `WEIGHT` product, `actual_weight_kg` must be present and greater than 0; a missing or non-positive quantity is rejected with `ERR_INVALID_PICK_QUANTITY`."

    Design: Corner/validations/val_pick_missing_quantity
    """
    store = create_store()
    customer = create_customer(email="cc12@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": a["id"], "requested_qty": 1}])
    ph = make_picker_headers(picker["id"])
    line_id = get_line_ids(order["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])

    resp = api.pick_order_line(line_id, {}, ph)
    validate_error(resp, ApiErrorId.ERR_INVALID_PICK_QUANTITY.value, 400)


def test_cross_store_slot_reference_rejected(api):
    """PRD §3.2: "the slot, products, and (where applicable) picker must belong to the same store as `store_id`, or the request is rejected with `ERR_CROSS_STORE_REFERENCE` ... "

    Design: Corner/errors/err_cross_store_reference_on_order_place
    """
    s1 = create_store(name="S1")
    s2 = create_store(name="S2")
    customer = create_customer(email="cc19@x.com")
    a = create_product(s1["id"], sku="A", name="A", unit_price_cents=349)
    slot2 = create_slot(s2["id"], capacity=1)

    resp = api.create_order(
        {"store_id": s1["id"], "customer_id": customer["id"], "slot_id": slot2["id"],
         "expected_slot_version": slot2["version"],
         "lines": [{"product_id": a["id"], "requested_qty": 1}]},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_STORE_REFERENCE.value, 409)


def test_add_line_with_discontinued_product_rejected(api):
    """PRD §3.1: "a `DISCONTINUED` product cannot be added to a new line nor proposed as a substitute, and an attempt to do so is rejected with `ERR_PRODUCT_DISCONTINUED`."

    Design: Corner/errors/err_product_discontinued_on_line_add
    """
    store = create_store()
    customer = create_customer(email="cc20@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    b = create_product(store["id"], sku="B", name="B", unit_price_cents=500)
    discontinue_product(a["id"])
    slot = create_slot(store["id"], capacity=5)
    ch = make_customer_headers(customer["id"])
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": b["id"], "requested_qty": 1}])

    resp = api.create_order_line(
        {"order_id": order["id"], "product_id": a["id"], "requested_qty": 1}, ch)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED.value, 409)


def test_place_order_for_suspended_customer_rejected(api):
    """PRD §3.1: "a `SUSPENDED` customer is refused at order placement with `ERR_CUSTOMER_SUSPENDED`."

    Design: Corner/errors/err_customer_suspended_on_order_place
    """
    store = create_store()
    customer = create_customer(email="cc21@x.com", snap_ebt_balance_cents=0)
    suspend_customer(customer["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)

    # StoreOps places on the suspended customer's behalf.
    resp = api.create_order(
        {"store_id": store["id"], "customer_id": customer["id"], "slot_id": slot["id"],
         "expected_slot_version": slot["version"],
         "lines": [{"product_id": a["id"], "requested_qty": 1}]},
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED.value, 409)


def test_place_order_against_closed_store_rejected(api):
    """PRD §3.1: "A `PlatformAdmin` may move a store from `ACTIVE` to `CLOSED`; a `CLOSED` store refuses new orders with `ERR_STORE_CLOSED`."

    Design: Corner/errors/err_store_closed_on_order_place
    """
    store = create_store()
    customer = create_customer(email="cc22@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    close_store(store["id"])

    resp = api.create_order(
        {"store_id": store["id"], "customer_id": customer["id"], "slot_id": slot["id"],
         "expected_slot_version": slot["version"],
         "lines": [{"product_id": a["id"], "requested_qty": 1}]},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STORE_CLOSED.value, 409)


def test_customer_cannot_capture_payment(api):
    """PRD §3.6: "A `StoreOps` operator captures payment on a staged order, advancing `payment_status` from `AUTHORIZED` to `CAPTURED`."
    PRD §2.1: "When the headers are present but the declared role is not permitted to perform the requested operation ... the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/rbac_customer_cannot_capture
    """
    store, customer, picker, product, slot, order, line_id = setup_single_unit_order_staged(
        unit_price_cents=349, picked_qty=1, email="cc25@x.com")
    resp = api.capture_order(order["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_storeops_cannot_claim_order(api):
    """PRD §3.2: "A `Picker` claims a `PLACED` order to begin work, which advances `fulfillment_status` from `PLACED` to `PICKING` and records the acting picker on `picker_id`."
    PRD §2.1: "When the headers are present but the declared role is not permitted to perform the requested operation ... the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/rbac_storeops_cannot_claim_picker_only
    """
    store = create_store()
    customer = create_customer(email="cc26@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": a["id"], "requested_qty": 1}])

    resp = api.claim_order(
        order["id"], {"window_start": "2026-06-15T08:00:00Z",
                      "window_end": "2026-06-15T08:45:00Z"}, OPS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
