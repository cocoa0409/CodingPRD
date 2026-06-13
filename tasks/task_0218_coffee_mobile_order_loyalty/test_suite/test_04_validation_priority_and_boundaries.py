"""Validation precedence, boundary edges, cross-entity state gating, and slot geometry.

Queue A (Difficulty): priority_pair_validation_conflict, boundary_precision_check,
                      cross_entity_state_dependency, resource_temporal_overlap.
"""
from test_helpers import (
    fixtures as fx,
    factories as f,
    validate_success,
    validate_error,
    ApiErrorId,
)

ERR = ApiErrorId


# ─── priority_pair_validation_conflict ────────────────────────────────────

def test_place_store_paused_beats_slot_full(api):
    """PRD §3.11: "Store-open status for placing or starting prep is checked
    (`ERR_STORE_PAUSED`). ... Remaining slot capacity at place is checked
    (`ERR_SLOT_FULL`)."
    PRD §3.6: "The fulfilling store must be `OPEN`; placing against a `PAUSED` store is
    rejected with `ERR_STORE_PAUSED`."

    slot_capacity 1: member A's order fills the slot; store is then PAUSED; member B
    tries to place into the same full slot at the paused store -> ERR_STORE_PAUSED
    (priority 7 outranks ERR_SLOT_FULL priority 11).

    Design: Difficulty/priority_pair_validation_conflict/place_store_paused_beats_slot_full
    """
    fx.set_clock()
    store = fx.create_store(slot_capacity=1, prep_minutes=0)
    item = fx.create_menu_item(store["id"], base_price_cents=615, category="BEVERAGE")
    slot = fx.create_pickup_slot(store["id"], *fx._SLOT_WINDOWS[0])

    mem_a = fx.create_member()
    a_order = fx.create_cart_order(mem_a["id"], store["id"], slot["id"])
    fx.add_line(mem_a["id"], a_order["id"], item["id"], quantity=1)
    fx.pay(mem_a["id"], a_order["id"], "EXTERNAL_CARD")
    fx.place(mem_a["id"], a_order["id"], slot["version"])  # slot now full

    mem_b = fx.create_member()
    b_order = fx.create_cart_order(mem_b["id"], store["id"], slot["id"])
    fx.add_line(mem_b["id"], b_order["id"], item["id"], quantity=1)
    fx.pay(mem_b["id"], b_order["id"], "EXTERNAL_CARD")
    cur_slot = validate_success(api.get_pickup_slot(slot["id"], fx.OPERATOR))
    fx.get_success_data(api.pause_store(store["id"], f.pause_payload(True), fx.ADMIN))

    resp = api.place_order(mem_b["id"], b_order["id"],
                           f.place_payload(cur_slot["version"]),
                           fx.make_member_headers(mem_b["id"]))
    validate_error(resp, ERR.ERR_STORE_PAUSED.value)


def test_place_paused_full_slot_order_stays_cart(api):
    """PRD §3.6: "The fulfilling store must be `OPEN`; placing against a `PAUSED` store
    is rejected with `ERR_STORE_PAUSED`."
    PRD §3.6: "A successful place advances `fulfillment_status` from `CART` to
    `PLACED`".

    Second facet of the priority pair: when the paused-store check pre-empts the
    place, the rejected order is left in CART (no PLACED transition leaked through).

    Design: Difficulty/priority_pair_validation_conflict/place_store_paused_beats_slot_full
    """
    fx.set_clock()
    store = fx.create_store(slot_capacity=1, prep_minutes=0)
    item = fx.create_menu_item(store["id"], base_price_cents=615, category="BEVERAGE")
    slot = fx.create_pickup_slot(store["id"], *fx._SLOT_WINDOWS[0])

    mem_a = fx.create_member()
    a_order = fx.create_cart_order(mem_a["id"], store["id"], slot["id"])
    fx.add_line(mem_a["id"], a_order["id"], item["id"], quantity=1)
    fx.pay(mem_a["id"], a_order["id"], "EXTERNAL_CARD")
    fx.place(mem_a["id"], a_order["id"], slot["version"])

    mem_b = fx.create_member()
    b_order = fx.create_cart_order(mem_b["id"], store["id"], slot["id"])
    fx.add_line(mem_b["id"], b_order["id"], item["id"], quantity=1)
    fx.pay(mem_b["id"], b_order["id"], "EXTERNAL_CARD")
    cur_slot = validate_success(api.get_pickup_slot(slot["id"], fx.OPERATOR))
    fx.get_success_data(api.pause_store(store["id"], f.pause_payload(True), fx.ADMIN))
    b_hdr = fx.make_member_headers(mem_b["id"])

    resp = api.place_order(mem_b["id"], b_order["id"],
                           f.place_payload(cur_slot["version"]), b_hdr)
    validate_error(resp, ERR.ERR_STORE_PAUSED.value)
    reread = validate_success(api.get_order(b_order["id"], b_hdr))
    assert reread["fulfillment_status"] == "CART", reread


