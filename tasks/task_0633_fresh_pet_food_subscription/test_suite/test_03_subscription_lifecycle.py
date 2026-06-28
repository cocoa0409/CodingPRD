"""Subscription state machine: pause/resume cycle, skip vs charge branching, invalid
transitions, terminal lockdown, the cancel-to-skipped cascade, and the skip cross-entity guard."""
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
    generate_order,
    charge_order,
    settle_order,
    get_subscription_version,
    ApiErrorId,
)

BILLING = TEST_USERS["billing_admin_headers"]


def test_subscription_active_paused_active_cycle(api):
    """PRD §3.6: "On success the subscription transitions `ACTIVE → PAUSED`; `pause_until` is set
    to the supplied `resume_at`, or to null for an indefinite pause when none is supplied".
    PRD §3.6: "Resuming requires the subscription be `PAUSED` (otherwise
    `ERR_SUBSCRIPTION_NOT_PAUSED`); it transitions `PAUSED → ACTIVE`, clears `pause_until` to null".

    Design: Difficulty/non_linear_state_machine/subscription_active_paused_active_cycle
    """
    account, pet, recipe, sub = setup_active_subscription("nl-1@x.com")
    headers = make_pet_parent_headers(account["id"])

    paused = validate_success(api.pause_subscription(sub["id"], headers), 200)
    assert paused["status"] == "PAUSED", paused["status"]

    resumed = validate_success(api.resume_subscription(sub["id"], headers), 200)
    assert resumed["status"] == "ACTIVE", resumed["status"]
    assert resumed["pause_until"] is None, resumed["pause_until"]


def test_order_skip_branch_advances_without_charge(api):
    """PRD §3.6: "A `PetParent` may skip a `SCHEDULED` order to forgive one cycle without charge."
    PRD §3.6: "On success the order transitions `SCHEDULED → SKIPPED`, the subscription's
    `next_order_date` advances by `cadence_days`, and the subscription's version increments."

    Design: Difficulty/non_linear_state_machine/order_branching_skip_vs_charge_divergent_side_effects
    """
    account, pet, recipe, sub, order = setup_active_subscription_with_order("nl-2@x.com")
    headers = make_pet_parent_headers(account["id"])
    # Keep clock strictly before ship date so the skip window is open.
    set_clock("2025-12-31T00:00:00Z")
    skipped = validate_success(api.skip_order(order["id"], headers), 200)
    assert skipped["status"] == "SKIPPED", skipped["status"]
    assert skipped["total_charged_cents"] == 0, skipped["total_charged_cents"]


def test_activate_already_active_subscription_rejected(api):
    """PRD §3.5: "Activation requires the subscription be in `DRAFT`, otherwise
    `ERR_SUBSCRIPTION_NOT_DRAFT`".

    Design: Corner/state_machines/activate_already_active_subscription_returns_not_draft
    """
    account, pet, recipe, sub = setup_active_subscription("sm-1@x.com")
    headers = make_pet_parent_headers(account["id"])
    res = api.activate_subscription(sub["id"], headers)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_DRAFT.value)


def test_resume_active_subscription_rejected(api):
    """PRD §3.6: "Resuming requires the subscription be `PAUSED` (otherwise
    `ERR_SUBSCRIPTION_NOT_PAUSED`)".

    Design: Corner/state_machines/resume_active_subscription_returns_not_paused
    """
    account, pet, recipe, sub = setup_active_subscription("sm-2@x.com")
    headers = make_pet_parent_headers(account["id"])
    res = api.resume_subscription(sub["id"], headers)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_PAUSED.value)


def test_cancel_already_cancelled_subscription_rejected(api):
    """PRD §3.6: "cancelling one already cancelled is rejected with
    `ERR_SUBSCRIPTION_ALREADY_CANCELLED`".

    Design: Corner/state_machines/cancel_terminal_subscription_returns_already_cancelled
    """
    account, pet, recipe, sub = setup_active_subscription("sm-3@x.com")
    headers = make_pet_parent_headers(account["id"])
    validate_success(api.cancel_subscription(sub["id"], headers), 200)
    res = api.cancel_subscription(sub["id"], headers)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_ALREADY_CANCELLED.value)


def test_cancel_cascades_scheduled_orders_to_skipped(api):
    """PRD §3.6: "On success the subscription moves to `CANCELLED` (terminal) and the cancellation
    cascades: every `SCHEDULED` order for the subscription is moved to `SKIPPED` (only the
    non-terminal scheduled orders are touched)".

    Design: Corner/state_machines/subscription_cancel_cascades_scheduled_orders_to_skipped
    """
    account, pet, recipe, sub, order = setup_active_subscription_with_order("sm-5@x.com")
    headers = make_pet_parent_headers(account["id"])
    cancelled = validate_success(api.cancel_subscription(sub["id"], headers), 200)
    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    order_after = get_success_data(api.get_order(order["id"], headers))
    assert order_after["status"] == "SKIPPED", order_after["status"]


def test_skip_order_on_past_due_subscription_rejected(api):
    """PRD §3.6: "Skipping requires the order be `SCHEDULED` (otherwise `ERR_ORDER_NOT_SCHEDULED`),
    requires the parent subscription be `ACTIVE` or `PAUSED` (otherwise
    `ERR_SUBSCRIPTION_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/order_skip_requires_subscription_active_or_paused
    """
    account, pet, recipe, sub = setup_active_subscription("ce-2@x.com")
    headers = make_pet_parent_headers(account["id"])
    # Generate two orders; decline the first to push the subscription PAST_DUE,
    # leaving order #2 SCHEDULED.
    sub_v0 = get_subscription_version(sub["id"])
    order1 = generate_order(sub["id"], sub_v0)
    sub_v1 = get_subscription_version(sub["id"])
    order2 = generate_order(sub["id"], sub_v1)
    charge_order(order1["id"])
    settle_order(order1["id"], "DECLINED")

    sub_after = get_success_data(api.get_subscription(sub["id"], BILLING))
    assert sub_after["status"] == "PAST_DUE", sub_after["status"]

    res = api.skip_order(order2["id"], headers)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value)


def test_skip_on_or_after_ship_date_rejected(api):
    """PRD §3.6: "requires that the current clock date be strictly before the order's
    `scheduled_ship_date` — once the ship day arrives or passes, skipping is closed and the
    request is rejected with `ERR_SKIP_WINDOW_CLOSED`."

    Design: Corner/errors/skip_window_closed_returns_422
    """
    account, pet, recipe, sub, order = setup_active_subscription_with_order(
        "er-7@x.com", sub_overrides={"cadence_days": 28}
    )
    headers = make_pet_parent_headers(account["id"])
    # next_order_date == clock == ship date 2026-01-01; clock is on the ship day.
    res = api.skip_order(order["id"], headers)
    validate_error(res, ApiErrorId.ERR_SKIP_WINDOW_CLOSED.value)
