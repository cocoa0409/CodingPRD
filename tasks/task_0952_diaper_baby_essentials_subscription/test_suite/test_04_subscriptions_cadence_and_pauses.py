"""Subscription creation, cadence derivation, activation, pausing and resuming."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_pause_record,
    assert_same_instant,
    assert_subscription,
    create_child_payload,
    create_subscription_payload,
    make_account_holder_headers,
    make_child,
    make_plan,
    make_subscription,
    read_subscription,
    register_and_verify_account,
    set_clock,
    setup_household,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["ops_admin_headers"]


# ==========================================================================
# Creation and cadence derivation
# ==========================================================================
def test_a_new_subscription_starts_in_draft_on_both_axes(api):
    """PRD §3.4: "The new subscription is persisted in `lifecycle_state` `DRAFT` and
    `billing_state` `CURRENT`."
    PRD §3.4: "The server multiplies `pack_count` by 60 — the assumed number of units in a
    pack for cadence purposes — divides by `consumption_rate_per_day`, and rounds the
    quotient half up to a whole number of days."
    PRD §3.4: "`cadence_override_days` is null by default, and a forward-looking cadence read
    reports the current `cadence_interval_days`, the current `anchor_date`, the projected
    `next_window_start`, `next_window_end` and `next_cutoff_at`, and an `override_active`
    boolean saying whether a manual override is presently pinned."

    Design: Corner/entities/corner_subscription_starts_draft_and_billing_current
    """
    ctx = setup_household(
        api, with_sku=False, email_prefix="draft", activate_subscription=False
    )
    subscription = ctx["subscription"]
    assert_subscription(subscription)
    assert subscription["lifecycle_state"] == "DRAFT"
    assert subscription["billing_state"] == "CURRENT"
    assert subscription["cadence_interval_days"] == 20, "2 packs x 60 units / 6 per day"
    assert subscription.get("cadence_override_days") is None
    assert subscription["free_shipping_eligible"] is False


def test_an_omitted_pack_count_is_copied_from_the_plan(api):
    """PRD §3.4: "`pack_count` is the number of packs shipped per cycle and must lie
    between 1 and 12 inclusive; when it is omitted the server copies the plan's
    `default_pack_count` into it."

    Design: Corner/entities/corner_subscription_pack_count_defaults_from_plan
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = make_plan(api, default_pack_count=4)
    account = register_and_verify_account(api, email=unique_email("packdef"))
    child = make_child(api, account)
    data = validate_success(
        api.create_subscription(
            {
                "account_id": account["id"],
                "plan_id": plan["id"],
                "child_id": child["id"],
                "consumption_rate_per_day": 6,
            },
            make_account_holder_headers(account["id"]),
        ),
        201,
    )
    assert data["pack_count"] == 4
    assert data["cadence_interval_days"] == 40, "4 packs x 60 units / 6 per day"


def test_the_derived_cadence_is_clamped_up_to_the_fourteen_day_floor(api):
    """PRD §3.4: "That derived figure is then clamped into the permitted band: no shorter
    than 14 days and no longer than 56 days."

    Design: Corner/calculations/corner_cadence_clamped_to_minimum_fourteen_days
    """
    ctx = setup_household(
        api,
        with_sku=False,
        email_prefix="clampmin",
        activate_subscription=False,
        subscription_overrides={"consumption_rate_per_day": 14, "pack_count": 1},
    )
    assert ctx["subscription"]["cadence_interval_days"] == 14
    assert ctx["subscription"]["pack_count"] == 1


def test_the_derived_cadence_is_clamped_down_to_the_fifty_six_day_ceiling(api):
    """PRD §3.4: "That derived figure is then clamped into the permitted band: no shorter
    than 14 days and no longer than 56 days."

    Design: Corner/calculations/corner_cadence_clamped_to_maximum_fifty_six_days
    """
    ctx = setup_household(
        api,
        with_sku=False,
        email_prefix="clampmax",
        activate_subscription=False,
        subscription_overrides={"consumption_rate_per_day": 1, "pack_count": 12},
    )
    assert ctx["subscription"]["cadence_interval_days"] == 56
    assert ctx["subscription"]["pack_count"] == 12