def test_pay_reward_not_applicable_beats_insufficient_balance(api):
    """PRD §3.11: "Reward applicability at pay is checked
    (`ERR_REWARD_NOT_APPLICABLE`). ... Sufficient wallet balance for a stored-value
    pay, after any auto-reload, is checked (`ERR_INSUFFICIENT_BALANCE`)."
    PRD §3.5: "a reward failing any of these is rejected with
    `ERR_REWARD_NOT_APPLICABLE`. A reward whose `expires_at` is at or before the
    current time is treated as expired at pay/place time".

    Order applies an expired reward AND pays STORED_VALUE on an empty card ->
    ERR_REWARD_NOT_APPLICABLE (priority 9 outranks ERR_INSUFFICIENT_BALANCE
    priority 12).

    Design: Difficulty/priority_pair_validation_conflict/pay_reward_not_applicable_beats_insufficient_balance
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    store = fx.create_store(slot_capacity=5, prep_minutes=0)
    latte = fx.create_menu_item(store["id"], name="Latte", base_price_cents=615,
                                category="BEVERAGE", reward_eligible=True)
    slot1 = fx.create_pickup_slot(store["id"], "2026-06-01T17:00:00Z", "2026-06-01T17:15:00Z")
    slot2 = fx.create_pickup_slot(store["id"], "2026-12-01T17:00:00Z", "2026-12-01T17:15:00Z")
    mem = fx.create_member()
    mid = mem["id"]
    hdr = fx.make_member_headers(mid)
    # Earn 150 stars and mint a FREE_ITEM reward (60-day TTL -> expires before Dec).
    fx.earn_lifetime_stars(mid, store["id"], slot1["id"], dollars=150)
    reward = fx.mint_free_item_reward(mid)
    # Advance clock past reward expiry; card balance stays 0.
    fx.set_clock("2026-12-01T00:00:00Z")
    order = fx.create_cart_order(mid, store["id"], slot2["id"], applied_reward_id=reward["id"])
    fx.add_line(mid, order["id"], latte["id"], quantity=1)
    card = fx.get_card(mid)
    resp = api.pay_order(
        mid, order["id"],
        f.pay_payload("STORED_VALUE", expected_card_version=card["version"]), hdr)
    validate_error(resp, ERR.ERR_REWARD_NOT_APPLICABLE.value)
    reread = validate_success(api.get_order(order["id"], hdr))
    assert reread["payment_status"] == "UNPAID", reread


def test_pay_reward_priority_order_not_charged(api):
    """PRD §3.11: "Reward applicability at pay is checked
    (`ERR_REWARD_NOT_APPLICABLE`). ... Sufficient wallet balance for a stored-value
    pay, after any auto-reload, is checked (`ERR_INSUFFICIENT_BALANCE`)."
    PRD §3.5: "a successful pay then sets the order's `pay_method`, advances
    `payment_status` from `UNPAID` to `PAID`".

    Second facet of the priority pair: when the reward-applicability check fires
    first, no spend is committed — the order remains UNPAID with no pay_method
    recorded (the fiscal/balance path was never reached).

    Design: Difficulty/priority_pair_validation_conflict/pay_reward_not_applicable_beats_insufficient_balance
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    store = fx.create_store(slot_capacity=5, prep_minutes=0)
    latte = fx.create_menu_item(store["id"], name="Latte", base_price_cents=615,
                                category="BEVERAGE", reward_eligible=True)
    slot1 = fx.create_pickup_slot(store["id"], "2026-06-01T17:00:00Z", "2026-06-01T17:15:00Z")
    slot2 = fx.create_pickup_slot(store["id"], "2026-12-01T17:00:00Z", "2026-12-01T17:15:00Z")
    mem = fx.create_member()
    mid = mem["id"]
    hdr = fx.make_member_headers(mid)
    fx.earn_lifetime_stars(mid, store["id"], slot1["id"], dollars=150)
    reward = fx.mint_free_item_reward(mid)
    fx.set_clock("2026-12-01T00:00:00Z")
    order = fx.create_cart_order(mid, store["id"], slot2["id"], applied_reward_id=reward["id"])
    fx.add_line(mid, order["id"], latte["id"], quantity=1)
    card = fx.get_card(mid)
    resp = api.pay_order(
        mid, order["id"],
        f.pay_payload("STORED_VALUE", expected_card_version=card["version"]), hdr)
    validate_error(resp, ERR.ERR_REWARD_NOT_APPLICABLE.value)
    reread = validate_success(api.get_order(order["id"], hdr))
    assert reread["payment_status"] == "UNPAID", reread
    assert reread["pay_method"] is None, reread


