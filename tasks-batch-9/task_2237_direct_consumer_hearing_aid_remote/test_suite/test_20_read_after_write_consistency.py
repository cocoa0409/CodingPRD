"""Read-after-write consistency: every cascade and every side effect a request
commits — including side effects that accompany a 4xx — is visible to the very
next read, because nothing is deferred to a background worker.
"""
from test_helpers import (
    ADMIN,
    CARE_OPS,
    ApiErrorId,
    assert_inventory_conservation,
    get_pool,
    set_clock,
    setup_active_care_plan,
    setup_authorized_order,
    validate_error,
    validate_paginated,
    validate_success,
)

# The canonical order economics used by both scenarios.
ORDER_OVERRIDES = {
    "list_price_cents": 200000,
    "discount_cents": 0,
    "accessory_subtotal_cents": 0,
    "shipping_cents": 1495,
}


def test_confirm_fit_response_and_immediately_following_reads_agree(api):
    """PRD §2.8: "All cascades run synchronously inside the request that triggers them; nothing is deferred to a background worker. When a transition dirties a derived field, that field is recomputed before the response is emitted."
    PRD §3.5: "Confirmation moves the fulfillment dimension `PENDING_FIT_CONFIRM → READY_TO_SHIP`, reserves a unit by decrementing that pool's `on_hand_units` by one and incrementing its `reserved_units` by one, assigns an `IN_STOCK` device of the same model by moving that device to `ASSIGNED` and writing the order's identity into the device's `device_order_id`, and increments the order's `version` by one."
    PRD §2.6: "And every `InventoryPool` satisfies an **inventory-conservation identity**: `on_hand_units` plus `reserved_units` plus `dispatched_units` always equals `total_units_received`."

    Design: Corner/consistency_model/consistency_immediate_confirm_fit_response_and_reads_agree
    """
    env = setup_authorized_order(order_overrides=dict(ORDER_OVERRIDES), restock_units=5)
    order_id = env["order"]["id"]
    pool_id = env["pool"]["id"]

    confirmed = validate_success(api.confirm_fit(order_id, CARE_OPS))

    assert confirmed["fulfillment_status"] == "READY_TO_SHIP", (
        "the confirm-fit response itself already carries the new fulfillment status"
    )

    pool_after = get_pool(pool_id)
    assert pool_after["on_hand_units"] == 4, (
        f"the reserved unit must already be off the shelf on the next read, got {pool_after['on_hand_units']}"
    )
    assert pool_after["reserved_units"] == 1, (
        f"the reservation must already be visible on the next read, got {pool_after['reserved_units']}"
    )
    assert_inventory_conservation(pool_after)

    assigned, assigned_meta = validate_paginated(
        api.list_devices(CARE_OPS, params={"device_order_id": order_id})
    )
    assert assigned_meta["total_count"] == 1, (
        "the assigned device must already be linked to the order on the next read, "
        f"got {assigned_meta['total_count']} linked devices"
    )
    device_id = assigned[0]["id"]

    device_after = validate_success(api.get_device(device_id, CARE_OPS))
    assert device_after["status"] == "ASSIGNED", (
        f"the assigned device must already read ASSIGNED, got {device_after['status']!r}"
    )
    assert device_after["device_order_id"] == order_id, (
        "the device must already carry the order's identity"
    )

    order_after = validate_success(api.get_device_order(order_id, CARE_OPS))
    assert order_after["fulfillment_status"] == "READY_TO_SHIP", (
        "a re-read of the order agrees with the trigger response — no read-your-writes anomaly"
    )
    assert order_after["version"] == confirmed["version"], (
        "the version observed in the response is the version a following read returns"
    )


def test_declined_billing_cycle_commits_dunning_state_visible_on_the_next_read(api):
    """PRD §2.8: "All cascades run synchronously inside the request that triggers them; nothing is deferred to a background worker."
    PRD §2.9: "The simulated charge outcome is a success for the amount due after credits, on `POST /care-plan-subscriptions/{id}/run-billing-cycle` and `POST /care-plan-subscriptions/{id}/retry-payment` — otherwise `ERR_PAYMENT_DECLINED` (402)."
    PRD §3.8: "On a declined instrument, with `last_charge_cents` exceeding `credit_balance_cents`, the plan moves `ACTIVE → PAST_DUE` with `dunning_attempts` set to 1 and — importantly — `cycle_ordinal` **not** incremented, which is why a past-due episode never advances the loyalty tier."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/consistency_model/consistency_immediate_state_changes_accompanying_a_4xx_are_visible_at_once
    """
    env = setup_active_care_plan(
        order_overrides=dict(ORDER_OVERRIDES),
        plan_overrides={"plan_tier": "STANDARD", "base_fee_cents": 9900, "firmware_auto_update_enabled": True},
        restock_units=5,
    )
    plan_id = env["plan"]["id"]
    order_id = env["order"]["id"]
    assert env["plan"]["status"] == "ACTIVE", "delivery must have activated the trialing plan"
    set_clock("2026-08-31T00:00:00Z")

    resp = api.run_billing_cycle(plan_id, {"charge_outcome": "DECLINED"}, ADMIN)

    error_data = validate_error(resp, ApiErrorId.ERR_PAYMENT_DECLINED.value)
    assert set(error_data.keys()) == {"error_id", "message"}, (
        f"an error envelope carries only error_id and message, got {sorted(error_data.keys())}"
    )

    plan_after = validate_success(api.get_care_plan_subscription(plan_id, CARE_OPS))
    assert plan_after["status"] == "PAST_DUE", (
        f"the declined cycle must already read PAST_DUE on the first read, got {plan_after['status']!r}"
    )
    assert plan_after["dunning_attempts"] == 1, (
        f"a declined cycle sets dunning_attempts to 1, got {plan_after['dunning_attempts']}"
    )
    assert plan_after["cycle_ordinal"] == 0, (
        f"a past-due episode does not advance cycle_ordinal, got {plan_after['cycle_ordinal']}"
    )
    assert plan_after["credit_balance_cents"] == 0, (
        f"the failed cycle consumed no credit, got {plan_after['credit_balance_cents']}"
    )

    order_after = validate_success(api.get_device_order(order_id, CARE_OPS))
    assert order_after["fulfillment_status"] == "DELIVERED", (
        "the billing failure is scoped to the subscription and leaves the order delivered"
    )
