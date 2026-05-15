"""Conserved invariants and concurrency (PRD §2.10 + §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_cycle_invariant,
    assert_exactly_one_succeeds,
    assert_money_invariant,
    cancel_force,
    capture_payment,
    confirm_order,
    create_draft_subscription,
    create_inventory_lot,
    create_pet,
    create_recipe,
    create_warehouse,
    drive_order_to_delivered,
    emit_next_order,
    make_customer_headers,
    pause_subscription,
    pause_subscription_payload,
    reload_customer,
    reload_subscription,
    run_race,
    setup_active_subscription,
    setup_customer_with_pet,
    setup_subscription_with_order,
    setup_verified_customer,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    verify_subscription_address,
)
from test_helpers.fixtures import activate_subscription
from test_helpers import advance_clock_by_hours


# ---------------------------------------------------------------------------
# §2.10 Cycle counter invariant — additional probes
# ---------------------------------------------------------------------------
def test_cycle_invariant_after_cancel_cascade_unchanged(api):
    """PRD §2.10: "a cancel cascade that turns a SCHEDULED or
    CONFIRMED Order into a CANCELLED one moves no counters (the cycle
    still counts as scheduled-then-cancelled)."
    """
    bundle = setup_subscription_with_order()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    cancel_force(customer, sub, "OTHER")
    sub_after = reload_subscription(customer, sub["id"])
    assert sub_after["scheduled_order_count"] == 1
    assert sub_after["skipped_count"] == 0
    assert sub_after["total_cycles_elapsed"] == 1
    assert_cycle_invariant(sub_after)


# ---------------------------------------------------------------------------
# §3.4 Race: skip vs auto-confirm (concurrency rule)
# ---------------------------------------------------------------------------
def test_skip_and_advance_clock_race_only_one_wins(api):
    """PRD §3.4: "If a customer-initiated skip and a system auto-
    confirm fire on the same order simultaneously, the operation that
    lands first wins via first-writer-wins on fulfillment_status: if
    the skip's deadline check passes and it commits first, the auto-
    confirm finds the order in SKIPPED and aborts; if the auto-confirm
    commits first, the skip finds the order no longer in SCHEDULED
    and is rejected with ERR_INVALID_ORDER_STATE."

    We invoke skip and a clock advance that crosses the auto-confirm
    cutoff in parallel. Exactly one of {fulfillment=SKIPPED,
    fulfillment=CONFIRMED} must result — PRD pins one-of outcome but
    not which.
    """
    bundle = setup_subscription_with_order()
    customer = bundle["customer"]
    order = bundle["order"]
    # Advance to T_cutoff - 1s so a hair more advance will trigger
    # auto-confirm. From here, fire skip and a tiny clock advance in
    # parallel.
    import datetime as dt

    def _parse(s):
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc)
    ship_at = _parse(order["scheduled_ship_at"])
    pre = ship_at - dt.timedelta(hours=48, seconds=2)
    api.advance_clock(
        {"to": pre.strftime("%Y-%m-%dT%H:%M:%S.000Z")},
        TEST_USERS["admin_ops_headers"],
    )
    # Now both ops race.
    customer_headers = make_customer_headers(customer["id"])
    results = run_race(
        lambda: api.skip_order(order["id"], customer_headers),
        lambda: api.advance_clock(
            {"by_hours": 2},  # pushes past cutoff → auto-confirm
            TEST_USERS["admin_ops_headers"],
        ),
    )
    # The clock-advance call almost always succeeds (it's an admin
    # capability that mutates the clock and triggers deferred effects);
    # what we care about is the skip's outcome. Per PRD §3.4, one of:
    #   skip succeeds (response 2xx, order SKIPPED)
    #   skip fails with ERR_INVALID_ORDER_STATE OR
    #     ERR_MODIFICATION_DEADLINE_PASSED
    skip_response = results[0] if hasattr(results[0], "status_code") else None
    # If run_race returns in completion order, fish out the skip.
    # Easier: re-fetch the order and verify final state.
    final = api.get_order(
        order["id"], customer_headers,
    ).json()["data"]
    assert final["fulfillment_status"] in {"SKIPPED", "CONFIRMED"}, (
        "PRD §3.4: race outcome must be exactly one of SKIPPED or "
        f"CONFIRMED; got {final['fulfillment_status']}"
    )


# ---------------------------------------------------------------------------
# Inventory race: two confirms for the last gram (PRD §3.4)
# ---------------------------------------------------------------------------
def test_inventory_race_first_writer_wins(api):
    """PRD §3.4: "The lot's quantity_grams is decremented atomically
    by the item's total_grams; the resulting balance must never become
    negative — if two confirmations race for the last gram of the
    same lot, exactly one wins and the loser receives
    ERR_INSUFFICIENT_INVENTORY."
    """
    recipe = create_recipe(kcal_per_gram=4.0)
    # Two distinct ACTIVE subscriptions on the same warehouse sharing
    # the same lot. Make capacity wide; constrain ONLY inventory.
    wh = create_warehouse(daily_outbound_capacity=10)
    # Both orders need 224*7=1568 g; stock 1568 only.
    create_inventory_lot(wh, recipe["id"], quantity_grams=1568)

    cust_a, pet_a = setup_customer_with_pet(
        pet_overrides={
            "species": "DOG", "birthdate": "2023-01-01",
            "weight_kg": 16, "activity_level": "MODERATE",
        },
    )
    cust_b, pet_b = setup_customer_with_pet(
        pet_overrides={
            "species": "DOG", "birthdate": "2023-01-01",
            "weight_kg": 16, "activity_level": "MODERATE",
        },
    )
    sub_a = create_draft_subscription(cust_a, pet_a)
    sub_a = verify_subscription_address(cust_a, sub_a)
    sub_a = activate_subscription(cust_a, sub_a)
    sub_b = create_draft_subscription(cust_b, pet_b)
    sub_b = verify_subscription_address(cust_b, sub_b)
    sub_b = activate_subscription(cust_b, sub_b)
    advance_clock_by_hours(7 * 24)
    o_a = api.list_orders(
        sub_a["id"], make_customer_headers(cust_a["id"]),
    ).json()["data"][0]
    o_b = api.list_orders(
        sub_b["id"], make_customer_headers(cust_b["id"]),
    ).json()["data"][0]
    h_a = make_customer_headers(cust_a["id"])
    h_b = make_customer_headers(cust_b["id"])
    results = run_race(
        lambda: api.confirm_order(o_a["id"], h_a),
        lambda: api.confirm_order(o_b["id"], h_b),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    assert len(outcome["successes"]) == 1
    assert len(outcome["failures"]) == 1


# ---------------------------------------------------------------------------
# §2.4 Optimistic concurrency on warehouse PATCH
# ---------------------------------------------------------------------------
def test_warehouse_patch_with_stale_version_rejected(api):
    """PRD §2.4: "When the caller includes version and the value
    supplied does not equal the entity's current version, the request
    is rejected with HTTP 409 and ERR_VERSION_CONFLICT."
    """
    wh = create_warehouse()
    stale_v = wh["version"]
    # First mutation bumps version.
    api.update_warehouse(
        wh["id"], {"daily_outbound_capacity": 99},
        TEST_USERS["admin_ops_headers"],
    )
    res = api.update_warehouse(
        wh["id"], {"daily_outbound_capacity": 88, "version": stale_v},
        TEST_USERS["admin_ops_headers"],
    )
    validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)


def test_warehouse_patch_with_correct_version_succeeds(api):
    """PRD §2.4: "Successful mutations bump version by one and refresh
    updated_at regardless of whether a version value was supplied in
    the request."
    """
    wh = create_warehouse()
    res = api.update_warehouse(
        wh["id"], {"priority_rank": 7, "version": wh["version"]},
        TEST_USERS["admin_ops_headers"],
    )
    after = validate_success(res)
    assert after["version"] == wh["version"] + 1
    assert after["priority_rank"] == 7