# ─── boundary_precision_check ─────────────────────────────────────────────

def test_slot_capacity_boundary_first_succeeds_second_full(api):
    """PRD §3.6: "an order may be placed only when strictly fewer than `slot_capacity`
    orders already hold the slot, so the slot-capacity-th order to place succeeds and
    the next one fails with `ERR_SLOT_FULL`."

    slot_capacity 1: the first place succeeds (reserved_count 0 < 1); the second
    fails ERR_SLOT_FULL (1 < 1 is false).

    Design: Difficulty/boundary_precision_check/slot_capacity_exact_boundary_place
    """
    fx.set_clock()
    store = fx.create_store(slot_capacity=1, prep_minutes=0)
    item = fx.create_menu_item(store["id"], base_price_cents=615, category="BEVERAGE")
    slot = fx.create_pickup_slot(store["id"], *fx._SLOT_WINDOWS[0])

    mem1 = fx.create_member()
    o1 = fx.create_cart_order(mem1["id"], store["id"], slot["id"])
    fx.add_line(mem1["id"], o1["id"], item["id"], quantity=1)
    fx.pay(mem1["id"], o1["id"], "EXTERNAL_CARD")

    mem2 = fx.create_member()
    o2 = fx.create_cart_order(mem2["id"], store["id"], slot["id"])
    fx.add_line(mem2["id"], o2["id"], item["id"], quantity=1)
    fx.pay(mem2["id"], o2["id"], "EXTERNAL_CARD")

    placed1 = fx.place(mem1["id"], o1["id"], slot["version"])
    assert placed1["fulfillment_status"] == "PLACED", placed1

    cur_slot = validate_success(api.get_pickup_slot(slot["id"], fx.OPERATOR))
    assert cur_slot["reserved_count"] == 1, cur_slot
    resp = api.place_order(mem2["id"], o2["id"], f.place_payload(cur_slot["version"]),
                           fx.make_member_headers(mem2["id"]))
    validate_error(resp, ERR.ERR_SLOT_FULL.value)


