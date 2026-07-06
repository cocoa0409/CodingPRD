"""Placement gates: capacity, allergen, locker, temporal, OCC, points, precedence."""
from test_helpers import (
    setup_store_item_slot_customer, create_store, create_menu_item, create_pickup_slot,
    create_customer, create_subscription_plan, create_active_subscription,
    create_cart_order, add_line, place, create_and_place_order, create_completed_order,
    advance, set_clock, saturate_slot, seed_points, make_customer_headers,
    get_slot, get_store, validate_error, validate_success, api_client, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]


def test_allergen_safety_beats_capacity_constraint(api):
    """PRD §3.11: "On placement they run in this order: the allergen safety gate
    (`ERR_ALLERGEN_BLOCKED`), then the slot-availability gate (`ERR_SLOT_UNAVAILABLE`), then the
    slot-capacity gate (`ERR_SLOT_CAPACITY_EXCEEDED`)".

    Design: Difficulty/priority_pair_validation_conflict/allergen_safety_beats_capacity_constraint
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=1)
    nutty = create_menu_item(store["id"], name="Nutty", base_price_cents=500,
                             base_calories=100, allergen_tags=["NUTS"])
    plain = create_menu_item(store["id"], name="Plain", base_price_cents=500, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")

    c1 = create_customer(store["id"])
    create_and_place_order(c1["id"], store["id"], slot["id"], plain["id"], slot["version"],
                           quantity=1)

    c2 = create_customer(store["id"], allergen_blocklist=["NUTS"])
    order2 = create_cart_order(c2["id"], store["id"], slot["id"])
    add_line(c2["id"], order2["id"], nutty["id"], quantity=1)
    slot_now = get_slot(slot["id"], make_customer_headers(c2["id"]))

    res = api.place_order(
        order2["id"],
        {"points_redeemed": 0, "expected_pickup_slot_version": slot_now["version"]},
        make_customer_headers(c2["id"]))
    validate_error(res, "ERR_ALLERGEN_BLOCKED")


def test_capacity_gate_fires_alone_when_allergen_clear(api):
    """PRD §3.5: "the slot's `reserved_count` must be strictly below the store's
    `throughput_capacity_per_slot`, or the order is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`".

    Design: Difficulty/priority_pair_validation_conflict/allergen_safety_beats_capacity_constraint
    """
    # Same shape as the precedence test but the second order carries NO blocklisted allergen,
    # so the capacity gate (lower priority) surfaces on its own.
    store = create_store(state_code="TX", throughput_capacity_per_slot=1)
    plain = create_menu_item(store["id"], name="Plain", base_price_cents=500, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")

    c1 = create_customer(store["id"])
    create_and_place_order(c1["id"], store["id"], slot["id"], plain["id"], slot["version"],
                           quantity=1)

    c2 = create_customer(store["id"])
    order2 = create_cart_order(c2["id"], store["id"], slot["id"])
    add_line(c2["id"], order2["id"], plain["id"], quantity=1)
    slot_now = get_slot(slot["id"], make_customer_headers(c2["id"]))

    res = api.place_order(
        order2["id"],
        {"points_redeemed": 0, "expected_pickup_slot_version": slot_now["version"]},
        make_customer_headers(c2["id"]))
    validate_error(res, "ERR_SLOT_CAPACITY_EXCEEDED")


def test_invalid_state_beats_insufficient_points(api):
    """PRD §3.11: "State validity comes sixth: a transition requested from a state where it is
    not defined — across any of the order lifecycle, settlement, subscription, or challenge axes
    — yields `ERR_INVALID_STATE`."
    PRD §3.11: "The remaining business gates apply specifically to placement and to refunds, and
    they rank after the six general checks above."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_insufficient_points
    """
    store, item, slot, customer = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})

    placed, new_v = create_and_place_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)

    res = api.place_order(
        placed["id"],
        {"points_redeemed": 9999, "expected_pickup_slot_version": new_v},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_insufficient_points_gate_fires_alone_on_valid_cart(api):
    """PRD §3.5: "the `points_redeemed` must not exceed the loyalty account's `points_balance`,
    or the order is rejected with `ERR_INSUFFICIENT_POINTS`".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_insufficient_points
    """
    # A CART order (valid state) with points_redeemed beyond a 0 balance surfaces the
    # lower-priority fiscal gate that ERR_INVALID_STATE would otherwise pre-empt.
    store, item, slot, customer = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})
    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=1)

    res = api.place_order(
        order["id"], {"points_redeemed": 9999, "expected_pickup_slot_version": slot["version"]},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INSUFFICIENT_POINTS")


def test_slot_capacity_strict_less_than_boundary(api):
    """PRD §3.5: "the slot's `reserved_count` must be strictly below the store's
    `throughput_capacity_per_slot`, or the order is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`".

    Design: Difficulty/boundary_precision_check/slot_capacity_strict_less_than_boundary
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=2)
    item = create_menu_item(store["id"], name="I", base_price_cents=500, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")

    c1 = create_customer(store["id"])
    _, v1 = create_and_place_order(c1["id"], store["id"], slot["id"], item["id"],
                                   slot["version"], quantity=1)
    c2 = create_customer(store["id"])
    _, v2 = create_and_place_order(c2["id"], store["id"], slot["id"], item["id"], v1, quantity=1)

    c3 = create_customer(store["id"])
    order3 = create_cart_order(c3["id"], store["id"], slot["id"])
    add_line(c3["id"], order3["id"], item["id"], quantity=1)
    res = api.place_order(
        order3["id"], {"points_redeemed": 0, "expected_pickup_slot_version": v2},
        make_customer_headers(c3["id"]))
    validate_error(res, "ERR_SLOT_CAPACITY_EXCEEDED")

    slot_after = get_slot(slot["id"])
    assert slot_after["reserved_count"] == 2


def test_slot_capacity_below_boundary_permits_placement(api):
    """PRD §3.5: "the slot's `reserved_count` must be strictly below the store's
    `throughput_capacity_per_slot`, or the order is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`".

    Design: Difficulty/boundary_precision_check/slot_capacity_strict_less_than_boundary
    """
    # cap 2, reserved_count 1 (1 < 2) -> the second placement is permitted and reaches CAPTURED.
    store = create_store(state_code="TX", throughput_capacity_per_slot=2)
    item = create_menu_item(store["id"], name="I", base_price_cents=500, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")

    c1 = create_customer(store["id"])
    _, v1 = create_and_place_order(c1["id"], store["id"], slot["id"], item["id"],
                                   slot["version"], quantity=1)
    c2 = create_customer(store["id"])
    placed2, _ = create_and_place_order(c2["id"], store["id"], slot["id"], item["id"], v1,
                                        quantity=1)

    assert placed2["order_status"] == "PLACED"
    assert placed2["settlement_status"] == "CAPTURED"
    assert get_slot(slot["id"])["reserved_count"] == 2


def test_empty_order_zero_lines_rejected(api):
    """PRD §3.5: "the order must hold at least one order line, or it is rejected with
    `ERR_EMPTY_ORDER`".

    Design: Difficulty/boundary_precision_check/empty_order_zero_lines_rejected
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    res = api.place_order(
        order["id"], {"points_redeemed": 0, "expected_pickup_slot_version": slot["version"]},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_EMPTY_ORDER")

    order_after = validate_success(
        api.get_order(order["id"], make_customer_headers(customer["id"])), 200)
    assert order_after["order_status"] == "CART"


def test_order_with_one_line_passes_empty_order_gate(api):
    """PRD §3.5: "the order must hold at least one order line, or it is rejected with
    `ERR_EMPTY_ORDER`".

    Design: Difficulty/boundary_precision_check/empty_order_zero_lines_rejected
    """
    # Exactly one line clears the empty-order gate and the order reaches PLACED.
    store, item, slot, customer = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})
    placed, _ = create_and_place_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)
    assert placed["order_status"] == "PLACED"


def test_order_place_requires_store_active(api):
    """PRD §3.4: "Adding a line for a menu item whose `is_available` is false, or whose store is
    not active, is rejected with `ERR_ITEM_UNAVAILABLE`."
    PRD §3.1: "an `is_active` flag, defaulting to true, that governs whether it accepts new
    orders."

    Design: Difficulty/cross_entity_state_dependency/order_place_requires_store_active
    """
    # The store's is_active flag governs whether it accepts new orders; the PRD concretizes this
    # at the add-line stage (§3.4), so an inactive store rejects new lines with ERR_ITEM_UNAVAILABLE.
    store = create_store(state_code="TX", throughput_capacity_per_slot=10, is_active=False)
    item = create_menu_item(store["id"], name="I", base_price_cents=500, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    res = api.add_order_line(
        order["id"], {"menu_item_id": item["id"], "quantity": 1},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_ITEM_UNAVAILABLE")

    order_after = validate_success(
        api.get_order(order["id"], make_customer_headers(customer["id"])), 200)
    assert order_after["order_status"] == "CART"


def test_order_place_at_active_store_succeeds(api):
    """PRD §3.1: "an `is_active` flag, defaulting to true, that governs whether it accepts new
    orders."
    PRD §3.5: "the order advances from `CART` to `PLACED`."

    Design: Difficulty/cross_entity_state_dependency/order_place_requires_store_active
    """
    # Same setup as the inactive-store rejection, but is_active true -> placement succeeds.
    store = create_store(state_code="TX", throughput_capacity_per_slot=10, is_active=True)
    item = create_menu_item(store["id"], name="I", base_price_cents=500, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])

    placed, _ = create_and_place_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)
    assert placed["order_status"] == "PLACED"


def test_earn_boost_requires_subscription_active(api):
    """PRD §3.6: "If the order applies a subscription whose `status` is `ACTIVE` at completion,
    the base points are then multiplied by the plan's `points_multiplier_bps`".
    PRD §3.9: "while `PAST_DUE`, its perks are suspended for new orders."

    Design: Difficulty/cross_entity_state_dependency/earn_boost_requires_subscription_active
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Bowl", base_price_cents=1450, base_calories=600)
    slot = create_pickup_slot(store["id"], channel="COUNTER",
                              window_end_utc="2026-06-30T00:00:00Z")
    plan = create_subscription_plan(tier_name="BOOST", monthly_fee_cents=999,
                                    points_multiplier_bps=15000)
    customer = create_customer(store["id"])
    sub = create_active_subscription(customer["id"], plan["id"])

    placed, _ = create_and_place_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"],
        quantity=2, subscription_id=sub["id"])
    advance(placed["id"])
    advance(placed["id"])

    set_clock("2026-05-01T00:00:00Z")
    validate_success(api.lapse_subscription(sub["id"], ADMIN), 200)

    done = validate_success(api.complete_order(placed["id"], MANAGER), 200)
    sub_after = validate_success(api.get_subscription(sub["id"], ADMIN), 200)
    assert done["points_earned"] == 290
    assert sub_after["status"] == "PAST_DUE"


def test_earn_boost_skipped_for_non_active_subscription(api):
    """PRD §3.6: "If the order applies a subscription whose `status` is `ACTIVE` at completion,
    the base points are then multiplied by the plan's `points_multiplier_bps` divided by ten
    thousand and floored again; with no active subscription the points earned equal the base
    points unchanged (equivalent to a 1.0× multiplier)."

    Design: Difficulty/cross_entity_state_dependency/earn_boost_requires_subscription_active
    """
    # Subscription applied but never paid (PENDING_PAYMENT, not ACTIVE) -> base earn 290.
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Bowl", base_price_cents=1450, base_calories=600)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    plan = create_subscription_plan(tier_name="BOOST2", monthly_fee_cents=999,
                                    points_multiplier_bps=15000)
    customer = create_customer(store["id"])
    sub = validate_success(
        api.create_subscription({"customer_id": customer["id"], "plan_id": plan["id"]},
                                make_customer_headers(customer["id"])), 201)

    done, _ = create_completed_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"],
        quantity=2, subscription_id=sub["id"])
    assert done["points_earned"] == 290


