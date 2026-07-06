"""Order parallel status axes, completion cascades, cancellation reversals, conservation."""
from test_helpers import (
    setup_store_item_slot_customer, create_store, create_menu_item, create_pickup_slot,
    create_customer, create_subscription_plan, create_active_subscription,
    create_cart_order, add_line, place, create_and_place_order, create_completed_order,
    advance, complete, make_it_right, cancel, seed_wallet, seed_points, set_clock,
    create_loyalty_challenge_payload, make_customer_headers,
    get_order, get_slot, get_store, get_customer, get_loyalty_account, get_subscription,
    get_challenge, validate_success, api_client, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]


def test_order_parallel_status_axes_completed_and_partially_refunded(api):
    """PRD §3.8: "A `refund_amount_cents` strictly between 0 and the remainder moves the
    settlement to `PARTIALLY_REFUNDED` and adds the amount to `refunded_cents`."
    PRD §3.6: "Completing a `READY` order moves its `order_status` to `COMPLETED`".

    Design: Difficulty/non_linear_state_machine/order_parallel_status_axes
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Item1000", base_price_cents=1000, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])

    done, _ = create_completed_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)
    refunded = make_it_right(done["id"], 400, "ORIGINAL")

    assert refunded["order_status"] == "COMPLETED"
    assert refunded["settlement_status"] == "PARTIALLY_REFUNDED"


def test_order_axes_independent_completed_then_fully_refunded(api):
    """PRD §3.8: "A `refund_amount_cents` exactly equal to the remainder moves the settlement to
    `REFUNDED` and sets `refunded_cents` to the full `total_cents`".
    PRD §3.6: "Completing a `READY` order moves its `order_status` to `COMPLETED`".

    Design: Difficulty/non_linear_state_machine/order_parallel_status_axes
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Item1000", base_price_cents=1000, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])

    done, _ = create_completed_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)
    refunded = make_it_right(done["id"], 1000, "ORIGINAL")

    assert refunded["order_status"] == "COMPLETED"
    assert refunded["settlement_status"] == "REFUNDED"


def test_subscription_past_due_recovery_cycle(api):
    """PRD §3.9: "a successful payment on a `PAST_DUE` subscription recovers it to `ACTIVE`;
    in both cases `current_period_end_utc` is set to the current clock instant plus 30 days."

    Design: Difficulty/non_linear_state_machine/subscription_past_due_recovery_cycle
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    plan = create_subscription_plan(tier_name="PLAN_A", monthly_fee_cents=999)
    customer = create_customer(store["id"])
    sub = create_active_subscription(customer["id"], plan["id"])

    set_clock("2026-05-01T00:00:00Z")
    validate_success(api.lapse_subscription(sub["id"], ADMIN), 200)
    recovered = validate_success(
        api.pay_subscription(sub["id"], {"payment_outcome": "SUCCEEDED"},
                             make_customer_headers(customer["id"])), 200)

    assert recovered["status"] == "ACTIVE"
    assert recovered["current_period_end_utc"] == "2026-05-31T00:00:00.000Z" \
        or recovered["current_period_end_utc"].startswith("2026-05-31T00:00:00")


def test_subscription_active_lapses_to_past_due_after_period_end(api):
    """PRD §3.9: "An admin may lapse an `ACTIVE` subscription to `PAST_DUE`, but only once its
    period has ended — that is, only when the current clock instant is at or after
    `current_period_end_utc`".

    Design: Difficulty/non_linear_state_machine/subscription_past_due_recovery_cycle
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    plan = create_subscription_plan(tier_name="PLAN_B", monthly_fee_cents=999)
    customer = create_customer(store["id"])
    sub = create_active_subscription(customer["id"], plan["id"])

    set_clock("2026-05-01T00:00:00Z")
    lapsed = validate_success(api.lapse_subscription(sub["id"], ADMIN), 200)
    assert lapsed["status"] == "PAST_DUE"