def test_slot_capacity_one_below_boundary_place_succeeds(api):
    """PRD §3.6: "an order may be placed only when strictly fewer than `slot_capacity`
    orders already hold the slot, so the slot-capacity-th order to place succeeds and
    the next one fails with `ERR_SLOT_FULL`."
    PRD §3.2: "a single-slot read reports the live `reserved_count`, which is the
    number of orders against that slot currently in the `PLACED`, `IN_PREP`, or
    `READY` fulfillment states."

    Below-boundary side of the count edge: with slot_capacity 1, the very first place
    (reserved_count 0 < 1) succeeds and drives reserved_count to exactly 1.

    Design: Difficulty/boundary_precision_check/slot_capacity_exact_boundary_place
    """
    fx.set_clock()
    store = fx.create_store(slot_capacity=1, prep_minutes=0)
    item = fx.create_menu_item(store["id"], base_price_cents=615, category="BEVERAGE")
    slot = fx.create_pickup_slot(store["id"], *fx._SLOT_WINDOWS[0])
    mem = fx.create_member()
    o = fx.create_cart_order(mem["id"], store["id"], slot["id"])
    fx.add_line(mem["id"], o["id"], item["id"], quantity=1)
    fx.pay(mem["id"], o["id"], "EXTERNAL_CARD")
    placed = fx.place(mem["id"], o["id"], slot["version"])
    assert placed["fulfillment_status"] == "PLACED", placed
    cur = validate_success(api.get_pickup_slot(slot["id"], fx.OPERATOR))
    assert cur["reserved_count"] == 1, cur


def test_redeem_at_exact_star_cost_boundary_succeeds(api):
    """PRD §3.9: "Redemption requires the member's `star_balance` to be at least the
    redemption cost of 150 stars; if it is below that, the request is rejected with
    `ERR_INSUFFICIENT_STARS`. A successful redemption appends a `StarLedgerEntry` of
    kind `REDEEM` carrying the negative redemption cost (after which the member's
    `star_balance` is recomputed), and mints a `RewardGrant` of kind `FREE_ITEM`".

    A member with exactly 150 stars redeems successfully (>= boundary), minting a
    FREE_ITEM reward and leaving star_balance 0.

    Design: Difficulty/boundary_precision_check/redeem_star_cost_exact_boundary
    """
    ctx = fx.setup_base(item_price=615, num_slots=1)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    fx.earn_lifetime_stars(mid, store_id, ctx["slots"][0]["id"], dollars=150)
    reward = validate_success(api.redeem_reward(mid, hdr), 201)
    assert reward["kind"] == "FREE_ITEM", reward
    member = validate_success(api.get_member(mid, hdr))
    assert member["star_balance"] == 0, member


def test_redeem_at_boundary_mints_free_item_with_cost_and_cap(api):
    """PRD §3.9: "mints a `RewardGrant` of kind `FREE_ITEM` in `ISSUED` status with a
    `star_cost` of 150, a `max_discount_cents` of 700".
    PRD §3.9: "A successful redemption appends a `StarLedgerEntry` of kind `REDEEM`
    carrying the negative redemption cost (after which the member's `star_balance` is
    recomputed)".

    At the exact 150-star boundary the minted FREE_ITEM reward records star_cost 150,
    max_discount_cents 700, and status ISSUED (the reward attributes of the boundary
    redeem, distinct from the balance-only first assertion).

    Design: Difficulty/boundary_precision_check/redeem_star_cost_exact_boundary
    """
    ctx = fx.setup_base(item_price=615, num_slots=1)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    fx.earn_lifetime_stars(mid, store_id, ctx["slots"][0]["id"], dollars=150)
    reward = validate_success(api.redeem_reward(mid, hdr), 201)
    assert reward["star_cost"] == 150, reward
    assert reward["max_discount_cents"] == 700, reward
    assert reward["status"] == "ISSUED", reward


# ─── cross_entity_state_dependency ────────────────────────────────────────

def test_place_requires_store_open(api):
    """PRD §3.6: "The fulfilling store must be `OPEN`; placing against a `PAUSED` store
    is rejected with `ERR_STORE_PAUSED`."
    PRD §3.2: "when `paused` is true the store's `status` becomes `PAUSED`".

    A paid order at a PAUSED store cannot be placed -> ERR_STORE_PAUSED; order stays
    CART.

    Design: Difficulty/cross_entity_state_dependency/order_place_requires_store_open
    """
    ctx = fx.setup_paid_order(item_price=615)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    fx.get_success_data(api.pause_store(store_id, f.pause_payload(True), fx.ADMIN))
    resp = api.place_order(mid, ctx["order"]["id"],
                           f.place_payload(ctx["slot"]["version"]), hdr)
    validate_error(resp, ERR.ERR_STORE_PAUSED.value)
    reread = validate_success(api.get_order(ctx["order"]["id"], hdr))
    assert reread["fulfillment_status"] == "CART", reread