def test_slot_window_expired_rejected_half_open(api):
    """PRD §2.7: "the current clock instant is strictly before its `window_end_utc`".
    PRD §3.5: "the chosen slot must be active — the logical clock strictly before its
    `window_end_utc` and the slot not closed — and the requested `channel` must match the slot's
    `channel`, failing which the order is rejected with `ERR_SLOT_UNAVAILABLE`".

    Design: Difficulty/resource_temporal_overlap/slot_window_expired_rejected_half_open
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="I", base_price_cents=500, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER",
                              window_end_utc="2026-03-05T00:00:00Z")
    customer = create_customer(store["id"])

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=1)
    set_clock("2026-03-05T00:00:00Z")

    res = api.place_order(
        order["id"], {"points_redeemed": 0, "expected_pickup_slot_version": slot["version"]},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_SLOT_UNAVAILABLE")

    order_after = validate_success(
        api.get_order(order["id"], make_customer_headers(customer["id"])), 200)
    assert order_after["order_status"] == "CART"


def test_slot_window_active_before_end_permits_placement(api):
    """PRD §2.7: "the current clock instant is strictly before its `window_end_utc`".
    PRD §3.5: "the chosen slot must be active — the logical clock strictly before its
    `window_end_utc` and the slot not closed".

    Design: Difficulty/resource_temporal_overlap/slot_window_expired_rejected_half_open
    """
    # Clock one second before window_end -> slot still active -> placement succeeds.
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="I", base_price_cents=500, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER",
                              window_end_utc="2026-03-05T00:00:00Z")
    customer = create_customer(store["id"])

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=1)
    set_clock("2026-03-04T23:59:59Z")

    placed = place(customer["id"], order["id"], slot["version"])
    assert placed["order_status"] == "PLACED"


def test_locker_aggregate_capacity_exhausted(api):
    """PRD §3.5: "for a `LOCKER`-channel order the count of non-terminal `LOCKER` orders at the
    store must be strictly below the store's `locker_count`, or the order is rejected with
    `ERR_NO_LOCKER_AVAILABLE`".

    Design: Difficulty/resource_temporal_overlap/locker_aggregate_capacity_exhausted
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10, locker_count=1)
    item = create_menu_item(store["id"], name="I", base_price_cents=500, base_calories=100)
    slot1 = create_pickup_slot(store["id"], channel="LOCKER")
    slot2 = create_pickup_slot(store["id"], channel="LOCKER")

    c1 = create_customer(store["id"])
    create_and_place_order(c1["id"], store["id"], slot1["id"], item["id"], slot1["version"],
                           quantity=1)

    c2 = create_customer(store["id"])
    order2 = create_cart_order(c2["id"], store["id"], slot2["id"])
    add_line(c2["id"], order2["id"], item["id"], quantity=1)
    res = api.place_order(
        order2["id"], {"points_redeemed": 0, "expected_pickup_slot_version": slot2["version"]},
        make_customer_headers(c2["id"]))
    validate_error(res, "ERR_NO_LOCKER_AVAILABLE")

    slot2_after = get_slot(slot2["id"])
    assert slot2_after["reserved_count"] == 0


