"""Subscriptions: pausing, the prorated cycle charge, skipping and ownership."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_money,
    assert_same_instant,
    build_subscription,
    create_subscription_payload,
    make_subscriber_headers,
    new_recipe,
    read_subscription,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _paused_then_resumed_subscription(api):
    recipe = new_recipe(api)
    subscription = build_subscription(
        api, recipe["id"], subscriber_email="rin@example.com",
        subscriber_birth_date="1992-07-04T00:00:00.000Z",
    )
    owner = make_subscriber_headers(subscription["id"])
    validate_success(
        api.pause_subscription(
            subscription["id"],
            {
                "start_date": "2026-05-05T00:00:00.000Z",
                "end_date": "2026-05-11T00:00:00.000Z",
            },
            owner,
        )
    )
    validate_success(api.resume_subscription(subscription["id"], owner))
    return subscription, owner


def test_a_pause_touching_a_recorded_window_at_one_endpoint_conflicts(api):
    """PRD 3.10: "The requested interval may not intersect any interval already
    recorded in `pause_windows`, and two closed intervals that merely **touch** at an
    endpoint do count as intersecting. A span that is too long, or one that conflicts,
    answers `ERR_PAUSE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/subscription_pause_windows_are_closed_so_touching_endpoints_collide
    """
    subscription, owner = _paused_then_resumed_subscription(api)

    response = api.pause_subscription(
        subscription["id"],
        {"start_date": "2026-05-11T00:00:00.000Z", "end_date": "2026-05-15T00:00:00.000Z"},
        owner,
    )
    validate_error(response, ApiErrorId.ERR_PAUSE_WINDOW_CONFLICT.value, 409)

    after = read_subscription(api, subscription["id"])
    assert after["status"] == "ACTIVE", "the refused pause leaves the subscription running"
    assert after["current_pause_start_date"] is None


def test_a_pause_starting_one_day_clear_of_the_recorded_window_is_accepted(api):
    """PRD 3.10: "On success the subscription moves `ACTIVE → PAUSED`,
    `current_pause_start_date` and `current_pause_end_date` are set, and
    `next_cycle_charge` is recomputed with the proration in play."
    PRD 3.10: "Resuming moves `PAUSED → ACTIVE`, appends the now-closed interval to
    `pause_windows` as a `start_date` and `end_date` pair, clears both current pause
    fields to null, and recomputes `next_cycle_charge`."

    Design: Difficulty/resource_temporal_overlap/subscription_pause_windows_are_closed_so_touching_endpoints_collide
    """
    subscription, owner = _paused_then_resumed_subscription(api)

    paused = validate_success(
        api.pause_subscription(
            subscription["id"],
            {"start_date": "2026-05-12T00:00:00.000Z", "end_date": "2026-05-15T00:00:00.000Z"},
            owner,
        )
    )

    assert paused["status"] == "PAUSED"
    assert_same_instant(
        paused["current_pause_start_date"], "2026-05-12T00:00:00.000Z",
        "current_pause_start_date",
    )
    assert_same_instant(
        paused["current_pause_end_date"], "2026-05-15T00:00:00.000Z", "current_pause_end_date"
    )
    assert len(paused["pause_windows"]) == 1, "only the closed window is recorded"
    window = paused["pause_windows"][0]
    assert_same_instant(window["start_date"], "2026-05-05T00:00:00.000Z", "window start_date")
    assert_same_instant(window["end_date"], "2026-05-11T00:00:00.000Z", "window end_date")


def test_a_seven_day_pause_prorates_the_cycle_before_any_loyalty_discount(api):
    """PRD 3.10: "Step one: the prorated base is 42.00 multiplied by the active days,
    divided by 28, rounded half up to 2 decimals. Step two: the discount rate is 10 %
    when `completed_cycles` is at or above 6 and 0 otherwise — exactly 6 completed
    cycles already qualifies for the loyalty tier."
    PRD 3.10: "As the scaffold works it: against the 42.00 base, a pause of 7 days
    with `completed_cycles` 0 leaves 21 active days, a prorated base of 31.50, no
    discount, and a charge of 31.50; the same pause with `completed_cycles` 6 leaves
    the prorated base at 31.50 with a discount of 3.15 and a charge of 28.35."

    Design: Corner/calculations/subscription_charge_prorates_the_base_before_the_loyalty_discount
    """
    recipe = new_recipe(api)
    subscription = build_subscription(
        api, recipe["id"], subscriber_email="mio@example.com",
        subscriber_birth_date="1995-09-09T00:00:00.000Z",
    )
    owner = make_subscriber_headers(subscription["id"])

    paused = validate_success(
        api.pause_subscription(
            subscription["id"],
            {"start_date": "2026-05-05T00:00:00.000Z", "end_date": "2026-05-11T00:00:00.000Z"},
            owner,
        )
    )

    assert paused["status"] == "PAUSED"
    assert_money(paused["next_cycle_charge"], 31.50, "next_cycle_charge after a 7-day pause")
    assert paused["completed_cycles"] == 0
    assert_money(paused["credit_balance"], 0.00, "credit_balance")
    assert paused["cycle_index"] == 1


def test_the_fourth_skip_in_one_calendar_year_is_refused(api):
    """PRD 3.10: "**Skipping** is a self-loop on `ACTIVE` and it is capped at 3 per
    calendar year: `skips_used_this_year` must be strictly below 3, and no allocation
    for the current `cycle_index` may still be `ALLOCATED`. Either failure is
    `ERR_SUBSCRIPTION_SKIP_CAP`. A skip increments `skips_used_this_year` by 1,
    increments `cycle_index` by 1, advances `cycle_start_date` by 28 whole days, and
    credits the subscriber."
    PRD 3.10: "The credit is **not** prorated: it is the full 42.00 list price less
    the loyalty discount computed on that full price — 42.00 multiplied by the
    discount rate and divided by 100, rounded half up to 2 decimals, subtracted from
    42.00 and rounded again — and the result is added to `credit_balance`."

    Design: Corner/state_machines/a_fourth_skip_in_one_calendar_year_is_refused
    """
    recipe = new_recipe(api)
    subscription = build_subscription(
        api, recipe["id"], subscriber_email="ren@example.com",
        subscriber_birth_date="1988-02-02T00:00:00.000Z",
    )
    owner = make_subscriber_headers(subscription["id"])
    for _ in range(3):
        validate_success(api.skip_subscription(subscription["id"], owner))

    response = api.skip_subscription(subscription["id"], owner)
    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_SKIP_CAP.value, 422)

    after = read_subscription(api, subscription["id"])
    assert after["skips_used_this_year"] == 3
    assert after["cycle_index"] == 4
    assert_money(after["credit_balance"], 126.00, "three unprorated 42.00 credits")
    assert after["status"] == "ACTIVE"


def test_a_second_live_subscription_on_the_same_email_is_refused(api):
    """PRD 3.10: "The email address must be unique across subscriptions whose `status`
    is `ACTIVE` or `PAUSED`; a cancelled subscription does not block re-use of the
    address."
    PRD 3.12: "Subscriptions are listed with filters for `status` and
    `preferred_recipe_id`, and one subscription's allocations by `status`."

    Design: Corner/validations/a_second_live_subscription_on_the_same_email_is_refused
    """
    recipe = new_recipe(api)
    first = build_subscription(
        api, recipe["id"], subscriber_email="kai@example.com",
        subscriber_birth_date="1990-03-11T00:00:00.000Z",
    )

    response = api.create_subscription(
        create_subscription_payload(
            recipe["id"], subscriber_email="kai@example.com",
            subscriber_birth_date="1990-03-11T00:00:00.000Z",
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    assert read_subscription(api, first["id"])["status"] == "ACTIVE"
    rows, meta = validate_paginated(api.list_subscriptions(ADMIN, params={"status": "ACTIVE"}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first["id"]]


def test_a_subscriber_may_not_pause_somebody_elses_subscription(api):
    """PRD 2.1: "Ownership is therefore checked by comparison: for the pause, resume,
    skip and cancel operations on a subscription, the target subscription's `id` must
    equal `X-User-ID`; for an operation aimed at a `SubscriptionAllocation`, the
    allocation's `subscription_id` must equal `X-User-ID`. A `Subscriber` acting on
    somebody else's subscription is refused with `ERR_UNAUTHORIZED` (HTTP 403), the
    same code used for a role that is simply not permitted."

    Design: Corner/rbac/a_subscriber_cannot_pause_a_subscription_they_do_not_own
    """
    recipe = new_recipe(api)
    subscription_a = build_subscription(
        api, recipe["id"], subscriber_email="a@example.com",
        subscriber_birth_date="1991-01-01T00:00:00.000Z",
    )
    subscription_b = build_subscription(
        api, recipe["id"], subscriber_email="b@example.com",
        subscriber_birth_date="1991-01-01T00:00:00.000Z",
    )

    response = api.pause_subscription(
        subscription_b["id"],
        {"start_date": "2026-05-05T00:00:00.000Z", "end_date": "2026-05-11T00:00:00.000Z"},
        make_subscriber_headers(subscription_a["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    after = read_subscription(api, subscription_b["id"])
    assert after["status"] == "ACTIVE"
    assert after["current_pause_start_date"] is None
