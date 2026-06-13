"""Order, RewardGrant, and Member state-machine behavior.

Queue A (Difficulty): non_linear_state_machine.
Queue B (Corner): state_machines section.
"""
from test_helpers import (
    fixtures as fx,
    factories as f,
    validate_success,
    validate_error,
    ApiErrorId,
)

ERR = ApiErrorId


# ─── non_linear_state_machine ─────────────────────────────────────────────

def test_reward_cycles_reserved_redeemed_back_to_issued_on_cancel(api):
    """PRD §3.8: "If the order had a redeemed reward, that reward is restored to
    `ISSUED` when its `expires_at` is still after the current time, or to `EXPIRED`
    when its `expires_at` is at or before the current time, and in either case its
    `reserved_by_order_id` is cleared to null. This restoration is the cyclic edge of
    the reward lifecycle: a `RESERVED` or `REDEEMED` reward returns to `ISSUED` so the
    member can reuse it."

    A FREE_ITEM reward is reserved at pay, redeemed at place, then the order is
    cancelled while still within the reward's validity -> reward returns to ISSUED
    with reserved_by_order_id cleared.

    Design: Difficulty/non_linear_state_machine/rewardgrant_cyclic_reserved_back_to_issued
    """
    ctx = fx.setup_member_with_free_item_reward(num_slots=4)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    reward = ctx["reward"]
    # Order applies the reward, pay (RESERVED), place (REDEEMED).
    order = fx.create_cart_order(mid, store_id, ctx["slots"][1]["id"],
                                 applied_reward_id=reward["id"])
    fx.add_line(mid, order["id"], ctx["item"]["id"], quantity=1)
    fx.pay(mid, order["id"], "EXTERNAL_CARD")
    slot = api.get_pickup_slot(ctx["slots"][1]["id"], hdr).json()["data"]
    placed = fx.place(mid, order["id"], slot["version"])
    redeemed = validate_success(api.get_reward(reward["id"], hdr))
    assert redeemed["status"] == "REDEEMED", redeemed

    # Cancel the PLACED order -> reward restored to ISSUED.
    cancelled = validate_success(api.cancel_order(mid, order["id"], hdr))
    assert cancelled["fulfillment_status"] == "CANCELLED", cancelled
    restored = validate_success(api.get_reward(reward["id"], hdr))
    assert restored["status"] == "ISSUED", restored
    assert restored["reserved_by_order_id"] is None, restored


def test_reward_reserved_at_pay(api):
    """PRD §3.5: "If the order carries an `applied_reward_id`, the reward is reserved
    at this point: its `status` moves from `ISSUED` to `RESERVED` and its
    `reserved_by_order_id` is set to the order."

    Paying an order that applies an ISSUED FREE_ITEM reward moves the reward to
    RESERVED and stamps reserved_by_order_id with the order id.

    Design: Difficulty/non_linear_state_machine/rewardgrant_cyclic_reserved_back_to_issued
    """
    ctx = fx.setup_member_with_free_item_reward(num_slots=3)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    reward = ctx["reward"]
    order = fx.create_cart_order(mid, store_id, ctx["slots"][1]["id"],
                                 applied_reward_id=reward["id"])
    fx.add_line(mid, order["id"], ctx["item"]["id"], quantity=1)
    fx.pay(mid, order["id"], "EXTERNAL_CARD")
    reserved = validate_success(api.get_reward(reward["id"], hdr))
    assert reserved["status"] == "RESERVED", reserved
    assert reserved["reserved_by_order_id"] == order["id"], reserved


