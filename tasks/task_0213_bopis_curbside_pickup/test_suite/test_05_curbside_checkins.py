"""Curbside check-in lifecycle, the order-verified gate, and the curbside-space
open-ended overlap.

Difficulty queue A (cross_entity_state_dependency curbside, resource_temporal_overlap
curbside) plus corner side-effect / derived-field / duplicate-checkin claims.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_customer_headers, make_manager_headers,
    factories as f, fixtures as fx,
)


def _checkin(api, order_id, store_id, customer_id, vehicle="car"):
    return validate_success(api.create_curbside_checkin(
        f.create_curbside_checkin_payload(order_id, store_id, vehicle),
        make_customer_headers(customer_id)), expected_status=201)


def test_start_loading_blocked_when_order_unverified(api):
    """PRD §3.6: "A `StoreAssociate` starts loading, moving the check-in from `ARRIVED`
    to `BEING_LOADED`, but only when the parent order is verified (otherwise
    `ERR_ORDER_NOT_VERIFIED`)"

    Design: Difficulty/cross_entity_state_dependency/curbside_loading_depends_on_order_verified
    """
    s = fx.setup_awaiting_pickup_order([{"price": 1000, "qty": 1}], verified=False,
                                       curbside_spaces=3)
    order, customer, store = s["order"], s["customer"], s["store"]
    assert order["verified"] is False, order
    ci = _checkin(api, order["id"], store["id"], customer["id"])
    resp = api.start_loading_checkin(ci["id"], fx.make_associate_headers())
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_VERIFIED.value)


def test_start_loading_succeeds_when_order_verified(api):
    """PRD §3.6: "A `StoreAssociate` starts loading, moving the check-in from `ARRIVED`
    to `BEING_LOADED`, but only when the parent order is verified (otherwise
    `ERR_ORDER_NOT_VERIFIED`); this bumps the check-in's `version`."

    Design: Difficulty/cross_entity_state_dependency/curbside_loading_depends_on_order_verified
    """
    s = fx.setup_awaiting_pickup_order([{"price": 1000, "qty": 1}], verified=True,
                                       curbside_spaces=3)
    order, customer, store = s["order"], s["customer"], s["store"]
    ci = _checkin(api, order["id"], store["id"], customer["id"])
    loading = validate_success(api.start_loading_checkin(ci["id"], fx.make_associate_headers()))
    assert loading["checkin_status"] == "BEING_LOADED", loading


def test_second_concurrent_checkin_blocked_when_curbside_full(api):
    """PRD §3.6: "A check-in is refused with `ERR_CURBSIDE_FULL` when the store's
    `active_curbside_count` is already at or above its `curbside_spaces` capacity"

    Design: Difficulty/resource_temporal_overlap/curbside_space_concurrent_open_ended_overlap
    """
    # curbside_spaces 1; two distinct orders both AWAITING_PICKUP at the same store.
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 10}],
                                 curbside_spaces=1, capacity=5)
    store_id, slot_id, product_id = base["store"]["id"], base["slot"]["id"], base["products"][0]["id"]
    c1 = base["customer"]
    o1 = fx.create_draft_order(c1["id"], store_id)
    fx.add_line(o1["id"], c1["id"], product_id, 1)
    fx.submit_order(o1["id"], c1["id"], slot_id, fx.get_slot_version(slot_id))

    c2 = fx.create_customer()
    o2 = fx.create_draft_order(c2["id"], store_id)
    fx.add_line(o2["id"], c2["id"], product_id, 1)
    fx.submit_order(o2["id"], c2["id"], slot_id, fx.get_slot_version(slot_id))

    _checkin(api, o1["id"], store_id, c1["id"], "car1")  # active_curbside_count -> 1
    resp = api.create_curbside_checkin(
        f.create_curbside_checkin_payload(o2["id"], store_id, "car2"),
        make_customer_headers(c2["id"]))
    validate_error(resp, ApiErrorId.ERR_CURBSIDE_FULL.value)

    store_state = validate_success(api.get_store(store_id, make_manager_headers()))
    assert store_state["active_curbside_count"] == 1, store_state


def test_checkin_raises_active_curbside_count(api):
    """PRD §3.6: "A check-in is created with its `checkin_status` set to `ARRIVED`, and
    creating it raises the store's `active_curbside_count` by one."

    Design: Difficulty/resource_temporal_overlap/curbside_space_concurrent_open_ended_overlap
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 10}],
                                 curbside_spaces=1, capacity=5)
    store_id, slot_id, product_id = base["store"]["id"], base["slot"]["id"], base["products"][0]["id"]
    c1 = base["customer"]
    o1 = fx.create_draft_order(c1["id"], store_id)
    fx.add_line(o1["id"], c1["id"], product_id, 1)
    fx.submit_order(o1["id"], c1["id"], slot_id, fx.get_slot_version(slot_id))
    ci = _checkin(api, o1["id"], store_id, c1["id"], "car1")
    assert ci["checkin_status"] == "ARRIVED", ci
    store_state = validate_success(api.get_store(store_id, make_manager_headers()))
    assert store_state["active_curbside_count"] == 1, store_state


