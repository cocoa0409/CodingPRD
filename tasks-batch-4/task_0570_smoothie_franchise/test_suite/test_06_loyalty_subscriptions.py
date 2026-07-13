"""Loyalty cascade on pay, subscription cyclic recovery, and OCC on subscriptions/stores."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_franchisee, create_store, create_open_store,
    create_ingredient, create_inventory_lot, create_menu_item,
    create_customer, create_subscription, setup_order_env,
    place_order, pay_order, order_line,
    make_customer_headers,
    create_order_payload, create_subscription_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/pay_earn_points_balance_tier_upgrade
# ---------------------------------------------------------------------------

def _pay_500_dollar_bundle(api):
    fr, st = create_open_store(api)
    ing = create_ingredient(api, name="Acai")
    create_inventory_lot(api, st["id"], ing["id"], qty_received=100, unit_cost_cents=2)
    mi = create_menu_item(api, name="Wellness Bundle", category="WELLNESS_PACK",
                          base_price_cents=50000,
                          recipe=[{"ingredient_id": ing["id"], "base_qty": 1}], base_calories=900)
    cust = create_customer(api, email="c7@x.com", full_name="C Seven")
    order = place_order(api, st["id"], cust["id"], [order_line(mi["id"], "SMALL")])
    paid = pay_order(api, order["id"], cust["id"])
    customer_after = validate_success(api.get_customer(cust["id"], make_customer_headers(cust["id"])))
    return paid, customer_after


def test_pay_grants_points_and_balance(api):
    """PRD §3.6: "The `points_earned` is the floor of `discounted_subtotal_cents` divided
    by 100 — one point per whole dollar of the pre-tax discounted subtotal — and is
    written as an `EARN` points transaction of `+points_earned`, cascading through the
    customer's `points_balance`, `lifetime_points_earned`, and `loyalty_tier`."

    Design: Difficulty/transitive_cascade/pay_earn_points_balance_tier_upgrade
    """
    paid, customer_after = _pay_500_dollar_bundle(api)
    assert paid["points_earned"] == 500, f"Expected points_earned 500, got {paid['points_earned']}"
    assert customer_after["points_balance"] == 500, (
        f"Expected balance 500, got {customer_after['points_balance']}"
    )


def test_pay_cascades_to_silver_tier(api):
    """PRD §3.3: "a lifetime of at least 1500 points yields `GOLD`, at least 500 (but
    under 1500) yields `SILVER`, and anything below 500 is `BRONZE`. The boundary is
    inclusive on the lower edge — exactly 500 lifetime points is `SILVER`, and exactly
    1500 is `GOLD`."

    Design: Difficulty/transitive_cascade/pay_earn_points_balance_tier_upgrade
    """
    paid, customer_after = _pay_500_dollar_bundle(api)
    assert customer_after["lifetime_points_earned"] == 500, (
        f"Expected lifetime 500, got {customer_after['lifetime_points_earned']}"
    )
    assert customer_after["loyalty_tier"] == "SILVER", (
        f"Expected SILVER at lifetime 500, got {customer_after['loyalty_tier']}"
    )


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/subscription_cyclic_past_due_recovery
# ---------------------------------------------------------------------------

def test_failed_renewal_moves_active_to_past_due(api):
    """PRD §3.4: "Renewing an `ACTIVE` subscription with a failed outcome moves it
    `ACTIVE → PAST_DUE`: no credit reset and no bonus are granted."

    Design: Difficulty/non_linear_state_machine/subscription_cyclic_past_due_recovery
    """
    cust = create_customer(api, email="c6@x.com", full_name="C Six")
    sub = create_subscription(api, cust["id"], tier="BASIC", monthly_fee_cents=999,
                              included_smoothie_credits=4)
    resp = api.renew_subscription(sub["id"], {"payment_outcome": "FAIL"}, ADMIN)
    data = validate_success(resp)
    assert data["status"] == "PAST_DUE", f"Expected PAST_DUE, got {data['status']}"


def test_successful_renewal_recovers_past_due_to_active(api):
    """PRD §3.4: "Renewing a `PAST_DUE` subscription with a successful outcome recovers it
    `PAST_DUE → ACTIVE`, applying the same effects as a successful active renewal:
    `cycle_index` increases by one, `credits_remaining` resets to `included_smoothie_credits`,
    and the `+renewal_bonus_points` subscription bonus is granted with the same loyalty
    cascade."

    Design: Difficulty/non_linear_state_machine/subscription_cyclic_past_due_recovery
    """
    admin = ADMIN
    cust = create_customer(api, email="c6b@x.com", full_name="C Six B")
    sub = create_subscription(api, cust["id"], tier="BASIC", monthly_fee_cents=999,
                              included_smoothie_credits=4)
    validate_success(api.renew_subscription(sub["id"], {"payment_outcome": "FAIL"}, admin))
    data = validate_success(api.renew_subscription(sub["id"], {"payment_outcome": "SUCCESS"}, admin))
    assert data["status"] == "ACTIVE", f"Expected ACTIVE, got {data['status']}"
    assert data["cycle_index"] == 2, f"Expected cycle_index 2, got {data['cycle_index']}"
    assert data["credits_remaining"] == 4, (
        f"Expected credits reset to 4, got {data['credits_remaining']}"
    )


# ---------------------------------------------------------------------------
# Corner/validations/second_subscription_returns_subscription_exists
# ---------------------------------------------------------------------------

def test_second_subscription_returns_subscription_exists(api):
    """PRD §3.4: "A customer may hold at most one non-cancelled **Subscription** at a
    time; an attempt to start a second while one is still active or past due is rejected
    with `ERR_SUBSCRIPTION_EXISTS`."

    Design: Corner/validations/second_subscription_returns_subscription_exists
    """
    cust = create_customer(api, email="x2@x.com", full_name="Ex")
    create_subscription(api, cust["id"], tier="BASIC", monthly_fee_cents=999,
                        included_smoothie_credits=4)
    resp = api.create_subscription(
        cust["id"],
        create_subscription_payload(tier="PREMIUM", monthly_fee_cents=1999,
                                    included_smoothie_credits=8),
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_EXISTS.value)


# ---------------------------------------------------------------------------
# Corner/validations/credit_without_active_subscription_returns_no_active_subscription
# ---------------------------------------------------------------------------

def test_credit_without_active_subscription_rejected(api):
    """PRD §3.5: "if `use_subscription_credit` is set but the customer has no subscription
    in `ACTIVE` status, the request is rejected with `ERR_NO_ACTIVE_SUBSCRIPTION`."

    Design: Corner/validations/credit_without_active_subscription_returns_no_active_subscription
    """
    env = setup_order_env(api)
    st, cust, mi = env["store"], env["customer"], env["menu_item"]
    sub = create_subscription(api, cust["id"], tier="BASIC", monthly_fee_cents=999,
                              included_smoothie_credits=4)
    validate_success(api.cancel_subscription(sub["id"], make_customer_headers(cust["id"])))
    resp = api.create_order(
        create_order_payload(st["id"], [order_line(mi["id"], "SMALL")], use_subscription_credit=True),
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_SUBSCRIPTION.value)


# ---------------------------------------------------------------------------
# Corner/cross_cutting/subscription_change_plan_stale_version_returns_412
# ---------------------------------------------------------------------------

def test_subscription_change_plan_stale_version_returns_412(api):
    """PRD §2.6: "If `expected_subscription_version` does not equal the subscription's
    current `version` — because a prior plan change has already superseded the plan and
    advanced the version — the change is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/subscription_change_plan_stale_version_returns_412
    """
    cust = create_customer(api, email="cp@x.com", full_name="See Pea")
    sub = create_subscription(api, cust["id"], tier="BASIC", monthly_fee_cents=999,
                              included_smoothie_credits=4)
    stale_version = sub["version"]
    headers = make_customer_headers(cust["id"])
    validate_success(api.change_plan(sub["id"], {
        "expected_subscription_version": stale_version,
        "tier": "PREMIUM", "monthly_fee_cents": 1999, "included_smoothie_credits": 8,
    }, headers))
    resp = api.change_plan(sub["id"], {
        "expected_subscription_version": stale_version,
        "tier": "BASIC", "monthly_fee_cents": 999, "included_smoothie_credits": 4,
    }, headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# Corner/cross_cutting/store_config_stale_version_returns_412
# ---------------------------------------------------------------------------

def test_store_config_stale_version_returns_412(api):
    """PRD §2.6: "If `expected_store_version` does not equal the store's current `version`
    — because another configuration write has advanced it since the client last read the
    store — the update is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/store_config_stale_version_returns_412
    """
    admin = ADMIN
    fr = create_franchisee(api)
    store = create_store(api, fr["id"], catering_capacity=10)  # version 1
    stale_version = store["version"]
    validate_success(api.update_store(store["id"], {
        "expected_store_version": stale_version, "status": "OPEN",
    }, admin))
    resp = api.update_store(store["id"], {
        "expected_store_version": stale_version, "catering_capacity": 20,
    }, admin)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