def test_place_at_paused_store_keeps_payment_status_paid(api):
    """PRD §3.6: "The fulfilling store must be `OPEN`; placing against a `PAUSED` store
    is rejected with `ERR_STORE_PAUSED`."
    PRD §2.9: "the conservation invariant is that a member's `StoredValueCard`
    `balance_cents` after a pay followed by a refund equals the balance before the
    pay".

    The Order->Store dependency only blocks the place transition: the already-captured
    payment is untouched, so the order keeps payment_status PAID after the rejected
    place (no refund cascade leaks from a blocked place).

    Design: Difficulty/cross_entity_state_dependency/order_place_requires_store_open
    """
    ctx = fx.setup_paid_order(item_price=615)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    fx.get_success_data(api.pause_store(store_id, f.pause_payload(True), fx.ADMIN))
    resp = api.place_order(mid, ctx["order"]["id"],
                           f.place_payload(ctx["slot"]["version"]), hdr)
    validate_error(resp, ERR.ERR_STORE_PAUSED.value)
    reread = validate_success(api.get_order(ctx["order"]["id"], hdr))
    assert reread["payment_status"] == "PAID", reread


def test_pay_reapplying_redeemed_reward_rejected(api):
    """PRD §3.5: "For a reward to be reservable at pay time it must be owned by the
    order's member, be in `ISSUED` status, not be expired ... and the order must have
    at least one reward-eligible line; a reward failing any of these is rejected with
    `ERR_REWARD_NOT_APPLICABLE`."
    PRD §3.6: "the reward's `status` moves from `RESERVED` to `REDEEMED`, which is
    terminal — a redeemed reward cannot be reused unless it is later restored by a
    cancel or refund."

    A new order re-applies a reward already REDEEMED on a prior placed order; paying it
    -> ERR_REWARD_NOT_APPLICABLE, and the reward stays REDEEMED.

    Design: Difficulty/cross_entity_state_dependency/order_pay_reward_reserve_requires_reward_issued
    """
    ctx = fx.setup_member_with_free_item_reward(num_slots=5)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    reward = ctx["reward"]
    # Drive the reward to REDEEMED on a real order.
    used = fx.create_cart_order(mid, store_id, ctx["slots"][1]["id"],
                                applied_reward_id=reward["id"])
    fx.add_line(mid, used["id"], ctx["item"]["id"], quantity=1)
    fx.pay(mid, used["id"], "EXTERNAL_CARD")
    slot = validate_success(api.get_pickup_slot(ctx["slots"][1]["id"], hdr))
    fx.place(mid, used["id"], slot["version"])
    redeemed = validate_success(api.get_reward(reward["id"], hdr))
    assert redeemed["status"] == "REDEEMED", redeemed

    # New order re-applies the REDEEMED reward.
    order = fx.create_cart_order(mid, store_id, ctx["slots"][2]["id"],
                                 applied_reward_id=reward["id"])
    fx.add_line(mid, order["id"], ctx["item"]["id"], quantity=1)
    resp = api.pay_order(mid, order["id"], f.pay_payload("EXTERNAL_CARD"), hdr)
    validate_error(resp, ERR.ERR_REWARD_NOT_APPLICABLE.value)
    still = validate_success(api.get_reward(reward["id"], hdr))
    assert still["status"] == "REDEEMED", still