def test_order_payment_and_fulfillment_axes_independent(api):
    """PRD §3.5: "a successful pay then sets the order's `pay_method`, advances
    `payment_status` from `UNPAID` to `PAID`".
    PRD §3.6: "A successful place advances `fulfillment_status` from `CART` to
    `PLACED`".

    After pay: payment_status PAID while fulfillment_status is still CART.
    After place: fulfillment_status PLACED while payment_status remains PAID.

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
    """
    ctx = fx.setup_cart_order_with_line(item_price=615)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    slot = ctx["slot"]
    paid = validate_success(api.pay_order(mid, ctx["order"]["id"],
                                          f.pay_payload("EXTERNAL_CARD"), hdr))
    assert paid["payment_status"] == "PAID", paid
    assert paid["fulfillment_status"] == "CART", paid

    placed = validate_success(api.place_order(
        mid, ctx["order"]["id"], f.place_payload(slot["version"]), hdr))
    assert placed["fulfillment_status"] == "PLACED", placed
    assert placed["payment_status"] == "PAID", placed


def test_pay_advances_payment_status_to_paid(api):
    """PRD §3.5: "A successful pay then sets the order's `pay_method`, advances
    `payment_status` from `UNPAID` to `PAID`".

    A second, independent assertion of the parallel-axis instance: pay alone flips
    payment_status to PAID and records the pay_method, leaving fulfillment at CART.

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
    """
    ctx = fx.setup_cart_order_with_line(item_price=615)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    paid = validate_success(api.pay_order(mid, ctx["order"]["id"],
                                          f.pay_payload("EXTERNAL_CARD"), hdr))
    assert paid["payment_status"] == "PAID", paid
    assert paid["pay_method"] == "EXTERNAL_CARD", paid
    assert paid["fulfillment_status"] == "CART", paid


# ─── Queue B: state_machines section ──────────────────────────────────────

def test_start_prep_on_cart_order_rejected(api):
    """PRD §3.7: "Each of these queue steps requires the order to be in the expected
    source state and otherwise fails with `ERR_INVALID_STATE`."

    start-prep on an order still in CART (never placed) -> 409 ERR_INVALID_STATE;
    fulfillment_status stays CART.

    Design: Corner/state_machines/start_prep_from_cart_returns_invalid_state
    """
    ctx = fx.setup_cart_order_with_line(item_price=615)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    resp = api.start_prep(store_id, ctx["order"]["id"], fx.OPERATOR)
    validate_error(resp, ERR.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_order(ctx["order"]["id"], ctx["member_headers"]))
    assert reread["fulfillment_status"] == "CART", reread


def test_place_unpaid_order_rejected(api):
    """PRD §3.6: "Placement is permitted only when the order's `fulfillment_status` is
    `CART` and its `payment_status` is `PAID` — payment must be captured before an
    order enters the queue — and the order must have at least one line; a wrong-state
    attempt is rejected with `ERR_INVALID_STATE`."

    place on a CART/UNPAID order -> 409 ERR_INVALID_STATE.

    Design: Corner/state_machines/place_unpaid_order_returns_invalid_state
    """
    ctx = fx.setup_cart_order_with_line(item_price=615)
    mid = ctx["member"]["id"]
    resp = api.place_order(mid, ctx["order"]["id"],
                           f.place_payload(ctx["slot"]["version"]), ctx["member_headers"])
    validate_error(resp, ERR.ERR_INVALID_STATE.value)


def test_double_pay_rejected_no_second_earn(api):
    """PRD §3.5: "Pay is permitted only when the order's `payment_status` is `UNPAID`
    and its `fulfillment_status` is `CART`, and the order must have at least one line;
    an order in the wrong state for this transition is rejected with
    `ERR_INVALID_STATE`."
    PRD §3.4: "Concretely, a `GREEN` member paying with an external card earns 1 star
    per eligible pre-tax dollar".

    A second pay on an already-PAID 615c latte order -> 409 ERR_INVALID_STATE, and
    stars_earned stays 6 (no second EARN).

    Design: Corner/state_machines/double_pay_returns_invalid_state
    """
    ctx = fx.setup_cart_order_with_line(item_price=615)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    fx.pay(mid, ctx["order"]["id"], "EXTERNAL_CARD")
    resp = api.pay_order(mid, ctx["order"]["id"], f.pay_payload("EXTERNAL_CARD"), hdr)
    validate_error(resp, ERR.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_order(ctx["order"]["id"], hdr))
    assert reread["stars_earned"] == 6, reread


