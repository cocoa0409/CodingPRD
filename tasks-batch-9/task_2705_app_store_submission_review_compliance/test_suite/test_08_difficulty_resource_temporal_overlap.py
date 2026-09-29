"""Difficulty rule: resource_temporal_overlap.

Two interval conventions that deliberately disagree: reviewer capacity windows
are half-open and aggregate, rollout plans are closed at both ends.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    assert_decimal_equals,
    assert_slot_conservation,
    create_review_capacity_window_payload,
    create_rollout_plan_payload,
    get_success_data,
    make_policy_admin_headers,
    set_clock,
    setup_approved_ios,
    setup_released_ios,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# review_pool_half_open_aggregate_ceiling
# ---------------------------------------------------------------------------
def _window(api, starts_at, ends_at, capacity_slots, platform="IOS",
            reviewer_pool_code="POOL_A"):
    return api.create_review_capacity_window(
        create_review_capacity_window_payload(
            platform=platform,
            reviewer_pool_code=reviewer_pool_code,
            starts_at=starts_at,
            ends_at=ends_at,
            capacity_slots=capacity_slots,
        ),
        make_policy_admin_headers(),
    )


def _setup_pool_with_six_slots(api):
    """One OPEN IOS/POOL_A window of 6 slots over [08-01, 08-15)."""
    set_clock(api, DEFAULT_CLOCK)
    return get_success_data(
        _window(api, "2026-08-01T00:00:00Z", "2026-08-15T00:00:00Z", 6)
    )


def test_a_new_window_opens_with_every_slot_available(api):
    """"A window opens with `status` `OPEN`, `slots_reserved` and `slots_consumed` at 0 and
    `slots_available` equal to `capacity_slots`."

    Design: Difficulty/resource_temporal_overlap/review_pool_half_open_aggregate_ceiling
    """
    first = _setup_pool_with_six_slots(api)

    assert first["status"] == "OPEN"
    assert first["capacity_slots"] == 6
    assert first["slots_reserved"] == 0
    assert first["slots_consumed"] == 0
    assert first["slots_available"] == 6
    assert_slot_conservation(first)


def test_intersecting_slots_may_total_exactly_ten_but_never_eleven(api):
    """"Creation is subject to a pool-level ceiling: summed across every `OPEN` window of the
    same `platform` and `reviewer_pool_code` whose interval intersects the new one, total
    `capacity_slots` may not exceed 10, and a breach is refused with
    `ERR_REVIEW_POOL_OVERSUBSCRIBED`."

    Design: Difficulty/resource_temporal_overlap/review_pool_half_open_aggregate_ceiling
    """
    _setup_pool_with_six_slots(api)

    second = validate_success(
        _window(api, "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z", 4), 201
    )
    assert second["slots_available"] == 4
    assert second["slots_reserved"] == 0
    assert second["slots_consumed"] == 0

    validate_error(
        _window(api, "2026-08-12T00:00:00Z", "2026-08-18T00:00:00Z", 1),
        ApiErrorId.ERR_REVIEW_POOL_OVERSUBSCRIBED,
        409,
    )


def test_adjacency_and_a_different_pool_or_platform_never_intersect(api):
    """"Intersection is half-open, so adjacency never counts — a window ending exactly when
    another begins is always legal — and the ceiling is inclusive: a total of exactly 10 passes
    while 11 fails."

    Design: Difficulty/resource_temporal_overlap/review_pool_half_open_aggregate_ceiling
    """
    _setup_pool_with_six_slots(api)
    get_success_data(_window(api, "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z", 4))

    validate_success(
        _window(api, "2026-08-20T00:00:00Z", "2026-08-25T00:00:00Z", 5), 201
    )
    validate_success(
        _window(
            api,
            "2026-08-12T00:00:00Z",
            "2026-08-18T00:00:00Z",
            10,
            reviewer_pool_code="POOL_B",
        ),
        201,
    )
    validate_success(
        _window(
            api,
            "2026-08-12T00:00:00Z",
            "2026-08-18T00:00:00Z",
            10,
            platform="ANDROID",
        ),
        201,
    )


def test_closing_a_window_drops_its_slots_out_of_the_aggregate(api):
    """"A `PlatformPolicyAdmin` may close a window, moving it `OPEN → CLOSED`;
    already-reserved submissions keep their slots and may still be claimed and decided, but a
    closed window drops out of the selector, which is one way a queue call can find no capacity
    at all."

    Design: Difficulty/resource_temporal_overlap/review_pool_half_open_aggregate_ceiling
    """
    first = _setup_pool_with_six_slots(api)
    get_success_data(_window(api, "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z", 4))
    get_success_data(_window(api, "2026-08-20T00:00:00Z", "2026-08-25T00:00:00Z", 5))
    validate_error(
        _window(api, "2026-08-12T00:00:00Z", "2026-08-18T00:00:00Z", 1),
        ApiErrorId.ERR_REVIEW_POOL_OVERSUBSCRIBED,
    )

    closed = validate_success(
        api.close_review_capacity_window(first["id"], make_policy_admin_headers()), 200
    )
    assert closed["status"] == "CLOSED"

    late = validate_success(
        _window(api, "2026-08-12T00:00:00Z", "2026-08-18T00:00:00Z", 1), 201
    )
    assert late["capacity_slots"] == 1
    assert late["slots_available"] == 1

    rows, _meta = validate_paginated(
        api.list_review_capacity_windows(
            make_policy_admin_headers(),
            params={"platform": "IOS", "reviewer_pool_code": "POOL_A"},
        )
    )
    assert len(rows) == 4, "the refused creation must not have left a row behind"


# ---------------------------------------------------------------------------
# rollout_closed_interval_touching_conflict
# ---------------------------------------------------------------------------
def _setup_approved_phased_build(api):
    """One APPROVED PHASED build with no plan yet, clock at its default."""
    set_clock(api, DEFAULT_CLOCK)
    return setup_approved_ios(client=api)


def _plan(api, ctx, expected_version, scheduled_start_at, mode="PHASED"):
    return api.create_rollout_plan(
        create_rollout_plan_payload(
            ctx.app_record_id,
            ctx.submission_id,
            expected_version,
            mode=mode,
            scheduled_start_at=scheduled_start_at,
        ),
        ctx.release_manager,
    )


def test_phased_plan_projects_seven_phases_of_dwell_from_its_start(api):
    """"Its `projected_end_at` is derived: for a phased plan it is `scheduled_start_at` plus
    seven phases times 24 hours of minimum dwell; for an immediate plan it is
    `scheduled_start_at` itself."

    Design: Difficulty/resource_temporal_overlap/rollout_closed_interval_touching_conflict
    """
    ctx = _setup_approved_phased_build(api)

    first = validate_success(
        _plan(api, ctx, ctx.app_version(), "2026-08-02T00:00:00Z"), 201
    )
    assert first["state"] == "SCHEDULED"
    assert first["scheduled_start_at"] == "2026-08-02T00:00:00Z"
    assert first["projected_end_at"] == "2026-08-09T00:00:00Z"
    assert first["phase_index"] == 0
    assert first["terminated_at"] is None
    assert_decimal_equals(first["released_share_pct"], 0.00, 2, "released")
    assert_decimal_equals(first["held_back_share_pct"], 100.00, 2, "held back")


def test_a_plan_starting_exactly_when_another_ends_conflicts(api):
    """"A plan's interval runs from `scheduled_start_at` to `projected_end_at` and is
    **closed at both ends**, so touching endpoints *do* conflict: a new plan starting exactly
    when an existing plan is projected to end is rejected, whereas back-to-back capacity
    windows are always legal."

    Design: Difficulty/resource_temporal_overlap/rollout_closed_interval_touching_conflict
    """
    ctx = _setup_approved_phased_build(api)
    get_success_data(_plan(api, ctx, ctx.app_version(), "2026-08-02T00:00:00Z"))

    version_after_first = ctx.app_version()
    validate_error(
        _plan(api, ctx, version_after_first, "2026-08-09T00:00:00Z"),
        ApiErrorId.ERR_ROLLOUT_WINDOW_CONFLICT,
        409,
    )
    assert ctx.app_version() == version_after_first, (
        "a refused plan creation must not advance the app record revision"
    )

    third = validate_success(
        _plan(api, ctx, version_after_first, "2026-08-09T01:00:00Z"), 201
    )
    assert third["state"] == "SCHEDULED"
    assert third["projected_end_at"] == "2026-08-16T01:00:00Z"


def test_scheduling_plans_distributes_nothing_yet(api):
    """"A plan is created in state `SCHEDULED` with `phase_index` 0, `released_share_pct` 0.00
    and `held_back_share_pct` 100.00, and it advances the app record's `version` by one."

    Design: Difficulty/resource_temporal_overlap/rollout_closed_interval_touching_conflict
    """
    ctx = _setup_approved_phased_build(api)
    before = ctx.app_version()
    get_success_data(_plan(api, ctx, before, "2026-08-02T00:00:00Z"))
    assert ctx.app_version() == before + 1
    get_success_data(_plan(api, ctx, ctx.app_version(), "2026-08-09T01:00:00Z"))

    rows, _meta = validate_paginated(
        api.list_rollout_plans(
            ctx.release_manager, params={"app_record_id": ctx.app_record_id}
        )
    )
    assert len(rows) == 2
    assert [row["state"] for row in rows] == ["SCHEDULED", "SCHEDULED"]

    app = ctx.app()
    assert app["distribution_state"] == "NOT_DISTRIBUTED"
    assert app["live_submission_id"] is None


# ---------------------------------------------------------------------------
# rollback_cooldown_one_sided_strict_buffer
# ---------------------------------------------------------------------------
def _setup_rolled_back_plan(api):
    """A PHASE_ACTIVE phased plan over [08-01, 08-08] rolled back at 08-02T12:00Z."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(client=api, mode="PHASED")
    set_clock(api, "2026-08-02T12:00:00Z")
    rolled = get_success_data(
        api.rollback_rollout_plan(
            ctx.plan_id,
            {"rollback_reason_code": "CRASH_SPIKE", "halt_distribution": True},
            ctx.release_manager,
        )
    )
    return ctx, rolled


