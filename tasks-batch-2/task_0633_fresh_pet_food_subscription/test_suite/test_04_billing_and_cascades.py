"""The billing waterfall: charge/settle/retry, the declined-charge transitive cascade, the
first-paid-order referral grant, the transition-cycle counter floor, and gross conservation."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_pet_parent_headers,
    TEST_USERS,
    set_clock,
    register_account,
    create_pet,
    create_published_recipe,
    create_subscription,
    setup_active_subscription,
    setup_active_subscription_with_order,
    setup_referred_with_active_subscription,
    generate_order,
    charge_order,
    settle_order,
    get_subscription_version,
    assert_settlement_conserves_gross,
    ApiErrorId,
)

BILLING = TEST_USERS["billing_admin_headers"]


def test_declined_charge_cascade_past_due_cancelled_skipped(api):
    """PRD §3.7: "If that increment brings `consecutive_failed_charges` to at least 3, the failure
    cascades transitively: the subscription moves `PAST_DUE → CANCELLED`, all its `SCHEDULED`
    orders are skipped to `SKIPPED`".

    Design: Difficulty/transitive_cascade/declined_charge_to_past_due_to_cancelled_to_skipped_orders_depth3
    """
    account, pet, recipe, sub = setup_active_subscription("tc-1@x.com")
    v0 = get_subscription_version(sub["id"])
    order1 = generate_order(sub["id"], v0)
    v1 = get_subscription_version(sub["id"])
    order2 = generate_order(sub["id"], v1)

    # Attempt 1: charge then decline (consecutive_failed_charges 1, ACTIVE -> PAST_DUE).
    charge_order(order1["id"])
    settle_order(order1["id"], "DECLINED")
    # Attempt 2: retry then decline (-> 2).
    get_success_data(api.retry_charge(order1["id"], BILLING))
    settle_order(order1["id"], "DECLINED")
    # Attempt 3: retry then decline (-> 3 -> CANCELLED cascade).
    get_success_data(api.retry_charge(order1["id"], BILLING))
    settle_order(order1["id"], "DECLINED")

    sub_after = get_success_data(api.get_subscription(sub["id"], BILLING))
    assert sub_after["consecutive_failed_charges"] == 3, sub_after["consecutive_failed_charges"]
    assert sub_after["status"] == "CANCELLED", sub_after["status"]

    order2_after = get_success_data(api.get_order(order2["id"], BILLING))
    assert order2_after["status"] == "SKIPPED", order2_after["status"]


def test_first_paid_order_grants_referral_credit_both_accounts(api):
    """PRD §3.7: "if this is the referred account's first `PAID` order, the linked `PENDING`
    `SIGNUP` referral-credit rows flip to `GRANTED`, cascading into both accounts' wallet and
    lifetime fields".
    PRD §3.8: "the referrer's `lifetime_referral_grants_cents` increases by precisely that row's
    `referrer_grant_cents`, and each beneficiary's `wallet_credit_cents` increases by that row's
    `amount_cents`."

    Design: Difficulty/transitive_cascade/paid_first_order_grants_referral_credit_updates_both_accounts_depth2
    """
    referrer, referred, pet, recipe, sub = setup_referred_with_active_subscription(
        "tc2-r@x.com", "tc2-f@x.com"
    )
    order = generate_order(sub["id"], sub["version"])
    charge_order(order["id"])
    paid = settle_order(order["id"], "SUCCEEDED")
    assert paid["status"] == "PAID", paid["status"]

    acc_f = get_success_data(api.get_account(referred["id"], BILLING))
    acc_r = get_success_data(api.get_account(referrer["id"], BILLING))
    assert acc_f["wallet_credit_cents"] == 2000, acc_f["wallet_credit_cents"]
    assert acc_r["wallet_credit_cents"] == 1500, acc_r["wallet_credit_cents"]
    assert acc_r["lifetime_referral_grants_cents"] == 1500, acc_r["lifetime_referral_grants_cents"]


def test_referral_grant_conserves_lifetime_and_wallet(api):
    """PRD §3.8: "On each such grant, the conserved-quantity rule holds exactly: the referrer's
    `lifetime_referral_grants_cents` increases by precisely that row's `referrer_grant_cents`, and
    each beneficiary's `wallet_credit_cents` increases by that row's `amount_cents`."

    Design: Difficulty/compensating_invariant/referral_grant_conserves_lifetime_and_wallet
    """
    referrer, referred, pet, recipe, sub = setup_referred_with_active_subscription(
        "ci2-r@x.com", "ci2-f@x.com"
    )
    order = generate_order(sub["id"], sub["version"])
    charge_order(order["id"])
    settle_order(order["id"], "SUCCEEDED")

    acc_r = get_success_data(api.get_account(referrer["id"], BILLING))
    acc_f = get_success_data(api.get_account(referred["id"], BILLING))
    assert acc_r["lifetime_referral_grants_cents"] == 1500
    assert acc_r["wallet_credit_cents"] == 1500
    assert acc_f["wallet_credit_cents"] == 2000
    # Total granted (1500 + 2000 == 3500) equals the combined wallet increase.
    assert acc_r["wallet_credit_cents"] + acc_f["wallet_credit_cents"] == 3500


def test_settlement_conserves_gross_with_credit_applied(api):
    """PRD §3.7: "Third, form the gross as `food_subtotal_cents` plus `shipping_cents`. Fourth, set
    `credit_applied_cents` to the smaller of the account's `wallet_credit_cents` at charge time and
    that gross. Fifth, set `total_charged_cents` to the gross minus `credit_applied_cents`, which
    is never negative."

    Design: Difficulty/compensating_invariant/order_charge_settlement_conserves_gross
    """
    referrer, referred, pet, recipe, sub = setup_referred_with_active_subscription(
        "ci1-r@x.com", "ci1-f@x.com"
    )
    # First order: pay it so the referral grant lands 2000 in F's wallet.
    order1 = generate_order(sub["id"], sub["version"])
    charge_order(order1["id"])
    settle_order(order1["id"], "SUCCEEDED")

    # Second cycle (cadence 28 -> ship 2026-01-29): advance clock, generate, charge.
    set_clock("2026-01-29T00:00:00Z")
    v1 = get_subscription_version(sub["id"])
    order2 = generate_order(sub["id"], v1)
    charged = charge_order(order2["id"])

    # subtotal 8004 >= 8000 -> free ship; gross 8004; wallet 2000 -> credit 2000; total 6004.
    assert charged["food_subtotal_cents"] == 8004, charged["food_subtotal_cents"]
    assert charged["shipping_cents"] == 0, charged["shipping_cents"]
    assert charged["credit_applied_cents"] == 2000, charged["credit_applied_cents"]
    assert charged["total_charged_cents"] == 6004, charged["total_charged_cents"]
    assert_settlement_conserves_gross(charged)


def test_transition_remaining_cycles_floors_at_zero(api):
    """PRD §3.5: "The `transition_remaining_cycles` field ... starts at 2 on first activation and
    is decremented by one (floored at 0) each time an order for the subscription is settled paid.
    Any order generated while this counter is still above zero is flagged as a transition cycle."

    Design: Difficulty/boundary_precision_check/transition_remaining_cycles_zero_count_edge
    """
    account, pet, recipe, sub = setup_active_subscription(
        "bp-2@x.com", sub_overrides={"cadence_days": 28}
    )
    v0 = get_subscription_version(sub["id"])
    o1 = generate_order(sub["id"], v0)
    assert o1["is_transition_cycle"] is True, o1["is_transition_cycle"]
    charge_order(o1["id"])
    settle_order(o1["id"], "SUCCEEDED")

    set_clock("2026-01-29T00:00:00Z")
    v1 = get_subscription_version(sub["id"])
    o2 = generate_order(sub["id"], v1)
    assert o2["is_transition_cycle"] is True, o2["is_transition_cycle"]
    charge_order(o2["id"])
    settle_order(o2["id"], "SUCCEEDED")

    set_clock("2026-02-26T00:00:00Z")
    v2 = get_subscription_version(sub["id"])
    o3 = generate_order(sub["id"], v2)
    assert o3["is_transition_cycle"] is False, o3["is_transition_cycle"]

    sub_after = get_success_data(api.get_subscription(sub["id"], BILLING))
    assert sub_after["transition_remaining_cycles"] == 0, sub_after["transition_remaining_cycles"]


def test_charge_before_ship_date_rejected(api):
    """PRD §3.7: "requires the current clock date be on or after the order's `scheduled_ship_date`
    (otherwise `ERR_CHARGE_BEFORE_SHIP_DATE`)".

    Design: Corner/validations/charge_before_ship_date_returns_422
    """
    account, pet, recipe, sub = setup_active_subscription(
        "va-4@x.com", sub_overrides={"cadence_days": 28}
    )
    v0 = get_subscription_version(sub["id"])
    order1 = generate_order(sub["id"], v0)
    charge_order(order1["id"])
    settle_order(order1["id"], "SUCCEEDED")
    # next_order_date advanced to 2026-01-29; order #2 ships 2026-01-29; clock still 2026-01-01.
    v1 = get_subscription_version(sub["id"])
    order2 = generate_order(sub["id"], v1)
    res = api.charge_order(order2["id"], BILLING)
    validate_error(res, ApiErrorId.ERR_CHARGE_BEFORE_SHIP_DATE.value)