def test_refund_picked_up_order_rejected(api):
    """PRD §3.8: "The refund target must be `PAID` and must not yet be `PICKED_UP`; a
    completed pickup cannot be refunded and is rejected with `ERR_REFUND_NOT_ALLOWED`."

    Refund on a fully completed (PICKED_UP) order -> 409 ERR_REFUND_NOT_ALLOWED;
    payment_status stays PAID.

    Design: Corner/state_machines/refund_picked_up_order_returns_refund_not_allowed
    """
    ctx = fx.setup_placed_order(item_price=615)
    fx.drive_to_picked_up(ctx)
    store_id, oid = ctx["store"]["id"], ctx["order"]["id"]
    resp = api.refund_order(store_id, oid, f.refund_payload("ORIGINAL_METHOD"), fx.OPERATOR)
    validate_error(resp, ERR.ERR_REFUND_NOT_ALLOWED.value)
    reread = validate_success(api.get_order(oid, ctx["member_headers"]))
    assert reread["payment_status"] == "PAID", reread


def test_order_initial_state_cart_unpaid(api):
    """PRD §3.3: "The order is created with `fulfillment_status` `CART`,
    `payment_status` `UNPAID`, no `pay_method` yet, and all computed money fields —
    `subtotal_cents`, `reward_discount_cents`, `tax_cents`, and `total_cents` — at
    zero until pay finalizes them."

    A freshly created order: CART / UNPAID with zeroed subtotal and total.

    Design: Corner/state_machines/order_initial_state_cart_unpaid
    """
    ctx = fx.setup_base(item_price=615, num_slots=1)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    order = validate_success(api.create_order(
        mid, f.create_order_payload(ctx["store"]["id"], ctx["slots"][0]["id"]), hdr), 201)
    assert order["fulfillment_status"] == "CART", order
    assert order["payment_status"] == "UNPAID", order
    assert order["subtotal_cents"] == 0, order
    assert order["total_cents"] == 0, order


def test_close_member_with_inflight_order_rejected(api):
    """PRD §3.10: "Closure is permitted only when the member's `status` is `ACTIVE`
    and the member has no in-flight order — that is, no order owned by the member is in
    the `PLACED`, `IN_PREP`, or `READY` fulfillment states; a closure attempt in any
    other situation is rejected with `ERR_INVALID_STATE`."

    Closing a member who owns a PLACED order -> 409 ERR_INVALID_STATE; member stays
    ACTIVE.

    Design: Corner/state_machines/member_close_blocked_by_inflight_order
    """
    ctx = fx.setup_placed_order(item_price=615)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    resp = api.close_member(mid, hdr)
    validate_error(resp, ERR.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_member(mid, hdr))
    assert reread["status"] == "ACTIVE", reread


def test_operator_drives_full_queue_to_picked_up(api):
    """PRD §3.7: "Starting preparation advances `fulfillment_status` from `PLACED` to
    `IN_PREP` ... Marking an order ready advances it from `IN_PREP` to `READY`.
    Completing pickup advances it from `READY` to `PICKED_UP`, which is terminal, and
    recomputes the slot's `reserved_count` (the order leaves the reserved set)".

    PLACED -> IN_PREP -> READY -> PICKED_UP; final fulfillment PICKED_UP and the
    slot's reserved_count returns to 0.

    Design: Corner/state_machines/operator_full_queue_progression
    """
    ctx = fx.setup_placed_order(item_price=615)
    store_id, oid = ctx["store"]["id"], ctx["order"]["id"]
    fx.drive_to_picked_up(ctx)
    assert ctx["order"]["fulfillment_status"] == "PICKED_UP", ctx["order"]
    slot = validate_success(api.get_pickup_slot(ctx["slot"]["id"], fx.OPERATOR))
    assert slot["reserved_count"] == 0, slot
