"""Which check speaks first when a scoping or scheduling request breaks several rules."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_axes,
    assert_instant,
    assert_posture,
    assert_reserved_capacity,
    assert_runbook_state,
    assert_score,
    factories as f,
    fixtures as fx,
)


def test_scheduling_from_scoped_reports_the_state_error_not_the_window_clash(api):
    """A wrong from-state is reported before the calendar is ever consulted.

    PRD: "The exercise's `execution_state` is a declared from-state for the
    requested action — `ERR_INVALID_EXERCISE_STATE` (409), on scope-item
    creation, impact submission, impact decision, scheduling, execution
    transitions and step-execution recording."

    Design: Difficulty/priority_pair_validation_conflict/scoped_exercise_with_overlapping_window_rejects_on_state_before_window_conflict
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    fx.setup_scheduled_exercise(
        api,
        estate,
        name="Window holder",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    challenger = fx.setup_scoped_exercise(
        api,
        estate,
        name="Overlapping challenger",
        planned_start_at="2026-08-20T03:00:00Z",
        planned_end_at="2026-08-20T09:00:00Z",
    )

    validate_error(
        api.schedule_exercise(challenger["id"], {}, coordinator),
        ApiErrorId.ERR_INVALID_EXERCISE_STATE,
        409,
    )

    assert_axes(
        fx.read_exercise(api, coordinator, challenger["id"]), execution_state="SCOPED"
    )
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_recovery"]["id"]), 2
    )


def test_window_conflict_surfaces_once_the_state_check_passes(api):
    """With the state legal, the overlapping calendar is what rejects the schedule.

    PRD: "The exercise's half-open window must not intersect the window of any
    other exercise on the same recovery site whose `execution_state` is
    `SCHEDULED` or `IN_EXECUTION`."

    Design: Difficulty/priority_pair_validation_conflict/scoped_exercise_with_overlapping_window_rejects_on_state_before_window_conflict
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    fx.setup_scheduled_exercise(
        api,
        estate,
        name="Window holder",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    challenger = fx.setup_scoped_exercise(
        api,
        estate,
        name="Overlapping challenger",
        planned_start_at="2026-08-20T03:00:00Z",
        planned_end_at="2026-08-20T09:00:00Z",
    )
    fx.submit_impact(api, coordinator, challenger["id"])
    fx.approve_impact(api, estate["approver_headers"], challenger["id"])

    validate_error(
        api.schedule_exercise(challenger["id"], {}, coordinator),
        ApiErrorId.ERR_SITE_WINDOW_CONFLICT,
        409,
    )

    assert_axes(
        fx.read_exercise(api, coordinator, challenger["id"]), execution_state="APPROVED"
    )
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_recovery"]["id"]), 2
    )


def test_version_mismatch_pre_empts_the_readiness_floor(api):
    """The concurrency guard is answered before the runbook freshness rule.

    PRD: "The optimistic-concurrency field matches its parent's current
    `version`, as specified in §2.7 — `ERR_STALE_RECOVERY_GROUP_VERSION` or
    `ERR_STALE_EXERCISE_VERSION` (412), on `POST /runbooks` and `POST
    /exercises/{id}/scope-items`."

    Design: Difficulty/priority_pair_validation_conflict/stale_exercise_version_rejects_before_stale_runbook_readiness
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    exercise = fx.create_exercise(
        api,
        coordinator,
        recovery_site_id=estate["site_recovery"]["id"],
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at="2026-11-20T00:00:00Z",
        planned_end_at="2026-11-20T06:00:00Z",
        name="Concurrency versus freshness",
    )
    fx.set_logical_clock(api, "2026-10-13T00:00:00Z")

    validate_error(
        api.create_scope_item(
            exercise["id"],
            f.scope_item_payload(estate["group"]["id"], exercise["version"] + 1),
            coordinator,
        ),
        ApiErrorId.ERR_STALE_EXERCISE_VERSION,
        412,
    )

    unchanged = fx.read_exercise(api, coordinator, exercise["id"])
    assert_axes(unchanged, execution_state="DRAFT")
    assert unchanged["version"] == exercise["version"]