def test_locker_below_aggregate_capacity_permits_second(api):
    """PRD §3.5: "for a `LOCKER`-channel order the count of non-terminal `LOCKER` orders at the
    store must be strictly below the store's `locker_count`, or the order is rejected with
    `ERR_NO_LOCKER_AVAILABLE`".

    Design: Difficulty/resource_temporal_overlap/locker_aggregate_capacity_exhausted
    """
    # locker_count 2: with one LOCKER order already placed (1 < 2), a second is permitted.
    store = create_store(state_code="TX", throughput_capacity_per_slot=10, locker_count=2)
    item = create_menu_item(store["id"], name="I", base_price_cents=500, base_calories=100)
    slot1 = create_pickup_slot(store["id"], channel="LOCKER")
    slot2 = create_pickup_slot(store["id"], channel="LOCKER")

    c1 = create_customer(store["id"])
    create_and_place_order(c1["id"], store["id"], slot1["id"], item["id"], slot1["version"],
                           quantity=1)
    c2 = create_customer(store["id"])
    placed2, _ = create_and_place_order(c2["id"], store["id"], slot2["id"], item["id"],
                                        slot2["version"], quantity=1)

    assert placed2["order_status"] == "PLACED"
    assert get_slot(slot2["id"])["reserved_count"] == 1


