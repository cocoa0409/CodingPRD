"""Provisioning and entity-shape tests (corner queue B).

Covers store/product/order creation defaults, required fields, computed fields,
not-found, Refund immutability, plus order/slot initial-state and idempotency rules.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_store,
    assert_product,
    assert_order,
    assert_refund_has_no_version_fields,
    TEST_USERS,
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
    capture_order,
    handoff_order,
    close_slot,
    ADMIN,
    OPS,
)


def test_create_store_returns_system_fields_and_defaults(api):
    """PRD §3.1: "A store is created with a `name`, an optional `timezone` ... an optional `ebt_enabled` flag that defaults to true and declares whether the store accepts SNAP/EBT tender, and an optional `cold_chain_hold_minutes` value that defaults to 120 ... A store begins life `ACTIVE`."
    PRD §2.4: "version` starts at the resource's creation value and increments by one on every mutation. The `"

    Design: Corner/entities/entity_store_create_returns_system_fields
    """
    resp = api.create_store({"name": "FreshMart"}, ADMIN)
    data = validate_success(resp, 201)
    assert_store(data)
    assert data["status"] == "ACTIVE"
    assert data["ebt_enabled"] is True
    assert data["cold_chain_hold_minutes"] == 120
    assert data["version"] == 1


def test_create_product_missing_pricing_mode_rejected(api):
    """PRD §3.1: "Products live in a store's catalog and are created with the store's `store_id`, a `sku` (unique within the store), a display `name`, a `pricing_mode`, a `unit_price_cents`, and a handful of optional flags."
    PRD §2.10: "Malformed bodies, missing required fields, and invalid enum or type values surface as `ERR_VALIDATION`."

    Design: Corner/entities/entity_product_missing_required_field
    """
    store = create_store()
    resp = api.create_product(
        {"store_id": store["id"], "sku": "X", "name": "X", "unit_price_cents": 100},
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)


def test_create_product_default_flags_applied(api):
    """PRD §3.1: "The optional flags are `ebt_eligible` (defaults to false; whether the product may be paid with SNAP/EBT), `age_restricted` (defaults to false; whether sale requires an adult age verification at handoff), `cold_chain` (defaults to false; whether the product is a perishable subject to the staged-hold window) ... "

    Design: Corner/entities/entity_product_default_flags_applied
    """
    store = create_store()
    resp = api.create_product(
        {"store_id": store["id"], "sku": "MILK", "name": "Milk",
         "pricing_mode": "UNIT", "unit_price_cents": 349},
        OPS,
    )
    data = validate_success(resp, 201)
    assert_product(data)
    assert data["ebt_eligible"] is False
    assert data["age_restricted"] is False
    assert data["cold_chain"] is False


def test_order_estimated_total_is_server_computed(api):
    """PRD §3.5: "The `estimated_total_cents` is the sum of `estimated_line_cents` over all of the order's lines, plus the order's `tip_cents`. The `estimated_ebt_eligible_cents` is the sum of `estimated_line_cents` over only those lines whose product is `ebt_eligible`, and it excludes the tip."

    Design: Corner/entities/entity_order_computed_estimated_total_ignores_client_input
    """
    store = create_store()
    customer = create_customer(email="cc1@x.com")
    product = create_product(store["id"], unit_price_cents=349)  # ebt_eligible default false
    slot = create_slot(store["id"], capacity=1)
    resp = api.create_order(
        {"store_id": store["id"], "customer_id": customer["id"], "slot_id": slot["id"],
         "expected_slot_version": slot["version"], "tip_cents": 100,
         "lines": [{"product_id": product["id"], "requested_qty": 2}]},
        make_customer_headers(customer["id"]),
    )
    data = validate_success(resp, 201)
    assert_order(data)
    assert data["estimated_total_cents"] == 798, "349*2 + tip 100"
    assert data["estimated_ebt_eligible_cents"] == 0, "product not ebt_eligible -> 0"


def test_get_order_unknown_id_not_found(api):
    """PRD §2.7: "a path identifier that does not correspond to an existing resource yields the matching not-found error ... ERR_ORDER_NOT_FOUND` for an unknown order, ` ... "

    Design: Corner/entities/entity_order_not_found
    """
    resp = api.get_order(NON_EXISTENT_UUID, OPS)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)


def test_refund_record_has_no_version_field(api):
    """PRD §2.4: "The single exception is the `Refund` resource: a refund is an append-only event record that carries only `id` and `created_at` — it has no `updated_at` and no `version`, because once written it is never modified."

    Design: Corner/entities/entity_refund_immutable_no_version
    """
    # Drive a post-capture out-of-stock to produce one Refund, then read it back.
    store = create_store()
    customer = create_customer(email="cc-ref@x.com", snap_ebt_balance_cents=0)
    picker = create_picker(store["id"])
    product = create_product(store["id"], unit_price_cents=698)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": product["id"], "requested_qty": 1}])
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"])
    pick_line(line_id, picker["id"], picked_qty=1)
    stage_order(order["id"], picker["id"])
    capture_order(order["id"])
    api.out_of_stock_order_line(line_id, OPS)

    data, _meta = validate_paginated(api.list_refunds(OPS, params={"order_id": order["id"]}))
    assert len(data) == 1, "exactly one Refund created"
    assert_refund_has_no_version_fields(data[0])


def test_order_initial_states_placed_and_authorized(api):
    """PRD §3.2: "On success the server creates one `OrderLine` per entry in `lines` ... sets `fulfillment_status` to `PLACED` and `payment_status` to `AUTHORIZED` ... "

    Design: Corner/state_machines/sm_order_initial_states
    """
    store = create_store()
    customer = create_customer(email="cc2@x.com")
    product = create_product(store["id"], unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": product["id"], "requested_qty": 1}])
    assert order["fulfillment_status"] == "PLACED"
    assert order["payment_status"] == "AUTHORIZED"


def test_handoff_from_placed_rejected(api):
    """PRD §3.7: "A `StoreOps` operator hands off a staged, captured order, advancing `fulfillment_status` from `STAGED` to `HANDED_OFF`. Handoff requires the order to be `STAGED` (otherwise `ERR_ORDER_NOT_STAGED`) ... "

    Design: Corner/state_machines/sm_order_handoff_from_placed_invalid
    """
    store = create_store()
    customer = create_customer(email="cc3@x.com")
    product = create_product(store["id"], unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": product["id"], "requested_qty": 1}])
    resp = api.handoff_order(order["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_STAGED.value, 409)
    after = validate_success(api.get_order(order["id"], OPS))
    assert after["fulfillment_status"] == "PLACED"


def test_cancel_handed_off_order_rejected(api):
    """PRD §3.8: "an order that is already `HANDED_OFF` cannot be cancelled and the attempt is rejected with `ERR_ORDER_ALREADY_HANDED_OFF`."

    Design: Corner/state_machines/sm_order_cancel_after_handoff_terminal_lockdown
    """
    set_clock("2026-06-15T09:30:00Z")
    store = create_store()
    customer = create_customer(email="cc4@x.com")
    picker = create_picker(store["id"])
    product = create_product(store["id"], unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": product["id"], "requested_qty": 1}])
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"])
    pick_line(line_id, picker["id"], picked_qty=1)
    stage_order(order["id"], picker["id"])
    capture_order(order["id"])
    handoff_order(order["id"])

    resp = api.cancel_order(order["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_ORDER_ALREADY_HANDED_OFF.value, 409)
    after = validate_success(api.get_order(order["id"], OPS))
    assert after["fulfillment_status"] == "HANDED_OFF"

# SKIPPED Corner/state_machines/sm_slot_close_idempotent_second_close:
# PRD §3.1/§5 tie ERR_SLOT_CLOSED only to refusing new placements on a CLOSED slot.
# The PRD never states which error a SECOND close call returns, so two PRD-only
# implementers could ship different-but-faithful behaviour (generic invalid-state,
# idempotent 200, or ERR_SLOT_CLOSED). Fails unique-derivability — gap left as gap.