def test_matching_version_then_reports_the_stale_runbook(api):
    """Once the version matches, the decayed runbook is the surviving failure.

    PRD: "If `expected_exercise_version` does not equal the exercise's current
    `version`, the request is rejected with `ERR_STALE_EXERCISE_VERSION` (HTTP
    412)."

    Design: Difficulty/priority_pair_validation_conflict/stale_exercise_version_rejects_before_stale_runbook_readiness
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    exercise = fx.create_exercise(
        api,
        coordinator,
        recovery_site_id=estate["site_recovery"]["id"],
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at="2026-11-20T00:00:00Z",
        planned_end_at="2026-11-20T06:00:00Z",
        name="Concurrency versus freshness",
    )
    fx.set_logical_clock(api, "2026-10-13T00:00:00Z")

    validate_error(
        api.create_scope_item(
            exercise["id"],
            f.scope_item_payload(estate["group"]["id"], exercise["version"]),
            coordinator,
        ),
        ApiErrorId.ERR_RUNBOOK_STALE,
        422,
    )

    unchanged = fx.read_exercise(api, coordinator, exercise["id"])
    assert_axes(unchanged, execution_state="DRAFT")
    assert unchanged["required_capacity_units"] == 0
    validate_success(api.refresh_posture(estate["group"]["id"], coordinator))
    assert_score(
        fx.read_runbook(api, coordinator, estate["runbook"]["id"])["readiness_score"],
        79.72,
    )


def test_frozen_group_is_reported_before_the_site_mismatch(api):
    """A frozen group at the wrong site answers with the freeze, not the mismatch.

    PRD: "The group must not be in `posture` `FROZEN`, or the request is rejected
    with `ERR_GROUP_FROZEN`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_group_scoped_from_wrong_site_rejects_on_freeze_before_site_mismatch
    """
    estate = fx.setup_frozen_group_with_control_group(api)
    coordinator = estate["coordinator_headers"]
    exercise = estate["tertiary_exercise"]
    assert_posture(
        fx.read_group(api, coordinator, estate["group"]["id"]),
        "FROZEN",
        "OPEN_CRITICAL_FINDING",
    )

    validate_error(
        api.create_scope_item(
            exercise["id"],
            f.scope_item_payload(estate["group"]["id"], exercise["version"]),
            coordinator,
        ),
        ApiErrorId.ERR_GROUP_FROZEN,
        422,
    )

    assert_axes(
        fx.read_exercise(api, coordinator, exercise["id"]), execution_state="DRAFT"
    )


def test_unfrozen_group_at_another_site_reports_the_mismatch(api):
    """A healthy group belonging to a different recovery site is the site error.

    PRD: "The group's `recovery_site_id` must equal the exercise's
    `recovery_site_id`; a group that fails over somewhere else cannot be
    rehearsed here, and the mismatch yields `ERR_GROUP_SITE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_group_scoped_from_wrong_site_rejects_on_freeze_before_site_mismatch
    """
    estate = fx.setup_frozen_group_with_control_group(api)
    coordinator = estate["coordinator_headers"]
    exercise = estate["tertiary_exercise"]

    validate_error(
        api.create_scope_item(
            exercise["id"],
            f.scope_item_payload(estate["control_group"]["id"], exercise["version"]),
            coordinator,
        ),
        ApiErrorId.ERR_GROUP_SITE_MISMATCH,
        422,
    )

    unchanged = fx.read_exercise(api, coordinator, exercise["id"])
    assert_axes(unchanged, execution_state="DRAFT")
    assert unchanged["version"] == exercise["version"]
    assert_runbook_state(
        fx.read_runbook(api, coordinator, estate["control_runbook"]["id"]), "VALIDATED"
    )


def test_exercise_touching_the_change_freeze_endpoint_conflicts(api):
    """A window that ends exactly when the freeze opens still collides with it.

    PRD: "Because that interval is closed on both ends while the exercise window
    is half-open, an exercise that merely touches a freeze endpoint **does**
    conflict, and the rejection is `ERR_GROUP_CHANGE_FREEZE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/change_freeze_interval_is_closed_so_touching_the_endpoint_conflicts
    """
    estate = fx.setup_change_freeze_scenario(api)
    coordinator = estate["coordinator_headers"]
    exercise = estate["touching_exercise"]

    validate_error(
        api.create_scope_item(
            exercise["id"],
            f.scope_item_payload(estate["group"]["id"], exercise["version"]),
            coordinator,
        ),
        ApiErrorId.ERR_GROUP_CHANGE_FREEZE_CONFLICT,
        409,
    )

    unchanged = fx.read_exercise(api, coordinator, exercise["id"])
    assert_axes(unchanged, execution_state="DRAFT")
    assert unchanged["version"] == exercise["version"]
    assert unchanged["required_capacity_units"] == 0


def test_change_freeze_interval_is_stored_and_leaves_a_clear_window_alone(api):
    """The stored freeze is a closed interval, so a window ending before it is clear.

    PRD: "Both endpoints of that interval are **inclusive** — it is a closed
    interval — and `change_freeze_end_at` must be at or after
    `change_freeze_start_at` or the request is rejected with
    `ERR_INVALID_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/change_freeze_interval_is_closed_so_touching_the_endpoint_conflicts
    """
    estate = fx.setup_change_freeze_scenario(api)
    coordinator = estate["coordinator_headers"]
    group = fx.read_group(api, coordinator, estate["group"]["id"])
    assert_instant(group["change_freeze_start_at"], "2026-08-20T06:00:00Z")
    assert_instant(group["change_freeze_end_at"], "2026-08-25T00:00:00Z")

    exercise = estate["clear_exercise"]
    scope_item = validate_success(
        api.create_scope_item(
            exercise["id"],
            f.scope_item_payload(group["id"], exercise["version"]),
            coordinator,
        ),
        201,
    )

    assert scope_item["recovery_group_id"] == group["id"]
    assert_axes(
        fx.read_exercise(api, coordinator, exercise["id"]), execution_state="SCOPED"
    )
