"""Order/OrderLine/Substitution lifecycles, parallel axes, and multi-hop cascades.

Difficulty queue A (non_linear_state_machine, transitive_cascade) plus corner
state_machine transitions and side-effect claims.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_customer_headers, make_manager_headers,
    factories as f, fixtures as fx,
)


# --- non_linear_state_machine: parallel axes -------------------------------

def test_submit_advances_both_fulfillment_and_payment_axes(api):
    """PRD §3.3: "Submission moves the order's `fulfillment_status` from `DRAFT` to
    `SUBMITTED`"
    PRD §3.3: "The order's `authorized_total_cents` is pinned (see Section 3.9) and its
    `payment_status` advances from `UNAUTHORIZED` to `AUTHORIZED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_x_payment_axes
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 5}])
    customer = base["customer"]
    order = fx.create_draft_order(customer["id"], base["store"]["id"])
    fx.add_line(order["id"], customer["id"], base["products"][0]["id"], 1)
    submitted = validate_success(api.submit_order(
        order["id"], f.submit_order_payload(base["slot"]["id"], base["slot_version"]),
        make_customer_headers(customer["id"])))
    assert submitted["fulfillment_status"] == "SUBMITTED", submitted
    assert submitted["payment_status"] == "AUTHORIZED", submitted


def test_full_pickup_advances_both_axes_to_completed_and_captured(api):
    """PRD §3.6: "If the sum of handed-over units equals the sum of all lines'
    `qty_picked`, the order moves from `AWAITING_PICKUP` straight to `COMPLETED`"
    PRD §3.9: "When fulfillment reaches `COMPLETED` with nothing refunded, it moves
    from `AUTHORIZED` to `CAPTURED`"

    Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_x_payment_axes
    """
    s = fx.setup_awaiting_pickup_order([{"price": 1000, "qty": 1}])
    order, lines = s["order"], s["lines"]
    resp = validate_success(api.pickup_order(
        order["id"], f.pickup_payload([f.handover(lines[0]["id"], 1)]),
        fx.make_associate_headers()))
    assert resp["fulfillment_status"] == "COMPLETED", resp
    assert resp["payment_status"] == "CAPTURED", resp


# --- non_linear_state_machine: cyclic OrderLine substitution ---------------

def test_substitution_cycle_propose_decline_repropose(api):
    """PRD §3.5: "A successful proposal creates a `Substitution` with `decision_status`
    `PROPOSED`, moves the line from `SHORT_PICKED` to `SUBSTITUTION_PROPOSED`"
    PRD §3.5: "A decline (by the owning `Customer`) sets the substitution's
    `decision_status` to `DECLINED`; a withdrawal (by a `StorePicker`) sets it to
    `WITHDRAWN`."
    PRD §3.5: "Either way the parent line moves from `SUBSTITUTION_PROPOSED` back to
    `SHORT_PICKED` and the line's `version` bumps."

    Design: Difficulty/non_linear_state_machine/orderline_substitution_cycle_propose_decline_repropose
    """
    s = fx.setup_short_picked_with_proposal(
        original_price=1500, substitute_price=1800, qty=2, substitute_qty=2,
        extra_substitute_groups=[{"price": 1600}])
    customer, line = s["customer"], s["line"]
    sub1 = s["substitution"]

    declined = validate_success(api.decline_substitution(sub1["id"], make_customer_headers(customer["id"])))
    assert declined["decision_status"] == "DECLINED", declined

    line_back = validate_success(api.get_order_line(line["id"], fx.make_picker_headers()))
    assert line_back["line_status"] == "SHORT_PICKED", line_back

    # re-propose a fresh substitute (extra product D, group BREAD)
    sub2 = validate_success(api.create_substitution(
        f.create_substitution_payload(line["id"], s["extra_products"][0]["id"], 2),
        fx.make_picker_headers()), expected_status=201)
    assert sub2["decision_status"] == "PROPOSED", sub2

    line_again = validate_success(api.get_order_line(line["id"], fx.make_picker_headers()))
    assert line_again["line_status"] == "SUBSTITUTION_PROPOSED", line_again


def test_substitution_decline_returns_proposed_status_and_reopens_line(api):
    """PRD §3.5: "The customer may instead decline, and the picker may instead
    withdraw; both return the line to `SHORT_PICKED` so a fresh substitute may be
    proposed."

    Design: Difficulty/non_linear_state_machine/orderline_substitution_cycle_propose_decline_repropose
    """
    s = fx.setup_short_picked_with_proposal()
    customer, line, sub = s["customer"], s["line"], s["substitution"]
    declined = validate_success(api.decline_substitution(sub["id"], make_customer_headers(customer["id"])))
    assert declined["decision_status"] == "DECLINED"
    reopened = validate_success(api.get_order_line(line["id"], fx.make_picker_headers()))
    assert reopened["line_status"] == "SHORT_PICKED"


# --- transitive_cascade: expire -> hold -> strike -> standing --------------

def test_expire_cascades_to_hold_strike_and_standing(api):
    """PRD §3.7: "Expiry transitions the order's `fulfillment_status` from
    `AWAITING_PICKUP` to `EXPIRED`"
    PRD §3.7: "The order's hold moves to `EXPIRED`."
    PRD §3.7: "The owning customer's `no_show_strikes` rises by one and their
    `pickup_standing` is recomputed against the thresholds in Section 2.9."
    PRD §2.9: "at exactly 2 strikes the standing is `WATCH`"

    Design: Difficulty/transitive_cascade/expire_to_hold_to_customer_strike_to_standing
    """
    # First push customer to exactly 1 strike, then expire a second order -> 2 strikes.
    setup = fx.raise_customer_to_strikes(1, hold_window_minutes=120)
    customer = setup["customer"]
    assert customer["no_show_strikes"] == 1, customer

    store, product, slot = setup["store"], setup["product"], setup["slot"]
    fx.set_clock("2026-06-05T10:00:00Z")
    slot_v = fx.get_slot_version(slot["id"])
    order = fx.create_draft_order(customer["id"], store["id"])
    line = fx.add_line(order["id"], customer["id"], product["id"], 1)
    fx.submit_order(order["id"], customer["id"], slot["id"], slot_v)
    fx.start_picking(order["id"])
    fx.pick_line(line["id"], 1)
    fx.stage_order(order["id"])
    fx.ready_order(order["id"])
    fx.set_clock("2026-06-05T12:00:00Z")  # >= staged_at + 120 min

    expired = validate_success(api.expire_order(order["id"], make_manager_headers()))
    assert expired["fulfillment_status"] == "EXPIRED", expired

    holds = validate_success(api.list_order_holds(order["id"], make_manager_headers()))
    holds_list = holds if isinstance(holds, list) else holds
    assert holds_list[0]["hold_status"] == "EXPIRED", holds_list

    cust_after = validate_success(api.get_customer(customer["id"], make_manager_headers()))
    assert cust_after["no_show_strikes"] == 2, cust_after
    assert cust_after["pickup_standing"] == "WATCH", cust_after


def test_expire_full_refunds_order(api):
    """PRD §3.7: "The order's `refunded_total_cents` is set to the full
    `authorized_total_cents` and the `payment_status` becomes `REFUNDED`."

    Design: Difficulty/transitive_cascade/expire_to_hold_to_customer_strike_to_standing
    """
    setup = fx.raise_customer_to_strikes(0, hold_window_minutes=120)
    customer, store, product, slot = setup["customer"], setup["store"], setup["product"], setup["slot"]
    fx.set_clock("2026-06-05T10:00:00Z")
    slot_v = fx.get_slot_version(slot["id"])
    order = fx.create_draft_order(customer["id"], store["id"])
    line = fx.add_line(order["id"], customer["id"], product["id"], 1)
    submitted = fx.submit_order(order["id"], customer["id"], slot["id"], slot_v)
    auth = submitted["authorized_total_cents"]
    fx.start_picking(order["id"])
    fx.pick_line(line["id"], 1)
    fx.stage_order(order["id"])
    fx.ready_order(order["id"])
    fx.set_clock("2026-06-05T12:00:00Z")
    expired = validate_success(api.expire_order(order["id"], make_manager_headers()))
    assert expired["refunded_total_cents"] == auth, expired
    assert expired["payment_status"] == "REFUNDED", expired


# --- transitive_cascade: accept -> line SUBSTITUTED -> reserve + reauth -----

def test_substitution_accept_cascades_to_line_and_inventory_and_authorization(api):
    """PRD §3.5: "The acting `Customer` may accept, moving the substitution from
    `PROPOSED` to `ACCEPTED`"
    PRD §3.5: "On acceptance, the `price_delta_cents` is computed and pinned (see
    Section 3.9), the substitute inventory is reserved (its `reserved` rises by
    `substitute_qty`, a `RESERVE` movement is appended, and `available` is recomputed),
    the line moves from `SUBSTITUTION_PROPOSED` to `SUBSTITUTED` (its already-picked
    units plus the substitute units are treated as picked for staging), the order's
    `authorized_total_cents` rises by the `price_delta_cents` to re-authorize the
    difference, and both the order's `version` and the line's `version` increment."

    Design: Difficulty/transitive_cascade/substitution_accept_to_orderline_to_inventory_reserve
    """
    s = fx.setup_short_picked_with_proposal(
        original_price=1500, substitute_price=1800, qty=2, substitute_qty=2)
    customer, line, sub = s["customer"], s["line"], s["substitution"]
    inv_b = s["substitute_inventory"]

    accepted = validate_success(api.accept_substitution(sub["id"], make_customer_headers(customer["id"])))
    assert accepted["decision_status"] == "ACCEPTED", accepted
    assert accepted["price_delta_cents"] == 600, accepted

    line_after = validate_success(api.get_order_line(line["id"], fx.make_picker_headers()))
    assert line_after["line_status"] == "SUBSTITUTED", line_after

    inv_after = validate_success(api.get_store_inventory(inv_b["id"], make_manager_headers()))
    assert inv_after["reserved"] == 2, inv_after
    assert inv_after["available"] == 3, inv_after  # on_hand 5 - reserved 2

    order_after = validate_success(api.get_order(s["order"]["id"], make_manager_headers()))
    assert order_after["authorized_total_cents"] == 3600, order_after  # 3000 + 600


def test_substitution_accept_sets_line_substituted(api):
    """PRD §3.5: "the line moves from `SUBSTITUTION_PROPOSED` to `SUBSTITUTED` (its
    already-picked units plus the substitute units are treated as picked for staging)"

    Design: Difficulty/transitive_cascade/substitution_accept_to_orderline_to_inventory_reserve
    """
    s = fx.setup_short_picked_with_proposal()
    customer, line, sub = s["customer"], s["line"], s["substitution"]
    validate_success(api.accept_substitution(sub["id"], make_customer_headers(customer["id"])))
    line_after = validate_success(api.get_order_line(line["id"], fx.make_picker_headers()))
    assert line_after["line_status"] == "SUBSTITUTED"


# --- Corner: state-machine transitions -------------------------------------

def test_start_picking_from_draft_rejected(api):
    """PRD §3.4: "Once an order is `SUBMITTED`, a `StorePicker` begins picking,
    advancing the order's `fulfillment_status` from `SUBMITTED` to `PICKING`; this
    simply requires the order to currently be `SUBMITTED`"
    PRD §2.12: "the state guard — that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/start_picking_from_draft_returns_invalid_state
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 5}])
    customer = base["customer"]
    order = fx.create_draft_order(customer["id"], base["store"]["id"])
    resp = api.start_picking(order["id"], fx.make_picker_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_stage_with_reserved_line_rejected(api):
    """PRD §3.4: "This is permitted only when every order line is in one of the
    staging-terminal states `PICKED`, `SUBSTITUTED`, or `NOT_FULFILLED` — that is, no
    line is still `PENDING`, `RESERVED`, `SHORT_PICKED`, or `SUBSTITUTION_PROPOSED` —
    and at least one line is `PICKED` or `SUBSTITUTED` so that an entirely-unfulfilled
    order cannot be staged."
    PRD §3.4: "A staging attempt that violates either condition is rejected with
    `ERR_STAGE_NOT_READY`."

    Design: Corner/state_machines/stage_with_pending_line_returns_stage_not_ready
    """
    s = fx.setup_picking_order([{"price": 1000, "qty": 2}])
    resp = api.stage_order(s["order"]["id"], fx.make_picker_headers())
    validate_error(resp, ApiErrorId.ERR_STAGE_NOT_READY.value)


def test_cancel_completed_order_rejected(api):
    """PRD §3.8: "A `Customer` may cancel their own order while it is `DRAFT` or
    `SUBMITTED`; a `StoreManager` may cancel an order while it is `PICKING`."
    PRD §2.12: "the state guard — that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/cancel_completed_order_terminal_lockdown
    """
    s = fx.setup_awaiting_pickup_order([{"price": 1000, "qty": 1}])
    order, lines, customer = s["order"], s["lines"], s["customer"]
    completed = validate_success(api.pickup_order(
        order["id"], f.pickup_payload([f.handover(lines[0]["id"], 1)]),
        fx.make_associate_headers()))
    assert completed["fulfillment_status"] == "COMPLETED"
    resp = api.cancel_order(order["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_submit_twice_second_rejected_invalid_state(api):
    """PRD §3.3: "Submission moves the order's `fulfillment_status` from `DRAFT` to
    `SUBMITTED` and is permitted only when every one of the following holds"
    PRD §2.12: "the state guard — that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/submit_twice_idempotency_second_invalid_state
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 5}])
    customer = base["customer"]
    order = fx.create_draft_order(customer["id"], base["store"]["id"])
    fx.add_line(order["id"], customer["id"], base["products"][0]["id"], 1)
    fx.submit_order(order["id"], customer["id"], base["slot"]["id"], base["slot_version"])
    cur_v = fx.get_slot_version(base["slot"]["id"])
    resp = api.submit_order(
        order["id"], f.submit_order_payload(base["slot"]["id"], cur_v),
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_abandon_short_line_to_not_fulfilled(api):
    """PRD §3.4: "If nothing at all was picked for it — `qty_picked` equal to zero — a
    `StorePicker` may abandon it, releasing the residual reservation (the inventory's
    `reserved` falls by `qty_reserved`, `qty_reserved` becomes zero, `available` is
    recomputed, a `RELEASE` movement is appended), moving the line from `SHORT_PICKED`
    to `NOT_FULFILLED`"

    Design: Corner/state_machines/abandon_short_line_to_not_fulfilled
    """
    s = fx.setup_picking_order([{"price": 1000, "qty": 2}], on_hand=5)
    order, lines, inv = s["order"], s["lines"], s["inventories"][0]
    fx.pick_line(lines[0]["id"], 0)  # short pick to 0 -> SHORT_PICKED
    abandoned = validate_success(api.abandon_line(lines[0]["id"], fx.make_picker_headers()))
    assert abandoned["line_status"] == "NOT_FULFILLED", abandoned
    inv_after = validate_success(api.get_store_inventory(inv["id"], make_manager_headers()))
    assert inv_after["reserved"] == 0, inv_after
    assert inv_after["available"] == 5, inv_after


def test_substitution_withdraw_returns_line_to_short_picked(api):
    """PRD §3.5: "a withdrawal (by a `StorePicker`) sets it to `WITHDRAWN`. Either way
    the parent line moves from `SUBSTITUTION_PROPOSED` back to `SHORT_PICKED` and the
    line's `version` bumps."

    Design: Corner/state_machines/substitution_withdraw_returns_line_to_short_picked
    """
    s = fx.setup_short_picked_with_proposal()
    line, sub = s["line"], s["substitution"]
    withdrawn = validate_success(api.withdraw_substitution(sub["id"], fx.make_picker_headers()))
    assert withdrawn["decision_status"] == "WITHDRAWN", withdrawn
    line_after = validate_success(api.get_order_line(line["id"], fx.make_picker_headers()))
    assert line_after["line_status"] == "SHORT_PICKED", line_after