def test_insufficient_points_redeem_more_than_held(api):
    """PRD §3.5: "the `points_redeemed` must not exceed the loyalty account's `points_balance`,
    or the order is rejected with `ERR_INSUFFICIENT_POINTS`".

    Design: Corner/validations/insufficient_points_redeem_more_than_held
    """
    store, item, slot, customer = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=1)
    res = api.place_order(
        order["id"], {"points_redeemed": 200, "expected_pickup_slot_version": slot["version"]},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INSUFFICIENT_POINTS")


def test_close_slot_blocks_placement(api):
    """PRD §3.2: "closing sets `is_closed` to true and increments the slot's `version` by one."
    PRD §3.5: "the chosen slot must be active — the logical clock strictly before its
    `window_end_utc` and the slot not closed — and the requested `channel` must match the slot's
    `channel`, failing which the order is rejected with `ERR_SLOT_UNAVAILABLE`".

    Design: Corner/endpoints/close_slot_blocks_placement
    """
    store, item, slot, customer = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=1)
    closed = validate_success(api.close_pickup_slot(slot["id"], MANAGER), 200)

    res = api.place_order(
        order["id"], {"points_redeemed": 0, "expected_pickup_slot_version": closed["version"]},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_SLOT_UNAVAILABLE")


def test_queue_status_busy_boundary_inclusive(api):
    """PRD §2.7: "The 0.70 and 1.0 boundaries are inclusive on the higher posture: a ratio of
    exactly 0.70 is `BUSY`, and a ratio of exactly 1.0 is `SURGE`."

    Design: Corner/calculations/queue_status_busy_boundary_inclusive
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="X", base_price_cents=500, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")

    saturate_slot(store["id"], item["id"], slot["id"], 7)

    slot_after = get_slot(slot["id"])
    store_after = get_store(store["id"])
    assert slot_after["reserved_count"] == 7
    assert store_after["queue_status"] == "BUSY"


def test_occ_stale_slot_version_conflict(api):
    """PRD §2.8: "If that value does not equal the slot's current `version` at the moment of
    placement — because another placement reserved capacity, or a cancellation released it, or
    the slot was administratively closed, each of which bumps the slot's `version` — then the
    placing client is working from a stale view of the slot's remaining capacity and the request
    is rejected with `ERR_STALE_SLOT_VERSION` at HTTP status 412."

    Design: Corner/cross_cutting_layers/occ_stale_slot_version_conflict
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=5)
    item = create_menu_item(store["id"], name="X", base_price_cents=500, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    stale_version = slot["version"]

    c1 = create_customer(store["id"])
    c2 = create_customer(store["id"])
    order1 = create_cart_order(c1["id"], store["id"], slot["id"])
    add_line(c1["id"], order1["id"], item["id"], quantity=1)
    order2 = create_cart_order(c2["id"], store["id"], slot["id"])
    add_line(c2["id"], order2["id"], item["id"], quantity=1)

    place(c1["id"], order1["id"], stale_version)  # bumps slot version to 2

    res = api.place_order(
        order2["id"], {"points_redeemed": 0, "expected_pickup_slot_version": stale_version},
        make_customer_headers(c2["id"]))
    validate_error(res, "ERR_STALE_SLOT_VERSION")