def test_pay_with_redeemed_reward_leaves_order_unpaid(api):
    """PRD §3.5: "For a reward to be reservable at pay time it must be owned by the
    order's member, be in `ISSUED` status, not be expired ... a reward failing any of
    these is rejected with `ERR_REWARD_NOT_APPLICABLE`."
    PRD §3.5: "a successful pay then sets the order's `pay_method`, advances
    `payment_status` from `UNPAID` to `PAID`".

    Second facet of the Order->RewardGrant dependency: because the reward is no longer
    ISSUED, the pay is rejected and the order is left UNPAID (the PAID transition is
    gated on the reward-reserve sub-step succeeding).

    Design: Difficulty/cross_entity_state_dependency/order_pay_reward_reserve_requires_reward_issued
    """
    ctx = fx.setup_member_with_free_item_reward(num_slots=5)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    reward = ctx["reward"]
    used = fx.create_cart_order(mid, store_id, ctx["slots"][1]["id"],
                                applied_reward_id=reward["id"])
    fx.add_line(mid, used["id"], ctx["item"]["id"], quantity=1)
    fx.pay(mid, used["id"], "EXTERNAL_CARD")
    slot = validate_success(api.get_pickup_slot(ctx["slots"][1]["id"], hdr))
    fx.place(mid, used["id"], slot["version"])

    order = fx.create_cart_order(mid, store_id, ctx["slots"][2]["id"],
                                 applied_reward_id=reward["id"])
    fx.add_line(mid, order["id"], ctx["item"]["id"], quantity=1)
    resp = api.pay_order(mid, order["id"], f.pay_payload("EXTERNAL_CARD"), hdr)
    validate_error(resp, ERR.ERR_REWARD_NOT_APPLICABLE.value)
    reread = validate_success(api.get_order(order["id"], hdr))
    assert reread["payment_status"] == "UNPAID", reread


# ─── resource_temporal_overlap ────────────────────────────────────────────

def test_slot_overlap_rejected_endpoint_touch_allowed(api):
    """PRD §3.2: "A new slot's window must not overlap any existing slot on the same
    store; two windows that merely touch at an endpoint — where one window's end equals
    the next window's start — do not overlap and are allowed, but any genuine overlap
    is rejected with `ERR_SLOT_OVERLAP`."

    Existing slot [17:00,17:15). An endpoint-touching slot [17:15,17:30) is accepted;
    an overlapping slot [17:10,17:20) is rejected ERR_SLOT_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/pickup_slot_create_halfopen_overlap_rejected
    """
    fx.set_clock()
    store = fx.create_store(slot_capacity=5, prep_minutes=0)
    fx.create_pickup_slot(store["id"], "2026-06-01T17:00:00Z", "2026-06-01T17:15:00Z")
    # Endpoint-touching slot is accepted.
    touch = validate_success(api.create_pickup_slot(
        store["id"],
        f.create_pickup_slot_payload("2026-06-01T17:15:00Z", "2026-06-01T17:30:00Z"),
        fx.ADMIN), 201)
    assert touch["id"]
    # Genuine overlap is rejected.
    resp = api.create_pickup_slot(
        store["id"],
        f.create_pickup_slot_payload("2026-06-01T17:10:00Z", "2026-06-01T17:20:00Z"),
        fx.ADMIN)
    validate_error(resp, ERR.ERR_SLOT_OVERLAP.value)


def test_slot_endpoint_touching_window_accepted(api):
    """PRD §3.2: "two windows that merely touch at an endpoint — where one window's end
    equals the next window's start — do not overlap and are allowed, but any genuine
    overlap is rejected with `ERR_SLOT_OVERLAP`."
    PRD §3.2: "the window is half-open: `window_start` is inclusive and `window_end` is
    exclusive."

    Half-open adjacency: with an existing slot [17:00,17:15), a new slot starting
    exactly at 17:15 ([17:15,17:30)) is accepted (created with a reserved_count of 0).

    Design: Difficulty/resource_temporal_overlap/pickup_slot_create_halfopen_overlap_rejected
    """
    fx.set_clock()
    store = fx.create_store(slot_capacity=5, prep_minutes=0)
    fx.create_pickup_slot(store["id"], "2026-06-01T17:00:00Z", "2026-06-01T17:15:00Z")
    touch = validate_success(api.create_pickup_slot(
        store["id"],
        f.create_pickup_slot_payload("2026-06-01T17:15:00Z", "2026-06-01T17:30:00Z"),
        fx.ADMIN), 201)
    assert touch["window_start"].startswith("2026-06-01T17:15:00"), touch
    assert touch["reserved_count"] == 0, touch