def test_the_cadence_quotient_rounds_half_up_before_the_clamp(api):
    """PRD §3.4: "The server multiplies `pack_count` by 60 — the assumed number of units in
    a pack for cadence purposes — divides by `consumption_rate_per_day`, and rounds the
    quotient half up to a whole number of days."
    PRD §2.8: "Wherever a computation produces a fractional cent, it is rounded half up to
    a whole cent — a value ending in exactly one half rounds away from zero."

    Design: Corner/calculations/corner_cadence_rounds_half_up_before_clamping
    """
    ctx = setup_household(
        api,
        with_sku=False,
        email_prefix="round",
        activate_subscription=False,
        subscription_overrides={"consumption_rate_per_day": 7, "pack_count": 2},
    )
    assert ctx["subscription"]["cadence_interval_days"] == 17, "120 / 7 = 17.14 rounds to 17"


def test_every_subscription_mutation_advances_the_version_by_one(api):
    """PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation, and `version`, an integer that begins at 1 on creation and
    increments by exactly 1 on every mutation of that resource."
    PRD §3.4: "The derivation re-runs on creation, on activation, and on any update that
    touches `pack_count` or `consumption_rate_per_day`."

    Design: Corner/cross_cutting_layers/corner_version_increments_on_every_mutation
    """
    ctx = setup_household(
        api, with_sku=False, email_prefix="ver", activate_subscription=False
    )
    assert ctx["subscription"]["version"] == 1

    first = validate_success(
        api.update_subscription(ctx["subscription"]["id"], {"pack_count": 3}, ctx["headers"])
    )
    assert first["version"] == 2

    second = validate_success(
        api.update_subscription(
            ctx["subscription"]["id"], {"consumption_rate_per_day": 9}, ctx["headers"]
        )
    )
    assert second["version"] == 3
    assert second["cadence_interval_days"] == 20, "3 packs x 60 units / 9 per day"


# ==========================================================================
# The manual cadence override
# ==========================================================================
def test_a_pinned_cadence_override_survives_a_consumption_rate_change(api):
    """PRD §3.4: "Setting a manual override stores `cadence_override_days`, which must be
    between 14 and 56 inclusive, and immediately sets `cadence_interval_days` to that same
    value. While an override is in force, derivation is suppressed entirely: changing
    `pack_count` or `consumption_rate_per_day` leaves `cadence_interval_days` exactly where
    the override put it."

    Design: Difficulty/dual_variant_calc/cadence_manual_override_suppresses_recomputation
    """
    ctx = setup_household(api, with_sku=False, email_prefix="cad")
    pinned = validate_success(
        api.set_cadence_override(ctx["subscription"]["id"], 35, ctx["headers"])
    )
    assert pinned["cadence_interval_days"] == 35
    assert pinned["cadence_override_days"] == 35

    patched = validate_success(
        api.update_subscription(
            ctx["subscription"]["id"], {"consumption_rate_per_day": 12}, ctx["headers"]
        )
    )
    assert patched["cadence_interval_days"] == 35, (
        "the override suppresses derivation, so the interval stays where it was pinned"
    )


def test_clearing_the_override_immediately_re_derives_the_interval(api):
    """PRD §3.4: "Clearing the override sets `cadence_override_days` back to null and
    immediately re-derives the interval from the consumption rate."
    PRD §3.4: "That derived figure is then clamped into the permitted band: no shorter than
    14 days and no longer than 56 days."

    Design: Difficulty/dual_variant_calc/cadence_manual_override_suppresses_recomputation
    """
    ctx = setup_household(api, with_sku=False, email_prefix="cad2")
    validate_success(api.set_cadence_override(ctx["subscription"]["id"], 35, ctx["headers"]))
    validate_success(
        api.update_subscription(
            ctx["subscription"]["id"], {"consumption_rate_per_day": 12}, ctx["headers"]
        )
    )

    cleared = validate_success(
        api.clear_cadence_override(ctx["subscription"]["id"], ctx["headers"])
    )
    assert cleared["cadence_interval_days"] == 14, (
        "2 packs x 60 units / 12 per day is 10 days, clamped up to the 14-day floor"
    )
    assert cleared.get("cadence_override_days") is None
    assert read_subscription(api, ctx["subscription"]["id"])["cadence_interval_days"] == 14