def test_complete_checkin_decrements_active_count(api):
    """PRD §3.6: "The associate completes loading, moving the check-in from
    `BEING_LOADED` to `COMPLETED`, only when the parent order's `fulfillment_status` is
    `COMPLETED` or `PARTIALLY_PICKED_UP`; completion lowers the store's
    `active_curbside_count` by one and bumps the check-in's `version`."

    Design: Corner/state_machines/curbside_complete_decrements_active_count
    """
    s = fx.setup_awaiting_pickup_order([{"price": 1000, "qty": 1}], verified=True,
                                       curbside_spaces=3)
    order, customer, store, lines = s["order"], s["customer"], s["store"], s["lines"]
    ci = _checkin(api, order["id"], store["id"], customer["id"])
    validate_success(api.start_loading_checkin(ci["id"], fx.make_associate_headers()))
    # drive the order to COMPLETED via full pickup so complete is permitted
    validate_success(api.pickup_order(
        order["id"], f.pickup_payload([f.handover(lines[0]["id"], 1)]),
        fx.make_associate_headers()))
    completed = validate_success(api.complete_checkin(ci["id"], fx.make_associate_headers()))
    assert completed["checkin_status"] == "COMPLETED", completed
    store_state = validate_success(api.get_store(store["id"], make_manager_headers()))
    assert store_state["active_curbside_count"] == 0, store_state


def test_cancel_checkin_reconciles_active_count(api):
    """PRD §3.6: "A check-in may also be cancelled from either `ARRIVED` or
    `BEING_LOADED` (by a `StoreAssociate`, or by the owning `Customer`), moving it to
    `CANCELLED`, which likewise lowers `active_curbside_count` by one and bumps its
    `version`."

    Design: Corner/cross_cutting_concerns/derived_active_curbside_count_reconciled_on_cancel
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 5}],
                                 curbside_spaces=3, capacity=5)
    store_id, slot_id, product_id = base["store"]["id"], base["slot"]["id"], base["products"][0]["id"]
    c = base["customer"]
    o = fx.create_draft_order(c["id"], store_id)
    fx.add_line(o["id"], c["id"], product_id, 1)
    fx.submit_order(o["id"], c["id"], slot_id, fx.get_slot_version(slot_id))
    ci = _checkin(api, o["id"], store_id, c["id"])

    before = validate_success(api.get_store(store_id, make_manager_headers()))
    assert before["active_curbside_count"] == 1, before

    cancelled = validate_success(api.cancel_checkin(ci["id"], make_customer_headers(c["id"])))
    assert cancelled["checkin_status"] == "CANCELLED", cancelled
    after = validate_success(api.get_store(store_id, make_manager_headers()))
    assert after["active_curbside_count"] == 0, after


def test_duplicate_active_checkin_rejected(api):
    """PRD §3.6: "refused with `ERR_DUPLICATE_CHECKIN` when the order already has an
    active check-in (one already in `ARRIVED` or `BEING_LOADED`)."

    Design: Corner/validations/duplicate_active_checkin_rejected
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 5}],
                                 curbside_spaces=5, capacity=5)
    store_id, slot_id, product_id = base["store"]["id"], base["slot"]["id"], base["products"][0]["id"]
    c = base["customer"]
    o = fx.create_draft_order(c["id"], store_id)
    fx.add_line(o["id"], c["id"], product_id, 1)
    fx.submit_order(o["id"], c["id"], slot_id, fx.get_slot_version(slot_id))
    _checkin(api, o["id"], store_id, c["id"], "car1")
    resp = api.create_curbside_checkin(
        f.create_curbside_checkin_payload(o["id"], store_id, "car2"),
        make_customer_headers(c["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CHECKIN.value)