def test_complete_order_challenge_bonus_tier_depth3_cascade(api):
    """PRD §3.6: "if it then reaches or exceeds the challenge's `target_order_count` while the
    challenge is `IN_PROGRESS`, the challenge transitions to `ROUND_COMPLETE`, which appends a
    `CHALLENGE_BONUS` ledger entry with `delta_points` equal to the challenge's `bonus_points`
    and increments `rounds_completed` by one."
    PRD §3.6: "That bonus entry, being an earning entry, itself recomputes the account's
    `points_balance`, `lifetime_points_earned`, and `tier` — a three-deep cascade running from
    order completion, through the round-completion bonus, into the loyalty-account recomputation."
    PRD §2.10: "`GOLD` when it is at least 5000 but below 15000".

    Design: Difficulty/transitive_cascade/complete_order_challenge_bonus_tier_depth3
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Bowl2900", base_price_cents=1450, base_calories=600)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])
    challenge = validate_success(
        api.create_loyalty_challenge(
            create_loyalty_challenge_payload(customer["id"], target_order_count=1, bonus_points=5000),
            make_customer_headers(customer["id"])), 201)

    create_completed_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=2)

    ch = get_challenge(challenge["id"])
    account = get_loyalty_account(customer["loyalty_account_id"])
    assert ch["status"] == "ROUND_COMPLETE"
    assert ch["rounds_completed"] == 1
    assert account["lifetime_points_earned"] == 5290
    assert account["tier"] == "GOLD"


def test_complete_order_challenge_bonus_credits_points_balance(api):
    """PRD §3.6: "That bonus entry, being an earning entry, itself recomputes the account's
    `points_balance`, `lifetime_points_earned`, and `tier` — a three-deep cascade running from
    order completion, through the round-completion bonus, into the loyalty-account recomputation."
    PRD §3.6: "an `EARN` ledger entry with `delta_points` equal to `points_earned` is appended,
    and the account's `points_balance`, `lifetime_points_earned`, and `tier` are recomputed."

    Design: Difficulty/transitive_cascade/complete_order_challenge_bonus_tier_depth3
    """
    # base earn 290 (subtotal 2900) + challenge bonus 5000 = points_balance 5290.
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Bowl2900", base_price_cents=1450, base_calories=600)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])
    validate_success(
        api.create_loyalty_challenge(
            create_loyalty_challenge_payload(customer["id"], target_order_count=1, bonus_points=5000),
            make_customer_headers(customer["id"])), 201)

    create_completed_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=2)

    account = get_loyalty_account(customer["loyalty_account_id"])
    assert account["points_balance"] == 5290


def test_cancel_placed_order_releases_slot_and_requeues_depth2(api):
    """PRD §3.7: "the slot's `reserved_count` drops by one and its `version` increments by one;
    the store's `queue_status` is recomputed".
    PRD §2.7: "The posture is then `SURGE` when the load ratio is at least 1.0, `BUSY` when it
    is at least 0.70 but below 1.0, and `OPEN` when it is below 0.70."

    Design: Difficulty/transitive_cascade/cancel_placed_order_release_slot_requeue_depth2
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=1)
    item = create_menu_item(store["id"], name="I", base_price_cents=500, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])

    placed, _ = create_and_place_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)
    cancelled = cancel(customer["id"], placed["id"], refund_destination="ORIGINAL")

    slot_after = get_slot(slot["id"])
    store_after = get_store(store["id"])
    assert slot_after["reserved_count"] == 0
    assert store_after["queue_status"] == "OPEN"
    assert cancelled["settlement_status"] == "REFUNDED"


def test_placed_order_saturating_slot_drives_surge(api):
    """PRD §2.7: "The posture is then `SURGE` when the load ratio is at least 1.0, `BUSY` when it
    is at least 0.70 but below 1.0, and `OPEN` when it is below 0.70."
    PRD §3.5: "The slot's `reserved_count` rises by one and the slot's `version` increments by
    one."
    PRD §3.5: "Finally the store's `queue_status` is recomputed from the new slot load."

    Design: Difficulty/transitive_cascade/cancel_placed_order_release_slot_requeue_depth2
    """
    # cap 1, one placed order -> reserved_count 1 -> ratio 1.0 -> SURGE.
    store = create_store(state_code="TX", throughput_capacity_per_slot=1)
    item = create_menu_item(store["id"], name="I", base_price_cents=500, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])

    create_and_place_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)

    slot_after = get_slot(slot["id"])
    store_after = get_store(store["id"])
    assert slot_after["reserved_count"] == 1
    assert store_after["queue_status"] == "SURGE"