def test_rollback_terminates_the_plan_and_halts_distribution(api):
    """"Against a plan in `ROLLED_BACK` a one-sided cooldown applies instead: the new
    `scheduled_start_at` must be at or after that plan's `terminated_at` plus 72 hours, and the
    comparison is strict, so scheduling exactly at the buffer edge is legal."

    Design: Difficulty/resource_temporal_overlap/rollback_cooldown_one_sided_strict_buffer
    """
    ctx, rolled = _setup_rolled_back_plan(api)

    assert rolled["state"] == "ROLLED_BACK"
    assert rolled["terminated_at"] == "2026-08-02T12:00:00Z"
    assert rolled["projected_end_at"] == "2026-08-08T00:00:00Z"
    assert_decimal_equals(rolled["released_share_pct"], 0.00, 2, "released")
    assert_decimal_equals(rolled["held_back_share_pct"], 100.00, 2, "held back")

    app = ctx.app()
    assert app["distribution_state"] == "ROLLED_BACK"
    assert app["live_submission_id"] is None
    assert app["rollback_count"] == 1


def test_cooldown_edge_is_legal_one_hour_short_of_it_is_not(api):
    """"Only one plan may occupy an app's release calendar at a time, and the interval
    arithmetic here uses the **opposite** convention from reviewer capacity."

    Design: Difficulty/resource_temporal_overlap/rollback_cooldown_one_sided_strict_buffer
    """
    ctx, _rolled = _setup_rolled_back_plan(api)

    version = ctx.app_version()
    validate_error(
        _plan(api, ctx, version, "2026-08-05T11:00:00Z"),
        ApiErrorId.ERR_ROLLOUT_WINDOW_CONFLICT,
        409,
    )
    assert ctx.app_version() == version

    successor = validate_success(
        _plan(api, ctx, version, "2026-08-05T12:00:00Z"), 201
    )
    assert successor["state"] == "SCHEDULED"
    assert successor["scheduled_start_at"] == "2026-08-05T12:00:00Z"
    assert successor["projected_end_at"] == "2026-08-12T12:00:00Z"


def test_the_same_instant_turns_illegal_again_once_a_plan_occupies_it(api):
    """"Against every other plan of the same app in state `SCHEDULED`, `PHASE_ACTIVE` or
    `PAUSED`, a conflict exists when the new start is at or before that plan's projected end and
    that plan's start is at or before the new projected end."

    Design: Difficulty/resource_temporal_overlap/rollback_cooldown_one_sided_strict_buffer
    """
    ctx, _rolled = _setup_rolled_back_plan(api)
    get_success_data(_plan(api, ctx, ctx.app_version(), "2026-08-05T12:00:00Z"))

    validate_error(
        _plan(api, ctx, ctx.app_version(), "2026-08-05T12:00:00Z"),
        ApiErrorId.ERR_ROLLOUT_WINDOW_CONFLICT,
        409,
    )

    rows, _meta = validate_paginated(
        api.list_rollout_plans(
            ctx.release_manager, params={"app_record_id": ctx.app_record_id}
        )
    )
    assert len(rows) == 2
    assert sorted(row["state"] for row in rows) == ["ROLLED_BACK", "SCHEDULED"]
    assert ctx.app()["distribution_state"] == "ROLLED_BACK", (
        "scheduling a successor does not un-roll-back the app"
    )
