"""Line resolution branches and substitution decisions.

Difficulty queue A: OrderLine branching outcomes, substitution-accept depth-2
cascade. Corner queue B: substitution reject keeps line pending, double-accept,
price ceiling, no-substitution policy, pick on already-picked line.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    assert_order_line,
    assert_substitution,
    make_customer_headers,
    make_picker_headers,
    create_store,
    create_customer,
    create_picker,
    create_product,
    create_slot,
    place_order,
    get_line_ids,
    claim_order,
    pick_line,
    ADMIN,
    OPS,
)


def _order_picking_with_products(email, lines, products):
    """Provision store/customer/picker + given products, place order with `lines`,
    claim into PICKING. Returns (store, customer, picker, order)."""
    store = create_store(ebt_enabled=True)
    customer = create_customer(email=email)
    picker = create_picker(store["id"])
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"], lines)
    claim_order(order["id"], picker["id"])
    return store, customer, picker, order


def test_orderline_branching_substituted_vs_out_of_stock(api):
    """PRD §3.3: "Accepting a substitution advances it from `PROPOSED` to `ACCEPTED` and advances the parent line from `PENDING` to `SUBSTITUTED`, copying the substitution's `substitute_line_cents` onto the line's `final_line_cents`."
    PRD §3.3: "This pre-capture out-of-stock simply sets the line's `final_line_cents` to 0 so that the line contributes nothing to the final total at stage ... "

    Design: Difficulty/non_linear_state_machine/nlsm_orderline_branching_outcomes
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c6@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    b = create_product(store["id"], sku="B", name="B", unit_price_cents=500)
    sub = create_product(store["id"], sku="SUB", name="Sub", unit_price_cents=300)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": a["id"], "requested_qty": 1, "substitution_policy": "SHOPPER_CHOICE"},
         {"product_id": b["id"], "requested_qty": 1, "substitution_policy": "NO_SUBSTITUTION"}],
    )
    ph = make_picker_headers(picker["id"])
    a_line = get_line_ids(order["id"], product_id=a["id"], headers=ph)[0]
    b_line = get_line_ids(order["id"], product_id=b["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])
    sub_rec = validate_success(
        api.create_substitution(
            {"order_line_id": a_line, "substitute_product_id": sub["id"], "substitute_qty": 1}, ph),
        201,
    )

    validate_success(api.accept_substitution(sub_rec["id"], ph))
    validate_success(api.out_of_stock_order_line(b_line, ph))

    a_after = validate_success(api.get_order_line(a_line, ph))
    b_after = validate_success(api.get_order_line(b_line, ph))
    assert a_after["status"] == "SUBSTITUTED"
    assert a_after["final_line_cents"] == 300, "substitute final"
    assert b_after["status"] == "OUT_OF_STOCK"
    assert b_after["final_line_cents"] == 0


def test_orderline_branching_picked_vs_out_of_stock(api):
    """PRD §3.3: "Picking recomputes the line's `final_line_cents` from the recorded `picked_qty` or `actual_weight_kg`."
    PRD §3.3: "This pre-capture out-of-stock simply sets the line's `final_line_cents` to 0 so that the line contributes nothing to the final total at stage ... "

    Design: Difficulty/non_linear_state_machine/nlsm_orderline_branching_outcomes
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c6b@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    b = create_product(store["id"], sku="B", name="B", unit_price_cents=500)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": a["id"], "requested_qty": 2},
         {"product_id": b["id"], "requested_qty": 1}],
    )
    ph = make_picker_headers(picker["id"])
    a_line = get_line_ids(order["id"], product_id=a["id"], headers=ph)[0]
    b_line = get_line_ids(order["id"], product_id=b["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])
    pick_line(a_line, picker["id"], picked_qty=2)
    validate_success(api.out_of_stock_order_line(b_line, ph))

    a_after = validate_success(api.get_order_line(a_line, ph))
    b_after = validate_success(api.get_order_line(b_line, ph))
    assert a_after["status"] == "PICKED"
    assert a_after["final_line_cents"] == 698, "349 * 2"
    assert b_after["status"] == "OUT_OF_STOCK"
    assert b_after["final_line_cents"] == 0


def test_substitution_accept_depth2_cascade(api):
    """PRD §3.3: "A substitution is then decided by a `Customer` or a `Picker`. Accepting a substitution advances it from `PROPOSED` to `ACCEPTED` and advances the parent line from `PENDING` to `SUBSTITUTED`, copying the substitution's `substitute_line_cents` onto the line's `final_line_cents`."

    Design: Difficulty/transitive_cascade/tc_substitution_accept_depth2
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c8@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    sub = create_product(store["id"], sku="SUB", name="Sub", unit_price_cents=250)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": a["id"], "requested_qty": 1, "substitution_policy": "SHOPPER_CHOICE"}],
    )
    ph = make_picker_headers(picker["id"])
    ch = make_customer_headers(customer["id"])
    a_line = get_line_ids(order["id"], product_id=a["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])
    sub_rec = validate_success(
        api.create_substitution(
            {"order_line_id": a_line, "substitute_product_id": sub["id"], "substitute_qty": 1}, ph),
        201,
    )
    assert sub_rec["substitute_line_cents"] == 250

    resp = api.accept_substitution(sub_rec["id"], ch)  # Customer decides
    data = validate_success(resp)
    assert_substitution(data)
    assert data["status"] == "ACCEPTED"

    line_after = validate_success(api.get_order_line(a_line, ch))
    assert line_after["status"] == "SUBSTITUTED"
    assert line_after["final_line_cents"] == 250, "copied from substitute_line_cents"


def test_weight_substitute_line_cents_copied_to_line_on_accept(api):
    """PRD §3.3: "Proposing computes the substitute's `substitute_line_cents` using the same per-line charge rule that produces `final_line_cents`, applied to the substitute product ... "
    PRD §3.3: "Accepting a substitution advances it from `PROPOSED` to `ACCEPTED` and advances the parent line from `PENDING` to `SUBSTITUTED`, copying the substitution's `substitute_line_cents` onto the line's `final_line_cents`."

    Design: Difficulty/transitive_cascade/tc_substitution_accept_depth2
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c8b@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    # WEIGHT substitute: 200 c/kg * 1.50 kg = 300, round_half_up -> 300.
    sub = create_product(store["id"], sku="SUB", name="Sub",
                         pricing_mode="WEIGHT", unit_price_cents=200)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": a["id"], "requested_qty": 1, "substitution_policy": "SHOPPER_CHOICE"}],
    )
    ph = make_picker_headers(picker["id"])
    a_line = get_line_ids(order["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])
    sub_rec = validate_success(
        api.create_substitution(
            {"order_line_id": a_line, "substitute_product_id": sub["id"],
             "substitute_qty": 1, "substitute_weight_kg": 1.50}, ph),
        201,
    )
    assert sub_rec["substitute_line_cents"] == 300, "round_half_up(200 * 1.50)"

    validate_success(api.accept_substitution(sub_rec["id"], ph))
    line_after = validate_success(api.get_order_line(a_line, ph))
    assert line_after["status"] == "SUBSTITUTED"
    assert line_after["final_line_cents"] == 300, "copied from substitute_line_cents"


def test_substitution_reject_leaves_line_pending(api):
    """PRD §3.3: "Rejecting a substitution advances it from `PROPOSED` to `REJECTED` and requires only that it was still `PROPOSED` (otherwise `ERR_SUBSTITUTION_NOT_PROPOSED`); a rejection leaves the parent line untouched and still `PENDING`, so it remains pickable or markable out of stock."

    Design: Corner/state_machines/sm_substitution_reject_keeps_line_pending
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="cc5@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    sub = create_product(store["id"], sku="SUB", name="Sub", unit_price_cents=250)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": a["id"], "requested_qty": 1, "substitution_policy": "SHOPPER_CHOICE"}],
    )
    ph = make_picker_headers(picker["id"])
    ch = make_customer_headers(customer["id"])
    a_line = get_line_ids(order["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])
    sub_rec = validate_success(
        api.create_substitution(
            {"order_line_id": a_line, "substitute_product_id": sub["id"], "substitute_qty": 1}, ph),
        201,
    )
    data = validate_success(api.reject_substitution(sub_rec["id"], ch))
    assert data["status"] == "REJECTED"
    line_after = validate_success(api.get_order_line(a_line, ph))
    assert line_after["status"] == "PENDING"


def test_substitution_price_exceeded_same_price_or_less(api):
    """PRD §3.3: "when the policy is `SAME_PRICE_OR_LESS`, the substitute's `substitute_line_cents` must be less than or equal to the line's `estimated_line_cents`, or the acceptance is rejected with `ERR_SUBSTITUTION_PRICE_EXCEEDED`."

    Design: Corner/validations/val_substitution_price_exceeded_same_price_or_less
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="cc14@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    sub = create_product(store["id"], sku="SUB", name="Sub", unit_price_cents=500)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": a["id"], "requested_qty": 1, "substitution_policy": "SAME_PRICE_OR_LESS"}],
    )
    ph = make_picker_headers(picker["id"])
    a_line = get_line_ids(order["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])
    sub_rec = validate_success(
        api.create_substitution(
            {"order_line_id": a_line, "substitute_product_id": sub["id"], "substitute_qty": 1}, ph),
        201,
    )
    resp = api.accept_substitution(sub_rec["id"], ph)
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_PRICE_EXCEEDED.value, 409)


def test_substitution_not_allowed_on_no_substitution_line(api):
    """PRD §3.3: "Acceptance requires ... that the line's `substitution_policy` is not `NO_SUBSTITUTION` (otherwise `ERR_SUBSTITUTION_NOT_ALLOWED`) ... "

    Design: Corner/validations/val_substitution_not_allowed_no_substitution_policy
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="cc15@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    sub = create_product(store["id"], sku="SUB", name="Sub", unit_price_cents=250)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": a["id"], "requested_qty": 1, "substitution_policy": "NO_SUBSTITUTION"}],
    )
    ph = make_picker_headers(picker["id"])
    a_line = get_line_ids(order["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])
    sub_rec = validate_success(
        api.create_substitution(
            {"order_line_id": a_line, "substitute_product_id": sub["id"], "substitute_qty": 1}, ph),
        201,
    )
    resp = api.accept_substitution(sub_rec["id"], ph)
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_NOT_ALLOWED.value, 409)


def test_double_accept_substitution_not_proposed(api):
    """PRD §3.3: "Acceptance requires that the substitution is still `PROPOSED` (otherwise `ERR_SUBSTITUTION_NOT_PROPOSED`) ... "

    Design: Corner/errors/err_substitution_not_proposed_double_accept
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="cc24@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    sub = create_product(store["id"], sku="SUB", name="Sub", unit_price_cents=250)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": a["id"], "requested_qty": 1, "substitution_policy": "SHOPPER_CHOICE"}],
    )
    ph = make_picker_headers(picker["id"])
    a_line = get_line_ids(order["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])
    sub_rec = validate_success(
        api.create_substitution(
            {"order_line_id": a_line, "substitute_product_id": sub["id"], "substitute_qty": 1}, ph),
        201,
    )
    validate_success(api.accept_substitution(sub_rec["id"], ph))
    resp = api.accept_substitution(sub_rec["id"], ph)
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_NOT_PROPOSED.value, 409)


def test_pick_already_picked_line_rejected(api):
    """PRD §3.3: "A pick attempted on a line that is not `PENDING` is rejected with `ERR_LINE_NOT_PENDING` ... "

    Design: Corner/state_machines/sm_line_pick_when_already_picked_invalid
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="cc8@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": a["id"], "requested_qty": 1}])
    ph = make_picker_headers(picker["id"])
    line_id = get_line_ids(order["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])
    pick_line(line_id, picker["id"], picked_qty=1)
    resp = api.pick_order_line(line_id, {"picked_qty": 1}, ph)
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_PENDING.value, 409)