def test_cancel_restores_points_balance_invariant(api):
    """PRD §3.7: "if `points_redeemed` was positive, a compensating `ADJUSTMENT` ledger entry
    with `delta_points` equal to the positive of `points_redeemed` is appended so the
    `points_balance` is restored".

    Design: Difficulty/compensating_invariant/cancel_restores_points_balance_invariant
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Bowl", base_price_cents=1450, base_calories=600)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])
    seed_points(customer["loyalty_account_id"], 500)

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=2)
    placed = place(customer["id"], order["id"], slot["version"], points_redeemed=300)
    cancelled = cancel(customer["id"], placed["id"], refund_destination="ORIGINAL")

    account = get_loyalty_account(customer["loyalty_account_id"])
    assert account["points_balance"] == 500
    assert cancelled["settlement_status"] == "REFUNDED"


def test_place_redeem_debits_points_balance_before_cancel(api):
    """PRD §3.5: "If `points_redeemed` is positive, a ledger entry with `delta_points` equal to
    the negative of `points_redeemed` and `reason` `REDEEM` is appended and the account's
    `points_balance` is recomputed."

    Design: Difficulty/compensating_invariant/cancel_restores_points_balance_invariant
    """
    # seed 500, place redeeming 300 -> REDEEM -300 -> balance 200 (the debit half of the invariant).
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Bowl", base_price_cents=1450, base_calories=600)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])
    seed_points(customer["loyalty_account_id"], 500)

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=2)
    place(customer["id"], order["id"], slot["version"], points_redeemed=300)

    account = get_loyalty_account(customer["loyalty_account_id"])
    assert account["points_balance"] == 200


def test_cancel_restores_wallet_credit_invariant(api):
    """PRD §3.7: "the `wallet_applied_cents` is re-credited to the customer's
    `wallet_credit_cents`, and the charged amount is refunded according to the request's
    `refund_destination`".

    Design: Difficulty/compensating_invariant/cancel_restores_wallet_credit_invariant
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Bowl", base_price_cents=1450, base_calories=600)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])
    seed_wallet(customer["id"], 500)

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=2)
    placed = place(customer["id"], order["id"], slot["version"], points_redeemed=0)
    cancelled = cancel(customer["id"], placed["id"], refund_destination="ORIGINAL")

    refreshed = get_customer(customer["id"])
    assert refreshed["wallet_credit_cents"] == 500
    assert cancelled["settlement_status"] == "REFUNDED"


def test_place_apply_wallet_debits_credit_before_cancel(api):
    """PRD §3.5: "The customer's `wallet_credit_cents` is debited by `wallet_applied_cents`."

    Design: Difficulty/compensating_invariant/cancel_restores_wallet_credit_invariant
    """
    # seed 500 wallet, place applies all 500 to a 2900-subtotal order -> wallet debited to 0.
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Bowl", base_price_cents=1450, base_calories=600)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])
    seed_wallet(customer["id"], 500)

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=2)
    placed = place(customer["id"], order["id"], slot["version"], points_redeemed=0)

    refreshed = get_customer(customer["id"])
    assert placed["wallet_applied_cents"] == 500
    assert refreshed["wallet_credit_cents"] == 0


def test_order_initial_state_is_cart(api):
    """PRD §3.4: "A fresh order begins with `order_status` of `CART` and `settlement_status`
    of `UNSETTLED`, and all of its computed pricing fields at 0."

    Design: Corner/state_machines/order_initial_state_is_cart
    """
    store = create_store()
    slot = create_pickup_slot(store["id"])
    customer = create_customer(store["id"])

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    assert order["order_status"] == "CART"
    assert order["settlement_status"] == "UNSETTLED"


def test_place_slot_reservation_side_effect(api):
    """PRD §3.5: "The slot's `reserved_count` rises by one and the slot's `version` increments
    by one."
    PRD §3.5: "The order's `settlement_status` moves to `CAPTURED`".

    Design: Corner/state_machines/place_slot_reservation_side_effect
    """
    store, item, slot, customer = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})

    placed, _ = create_and_place_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)

    slot_after = get_slot(slot["id"])
    assert slot_after["reserved_count"] == 1
    assert slot_after["version"] == 2
    assert placed["settlement_status"] == "CAPTURED"


def test_challenge_round_two_cycle_resets_progress(api):
    """PRD §3.10: "A customer starts the next round on a challenge that is `ROUND_COMPLETE`,
    which returns it to `IN_PROGRESS` and resets `progress_count` to 0 as the new round's
    baseline".

    Design: Corner/cross_cutting_layers/challenge_round_two_cycle_resets_progress
    """
    store, item, slot, customer = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})
    challenge = validate_success(
        api.create_loyalty_challenge(
            create_loyalty_challenge_payload(customer["id"], target_order_count=1, bonus_points=500),
            make_customer_headers(customer["id"])), 201)

    create_completed_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)
    restarted = validate_success(
        api.start_challenge_round(challenge["id"], make_customer_headers(customer["id"])), 200)

    assert restarted["status"] == "IN_PROGRESS"
    assert restarted["progress_count"] == 0
    assert restarted["rounds_completed"] == 1