# ==========================================================================
# Activation
# ==========================================================================
def test_activating_an_already_active_subscription_is_refused(api):
    """PRD §3.4: "The preconditions are that the subscription is in `DRAFT`, the owning
    account's `status` is `ACTIVE`, the child is not archived, and no *other* subscription
    for the same account-and-child pair is in `lifecycle_state` `ACTIVE` or `PAUSED`"
    PRD §3.4: "any attempt to move a subscription whose current `lifecycle_state` is not in
    the target transition's from-set is refused with `ERR_SUBSCRIPTION_STATE_INVALID` (HTTP
    409)."
    PRD §3.4: "Activation moves the subscription `DRAFT → ACTIVE` and sets `anchor_date` —
    the instant from which the next cycle window opens — to the logical clock at the moment
    of activation plus 7 days of lead time."

    Design: Corner/state_machines/corner_activate_an_already_active_subscription_rejected
    """
    ctx = setup_household(api, with_sku=False, email_prefix="twice")
    set_clock(api, "2026-06-03T00:00:00Z")
    resp = api.activate_subscription(ctx["subscription"]["id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_STATE_INVALID.value, 409)

    after = read_subscription(api, ctx["subscription"]["id"])
    assert_same_instant(after["anchor_date"], "2026-06-08T00:00:00Z", "anchor_date")


def test_a_second_active_subscription_for_the_same_child_is_refused(api):
    """PRD §3.4: "and no *other* subscription for the same account-and-child pair is in
    `lifecycle_state` `ACTIVE` or `PAUSED`; that last one is refused with
    `ERR_DUPLICATE_ACTIVE_SUBSCRIPTION` (HTTP 409)."

    Design: Corner/validations/corner_second_active_subscription_for_same_child_rejected
    """
    ctx = setup_household(api, with_sku=False, email_prefix="dupsub")
    second = make_subscription(
        api, ctx["account"], ctx["plan"], ctx["child"],
        consumption_rate_per_day=8, pack_count=3,
    )
    resp = api.activate_subscription(second["id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_SUBSCRIPTION.value, 409)

    assert read_subscription(api, second["id"])["lifecycle_state"] == "DRAFT"
    assert read_subscription(api, ctx["subscription"]["id"])["lifecycle_state"] == "ACTIVE"


def test_a_subscription_naming_another_households_child_is_refused(api):
    """PRD §3.4: "it enforces referential coherence: the child's own `account_id` must
    equal the `account_id` supplied for the subscription, and a mismatch is refused with
    `ERR_CHILD_ACCOUNT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/corner_subscription_naming_another_accounts_child_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = make_plan(api)
    account_a = register_and_verify_account(
        api, email=unique_email("mismatchA"), payment_method_on_file=True
    )
    account_b = register_and_verify_account(
        api, email=unique_email("mismatchB"), payment_method_on_file=True
    )
    child_b = make_child(api, account_b, name="Kai")

    resp = api.create_subscription(
        create_subscription_payload(account_a["id"], plan["id"], child_b["id"]),
        make_account_holder_headers(account_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CHILD_ACCOUNT_MISMATCH.value, 422)

    _listed, meta = validate_paginated(
        api.list_subscriptions(
            make_account_holder_headers(account_a["id"]), {"account_id": account_a["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_cancelled_subscription_admits_no_pause(api):
    """PRD §3.4: "`CANCELLED` is terminal on the lifecycle axis and admits no transition
    whatsoever; any attempt to move a subscription whose current `lifecycle_state` is not in
    the target transition's from-set is refused with `ERR_SUBSCRIPTION_STATE_INVALID` (HTTP
    409)."
    PRD §3.10: "the subscription's `lifecycle_state` becomes `CANCELLED` and `cancelled_at`
    is stamped with the logical clock"

    Design: Corner/state_machines/corner_cancelled_subscription_is_terminal_for_pauses
    """
    ctx = setup_household(api, with_sku=False, email_prefix="cancel1")
    validate_success(api.cancel_subscription(ctx["subscription"]["id"], ctx["headers"]))

    resp = api.create_pause(
        ctx["subscription"]["id"],
        {"start_date": "2026-06-10", "end_date": "2026-06-12"},
        ctx["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_STATE_INVALID.value, 409)

    after = read_subscription(api, ctx["subscription"]["id"])
    assert after["lifecycle_state"] == "CANCELLED"
    assert_same_instant(after["cancelled_at"], "2026-06-01T00:00:00Z", "cancelled_at")

    _listed, meta = validate_paginated(
        api.list_pause_records(OPS, {"subscription_id": ctx["subscription"]["id"]})
    )
    assert meta["total_count"] == 0


# ==========================================================================
# Pause intervals — closed at both ends
# ==========================================================================
def test_a_pause_starting_the_day_after_an_existing_one_ends_is_accepted(api):
    """PRD §3.4: "The requested interval may not share a single calendar day with any
    existing `PauseRecord` of the same subscription whose `status` is `SCHEDULED` or
    `ACTIVE` — two pauses conflict exactly when they overlap on at least one day, so
    strictly adjacent pauses, where an existing pause ends the day before the new one
    starts, are permitted; a conflict is refused with `ERR_PAUSE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/pause_closed_closed_day_intervals_adjacent_ok_shared_day_rejected
    """
    ctx = setup_household(api, with_sku=False, email_prefix="pause")
    first = validate_success(
        api.create_pause(
            ctx["subscription"]["id"],
            {"start_date": "2026-06-10", "end_date": "2026-06-20"},
            ctx["headers"],
        ),
        201,
    )
    assert_pause_record(first)
    assert first["status"] == "SCHEDULED"

    second = validate_success(
        api.create_pause(
            ctx["subscription"]["id"],
            {"start_date": "2026-06-21", "end_date": "2026-06-25"},
            ctx["headers"],
        ),
        201,
    )
    assert second["status"] == "SCHEDULED"
    assert read_subscription(api, ctx["subscription"]["id"])["lifecycle_state"] == "ACTIVE"


def test_a_pause_sharing_a_single_calendar_day_is_refused(api):
    """PRD §3.4: "Pause intervals are closed at both ends: both the start day and the end
    day belong to the interval, so a pause where `end_date` equals `start_date` is a valid
    one-day pause."
    PRD §3.4: "two pauses conflict exactly when they overlap on at least one day, so
    strictly adjacent pauses, where an existing pause ends the day before the new one
    starts, are permitted; a conflict is refused with `ERR_PAUSE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/pause_closed_closed_day_intervals_adjacent_ok_shared_day_rejected
    """
    ctx = setup_household(api, with_sku=False, email_prefix="pause2")
    validate_success(
        api.create_pause(
            ctx["subscription"]["id"],
            {"start_date": "2026-06-10", "end_date": "2026-06-20"},
            ctx["headers"],
        ),
        201,
    )
    validate_success(
        api.create_pause(
            ctx["subscription"]["id"],
            {"start_date": "2026-06-21", "end_date": "2026-06-25"},
            ctx["headers"],
        ),
        201,
    )
    resp = api.create_pause(
        ctx["subscription"]["id"],
        {"start_date": "2026-06-25", "end_date": "2026-06-30"},
        ctx["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PAUSE_OVERLAP.value, 409)

    _listed, meta = validate_paginated(
        api.list_pause_records(OPS, {"subscription_id": ctx["subscription"]["id"]})
    )
    assert meta["total_count"] == 2, "the conflicting pause must not have persisted"


def test_a_pause_starting_before_today_is_refused(api):
    """PRD §3.4: "The `start_date` may not be earlier than the logical clock's calendar
    date, or the request is refused with `ERR_PAUSE_START_IN_PAST` (HTTP 422)."

    Design: Corner/validations/corner_pause_starting_in_the_past_rejected
    """
    ctx = setup_household(api, with_sku=False, email_prefix="pastpause")
    resp = api.create_pause(
        ctx["subscription"]["id"],
        {"start_date": "2026-05-01", "end_date": "2026-05-10"},
        ctx["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PAUSE_START_IN_PAST.value, 422)

    _listed, meta = validate_paginated(
        api.list_pause_records(OPS, {"subscription_id": ctx["subscription"]["id"]})
    )
    assert meta["total_count"] == 0


def test_a_pause_ending_before_it_starts_is_refused(api):
    """PRD §3.4: "The `end_date` may not be earlier than `start_date`, or the request is
    refused with `ERR_PAUSE_INTERVAL_INVALID` (HTTP 422)."

    Design: Corner/validations/corner_pause_end_before_start_rejected
    """
    ctx = setup_household(api, with_sku=False, email_prefix="badinterval")
    resp = api.create_pause(
        ctx["subscription"]["id"],
        {"start_date": "2026-06-20", "end_date": "2026-06-10"},
        ctx["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PAUSE_INTERVAL_INVALID.value, 422)

    _listed, meta = validate_paginated(
        api.list_pause_records(OPS, {"subscription_id": ctx["subscription"]["id"]})
    )
    assert meta["total_count"] == 0


def test_a_ninety_two_day_projected_pause_exceeds_the_budget(api):
    """PRD §3.4: "Finally the household's pause budget must hold: the subscription's
    `cumulative_pause_days` plus the projected length of the new pause, counted inclusively
    as the number of days from `start_date` to `end_date` plus one, may not exceed 90; a
    projected total of exactly 90 is admitted and 91 is refused with
    `ERR_PAUSE_BUDGET_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/corner_pause_projected_ninety_two_days_exceeds_budget
    """
    ctx = setup_household(api, with_sku=False, email_prefix="budget")
    resp = api.create_pause(
        ctx["subscription"]["id"],
        {"start_date": "2026-06-10", "end_date": "2026-09-09"},
        ctx["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PAUSE_BUDGET_EXCEEDED.value, 409)

    after = read_subscription(api, ctx["subscription"]["id"])
    assert after["cumulative_pause_days"] == 0
    assert after["lifecycle_state"] == "ACTIVE"
    _listed, meta = validate_paginated(
        api.list_pause_records(OPS, {"subscription_id": ctx["subscription"]["id"]})
    )
    assert meta["total_count"] == 0


def test_cancelling_an_active_pause_record_is_refused(api):
    """PRD §3.4: "When the `start_date` is today the record is created directly in `ACTIVE`
    and the subscription moves `ACTIVE → PAUSED`"
    PRD §3.4: "A `SCHEDULED` record may be cancelled outright by its household, moving it
    `SCHEDULED → CANCELLED`; that path charges nothing against the pause budget, since
    `consumed_days` stays 0. Cancelling a record that is not `SCHEDULED` is refused with
    `ERR_PAUSE_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/corner_cancel_an_active_pause_record_rejected
    """
    ctx = setup_household(api, with_sku=False, email_prefix="pausedel")
    record = validate_success(
        api.create_pause(
            ctx["subscription"]["id"],
            {"start_date": "2026-06-01", "end_date": "2026-06-15"},
            ctx["headers"],
        ),
        201,
    )
    assert record["status"] == "ACTIVE", "a pause starting today begins immediately"

    resp = api.cancel_pause_record(record["id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_PAUSE_STATE_INVALID.value, 409)

    assert validate_success(api.get_pause_record(record["id"], OPS))["status"] == "ACTIVE"
    assert read_subscription(api, ctx["subscription"]["id"])["lifecycle_state"] == "PAUSED"


def test_resuming_early_consumes_only_the_days_actually_taken(api):
    """PRD §3.4: "`consumed_days` is what the budget actually counts, and it is computed
    per record: an `ENDED` record consumes the inclusive number of days from its
    `start_date` to its `actual_end_date`"
    PRD §3.4: "That record moves `ACTIVE → ENDED`, its `actual_end_date` is set to today and
    its `consumed_days` recomputed, the subscription moves `PAUSED → ACTIVE`, and
    `cumulative_pause_days` is recomputed. The cadence anchor is then pushed forward by the
    days actually consumed — the inclusive count from `start_date` to `actual_end_date` —
    added to the existing `anchor_date`, preserving its time-of-day component."

    Design: Corner/calculations/corner_pause_consumed_days_counts_both_endpoints_and_shifts_anchor
    """
    ctx = setup_household(api, with_sku=False, email_prefix="resume")
    record = validate_success(
        api.create_pause(
            ctx["subscription"]["id"],
            {"start_date": "2026-06-01", "end_date": "2026-06-15"},
            ctx["headers"],
        ),
        201,
    )
    set_clock(api, "2026-06-05T00:00:00Z")

    resumed = validate_success(
        api.resume_subscription(ctx["subscription"]["id"], ctx["headers"])
    )
    assert resumed["lifecycle_state"] == "ACTIVE"
    assert_same_instant(resumed["anchor_date"], "2026-06-13T00:00:00Z", "anchor_date")

    after = validate_success(api.get_pause_record(record["id"], OPS))
    assert after["status"] == "ENDED"
    assert after["actual_end_date"] == "2026-06-05"
    assert after["consumed_days"] == 5, "1 June through 5 June inclusive is five days"
    assert read_subscription(api, ctx["subscription"]["id"])["cumulative_pause_days"] == 5
