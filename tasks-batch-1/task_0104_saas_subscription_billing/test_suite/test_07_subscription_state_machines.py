"""Subscription / account / pause-window state-machine transitions.

Queue B (corner) translations for the state_machines section. The
dunning_exhaustion_cancel_cascade instance is an excluded_because stub — its
cascade is owned by the transitive_cascade difficulty instance — so it is
not translated here.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    make_account_owner_headers,
    TEST_USERS,
    create_pause_window_payload,
    setup_active_subscription,
    setup_trialing_subscription,
    setup_subscription_with_pause_window,
)

ADMIN = TEST_USERS["billing_admin_headers"]


def _owner(account_id):
    return make_account_owner_headers(account_id)


def test_cancel_already_canceled_subscription_returns_invalid_state(api):
    """PRD §3.9: "Either way, a subscription not in the originating state for these transitions is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_already_canceled_subscription_returns_invalid_state
    """
    plan, account, sub = setup_active_subscription(plan_tier="BASIC", email="cc@x.com")
    validate_success(api.cancel_subscription(account["id"], sub["id"], _owner(account["id"])), 200)
    res = api.cancel_subscription(account["id"], sub["id"], _owner(account["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_convert_non_trialing_subscription_returns_invalid_state(api):
    """PRD §3.3: "An `AccountOwner` may convert early, advancing `lifecycle_status` from `TRIALING` to `ACTIVE` while the subscription is still `TRIALING`". PRD §2.7: "returning `ERR_INVALID_STATE` when the target resource is not in a state that permits the requested transition."

    Design: Corner/state_machines/convert_non_trialing_subscription_returns_invalid_state
    """
    # trial_days=0 plan opens the subscription directly ACTIVE, so convert is illegal.
    plan, account, sub = setup_active_subscription(plan_tier="BASIC", email="cv@x.com")
    res = api.convert_subscription(account["id"], sub["id"], _owner(account["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_new_trial_subscription_starts_trialing_with_no_invoice(api):
    """PRD §3.2: "When the plan's `trial_days` is greater than 0, the subscription begins in `TRIALING` with `trial_end` set to the current clock plus `trial_days` days, and no invoice is generated yet". PRD §3.2: "The **billing** dimension, `billing_status`, runs `CURRENT`, `PAST_DUE`, or `UNPAID`".

    Design: Corner/state_machines/new_subscription_with_trial_starts_in_trialing
    """
    plan, account, sub = setup_trialing_subscription(plan_tier="PRO", trial_days=14, email="tr@x.com")
    assert sub["lifecycle_status"] == "TRIALING", f"lifecycle, got {sub['lifecycle_status']}"
    assert sub["billing_status"] == "CURRENT", f"billing, got {sub['billing_status']}"
    _, meta = validate_paginated(api.list_invoices(account["id"], _owner(account["id"])))
    assert meta["total_count"] == 0, f"trial should generate no invoice, got {meta['total_count']}"


def test_close_account_with_settled_subscription_succeeds(api):
    """PRD §3.9: "an `AccountOwner` may **close** their account, moving `status` from `ACTIVE` to `CLOSED` and setting `mrr_cents` to 0." PRD §3.9: "if any subscription on the account is `TRIALING` or `ACTIVE`, the close is rejected with `ERR_ACCOUNT_HAS_ACTIVE_SUBS`; if any invoice on the account is `OPEN` or `PAST_DUE`, it is rejected with `ERR_ACCOUNT_HAS_OPEN_INVOICES`."

    Design: Corner/state_machines/close_account_with_settled_subscription_succeeds
    """
    # trial_days=0 + payment_method_ok -> first invoice PAID (terminal); then cancel.
    plan, account, sub = setup_active_subscription(
        plan_tier="BASIC", email="clok@x.com", payment_method_ok=True
    )
    validate_success(api.cancel_subscription(account["id"], sub["id"], _owner(account["id"])), 200)
    res = api.close_account(account["id"], _owner(account["id"]))
    closed = validate_success(res, 200)
    assert closed["status"] == "CLOSED", f"account status, got {closed['status']}"
    assert closed["mrr_cents"] == 0, f"closed account mrr_cents, got {closed['mrr_cents']}"


def test_cancel_pause_window_frees_timeline_for_overlapping_window(api):
    """PRD §3.9: "Canceling a scheduled pause window moves its `status` from `SCHEDULED` to `CANCELED` (terminal); once canceled the window no longer occupies the timeline, so a future window that would otherwise have conflicted with it may then be scheduled."

    Design: Corner/state_machines/cancel_pause_window_then_overlapping_window_allowed
    """
    account, sub, pw = setup_subscription_with_pause_window(
        pause_from="2026-06-01T00:00:00Z", pause_to="2026-06-10T00:00:00Z", email="pwc@x.com"
    )
    cancel_res = api.cancel_pause_window(account["id"], sub["id"], pw["id"], _owner(account["id"]))
    canceled = validate_success(cancel_res, 200)
    assert canceled["status"] == "CANCELED", f"pause window status, got {canceled['status']}"
    # A window that previously would conflict is now allowed.
    res = api.create_pause_window(
        account["id"],
        sub["id"],
        create_pause_window_payload("2026-06-05T00:00:00Z", "2026-06-12T00:00:00Z"),
        _owner(account["id"]),
    )
    validate_success(res, 201)
