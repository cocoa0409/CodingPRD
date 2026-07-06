"""Subscription lifecycle, pause-window overlap, and optimistic-concurrency plan changes.

Translates the resource-temporal-overlap difficulty instance (pause window, queue A) plus corner
state-machine and cross-cutting concurrency instances (queue B).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, make_customer_headers,
    create_pause_window_payload, create_plan_change_payload,
    setup_cancelled_subscription, setup_subscription_with_pause, setup_subscription_two_plans,
)


def test_cancel_subscription_twice_terminal_lockdown(api):
    """PRD §3.3: "Cancelling a subscription moves it from `ACTIVE` to `CANCELLED` and cascades in
    a single request".
    PRD §2.9: "(4) state validity, that the target resource is in a state from which the
    requested transition is defined, yielding `ERR_INVALID_STATE`".

    Design: Corner/state_machines/cancel_subscription_twice_terminal_lockdown
    """
    ctx = setup_cancelled_subscription(api)  # already CANCELLED (terminal)
    resp = api.cancel_subscription(ctx["sub_id"], make_customer_headers(ctx["cust_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_pause_window_overlap_rejected(api):
    """PRD §3.3: "a new window may not overlap any existing `SCHEDULED` window of the same
    subscription, though windows that merely touch at an endpoint (one ending exactly where the
    next begins) are allowed; an overlapping request is refused with `ERR_PAUSE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pause_window_half_open_overlap
    """
    ctx = setup_subscription_with_pause(api)  # existing SCHEDULED window [2026-03-16, 2026-03-30)
    resp = api.create_pause_window(
        ctx["sub_id"], create_pause_window_payload("2026-03-23", "2026-04-06"),
        make_customer_headers(ctx["cust_id"]))
    validate_error(resp, ApiErrorId.ERR_PAUSE_OVERLAP.value)


def test_pause_window_adjacent_allowed(api):
    """PRD §3.3: "windows that merely touch at an endpoint (one ending exactly where the next
    begins) are allowed".
    PRD §3.3: "The interval is treated as inclusive of `start_date` and exclusive of `end_date`".

    Design: Difficulty/resource_temporal_overlap/pause_window_half_open_overlap
    """
    ctx = setup_subscription_with_pause(api)  # existing window ends (exclusive) at 2026-03-30
    resp = api.create_pause_window(
        ctx["sub_id"], create_pause_window_payload("2026-03-30", "2026-04-13"),
        make_customer_headers(ctx["cust_id"]))
    data = validate_success(resp, 201)  # back-to-back start exactly at prior end -> allowed
    assert data["status"] == "SCHEDULED"


def test_stale_subscription_version_on_plan_change_rejected(api):
    """PRD §2.7: "If that value does not equal the subscription's current `version`, the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412) and no plan change is created."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_subscription_version_on_plan_change
    """
    ctx = setup_subscription_two_plans(api)  # subscription at version 1
    headers = make_customer_headers(ctx["cust_id"])
    validate_success(api.create_plan_change(
        ctx["sub_id"],
        create_plan_change_payload(ctx["starter_plan_id"], "2026-04-01", ctx["sub_version"]),
        headers), 201)  # this advances the subscription version to 2
    resp = api.create_plan_change(
        ctx["sub_id"],
        create_plan_change_payload(ctx["starter_plan_id"], "2026-04-08", ctx["sub_version"]),
        headers)  # still carries the now-stale version 1
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_plan_change_supersedes_prior_pending(api):
    """PRD §3.3: "creating it drives any prior `PENDING` plan change on the same subscription
    from `PENDING` to `SUPERSEDED` and increments the subscription's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/plan_change_supersedes_prior_pending
    """
    ctx = setup_subscription_two_plans(api)
    headers = make_customer_headers(ctx["cust_id"])
    pc1 = validate_success(api.create_plan_change(
        ctx["sub_id"],
        create_plan_change_payload(ctx["starter_plan_id"], "2026-04-01", ctx["sub_version"]),
        headers), 201)
    sub = validate_success(api.get_subscription(ctx["sub_id"], headers), 200)  # version now 2
    pc2 = validate_success(api.create_plan_change(
        ctx["sub_id"],
        create_plan_change_payload(ctx["starter_plan_id"], "2026-04-08", sub["version"]),
        headers), 201)
    assert validate_success(api.get_plan_change(pc1["id"], headers), 200)["status"] == "SUPERSEDED"
    assert validate_success(api.get_plan_change(pc2["id"], headers), 200)["status"] == "PENDING"
    assert validate_success(api.get_subscription(ctx["sub_id"], headers), 200)["version"] == 3