def test_slot_aggregate_capacity_third_place_rejected(api):
    """PRD §3.6: "an order may be placed only when strictly fewer than `slot_capacity`
    orders already hold the slot, so the slot-capacity-th order to place succeeds and
    the next one fails with `ERR_SLOT_FULL`."
    PRD §3.2: "a single-slot read reports the live `reserved_count`, which is the
    number of orders against that slot currently in the `PLACED`, `IN_PREP`, or
    `READY` fulfillment states."

    slot_capacity 2: two orders place successfully (reserved_count 2); the third place
    is rejected ERR_SLOT_FULL.

    Design: Difficulty/resource_temporal_overlap/pickup_slot_aggregate_capacity_overlap_at_place
    """
    fx.set_clock()
    store = fx.create_store(slot_capacity=2, prep_minutes=0)
    item = fx.create_menu_item(store["id"], base_price_cents=615, category="BEVERAGE")
    slot = fx.create_pickup_slot(store["id"], *fx._SLOT_WINDOWS[0])

    orders = []
    for _ in range(3):
        mem = fx.create_member()
        o = fx.create_cart_order(mem["id"], store["id"], slot["id"])
        fx.add_line(mem["id"], o["id"], item["id"], quantity=1)
        fx.pay(mem["id"], o["id"], "EXTERNAL_CARD")
        orders.append((mem["id"], o["id"]))

    # Place the first two (capacity 2).
    cur = validate_success(api.get_pickup_slot(slot["id"], fx.OPERATOR))
    fx.place(orders[0][0], orders[0][1], cur["version"])
    cur = validate_success(api.get_pickup_slot(slot["id"], fx.OPERATOR))
    fx.place(orders[1][0], orders[1][1], cur["version"])

    cur = validate_success(api.get_pickup_slot(slot["id"], fx.OPERATOR))
    assert cur["reserved_count"] == 2, cur
    resp = api.place_order(orders[2][0], orders[2][1], f.place_payload(cur["version"]),
                           fx.make_member_headers(orders[2][0]))
    validate_error(resp, ERR.ERR_SLOT_FULL.value)


def test_slot_aggregate_capacity_blocked_order_stays_cart(api):
    """PRD §3.6: "an order may be placed only when strictly fewer than `slot_capacity`
    orders already hold the slot, so the slot-capacity-th order to place succeeds and
    the next one fails with `ERR_SLOT_FULL`."
    PRD §3.6: "A successful place advances `fulfillment_status` from `CART` to
    `PLACED`".

    Second facet of the aggregate-capacity instance: when the third place is rejected
    with ERR_SLOT_FULL, that order is left in CART (it never enters the reserved set,
    keeping reserved_count at the capacity of 2).

    Design: Difficulty/resource_temporal_overlap/pickup_slot_aggregate_capacity_overlap_at_place
    """
    fx.set_clock()
    store = fx.create_store(slot_capacity=2, prep_minutes=0)
    item = fx.create_menu_item(store["id"], base_price_cents=615, category="BEVERAGE")
    slot = fx.create_pickup_slot(store["id"], *fx._SLOT_WINDOWS[0])

    orders = []
    for _ in range(3):
        mem = fx.create_member()
        o = fx.create_cart_order(mem["id"], store["id"], slot["id"])
        fx.add_line(mem["id"], o["id"], item["id"], quantity=1)
        fx.pay(mem["id"], o["id"], "EXTERNAL_CARD")
        orders.append((mem["id"], o["id"]))

    cur = validate_success(api.get_pickup_slot(slot["id"], fx.OPERATOR))
    fx.place(orders[0][0], orders[0][1], cur["version"])
    cur = validate_success(api.get_pickup_slot(slot["id"], fx.OPERATOR))
    fx.place(orders[1][0], orders[1][1], cur["version"])
    cur = validate_success(api.get_pickup_slot(slot["id"], fx.OPERATOR))

    third_hdr = fx.make_member_headers(orders[2][0])
    resp = api.place_order(orders[2][0], orders[2][1], f.place_payload(cur["version"]),
                           third_hdr)
    validate_error(resp, ERR.ERR_SLOT_FULL.value)
    reread = validate_success(api.get_order(orders[2][1], third_hdr))
    assert reread["fulfillment_status"] == "CART", reread
    final_slot = validate_success(api.get_pickup_slot(slot["id"], fx.OPERATOR))
    assert final_slot["reserved_count"] == 2, final_slot
