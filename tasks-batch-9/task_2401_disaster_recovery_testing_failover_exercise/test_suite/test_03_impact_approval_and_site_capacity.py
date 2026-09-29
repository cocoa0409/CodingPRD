"""Production-impact scoring, the readiness gate on submission, and site capacity."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_axes,
    assert_impact_scores,
    assert_posture,
    assert_reserved_capacity,
    assert_score,
    fixtures as fx,
)


def test_governance_surcharge_is_keyed_on_the_provisional_band(api):
    """A provisional 59.50 takes the LEVEL_2 surcharge of 3, not the LEVEL_3 one of 5.

    PRD: "**The governance surcharge** is keyed on that *provisional* band: 1 for
    `LEVEL_1`, 3 for `LEVEL_2`, 5 for `LEVEL_3`."

    Design: Difficulty/combinatorial_formula/impact_surcharge_keyed_on_provisional_band_not_final_band
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    exercise = fx.setup_scoped_exercise(
        api,
        estate,
        name="Annual site failover",
        exercise_type="FULL_SITE_FAILOVER",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )

    submitted = fx.submit_impact(api, coordinator, exercise["id"])

    assert_impact_scores(submitted, 59.50, 62.50, "LEVEL_3")
    assert_score(
        submitted["production_impact_score"] - submitted["provisional_impact_score"], 3.00
    )


def test_required_authority_is_derived_once_from_the_final_score(api):
    """The final score sets the authority level while the surcharge stays at 3.

    PRD: "The surcharge keeps the value of the provisional band even when adding
    it pushes the final score into a higher band — the band is not re-derived a
    second time in order to grow the surcharge — while `required_approval_level`
    is derived exactly once and from the final score, not from the provisional
    one."

    Design: Difficulty/combinatorial_formula/impact_surcharge_keyed_on_provisional_band_not_final_band
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    exercise = fx.setup_scoped_exercise(
        api,
        estate,
        name="Annual site failover",
        exercise_type="FULL_SITE_FAILOVER",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )

    fx.submit_impact(api, coordinator, exercise["id"])

    stored = fx.read_exercise(api, coordinator, exercise["id"])
    assert_impact_scores(stored, 59.50, 62.50, "LEVEL_3")
    assert stored["production_impact_score"] != 64.50
    assert stored["required_capacity_units"] == 6
    assert_axes(stored, execution_state="PENDING_IMPACT_APPROVAL")


def test_impact_submission_requires_every_in_scope_group_ready(api):
    """A ready group lets the submission through and produces both scores.

    PRD: "At least one scope item must exist, and **every** in-scope group must
    be in `posture` `READY` at that moment; a group that has since slipped to
    `RESTRICTED` or `FROZEN` blocks the submission with `ERR_GROUP_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/impact_submission_depends_on_recovery_group_posture_ready
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    ready_exercise = fx.setup_scoped_exercise(
        api,
        estate,
        name="Submitted while ready",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )

    submitted = fx.submit_impact(api, coordinator, ready_exercise["id"])

    assert_axes(submitted, execution_state="PENDING_IMPACT_APPROVAL")
    assert_impact_scores(submitted, 38.50, 39.50, "LEVEL_1")


def test_restricted_group_blocks_the_submission_and_leaves_it_unscored(api):
    """Once the group slips to RESTRICTED the same submission is refused.

    PRD: "Hop 4, caused by hop 3, re-derives each affected recovery group's
    `posture`, which lands on `RESTRICTED` with `posture_reason` `RUNBOOK_STALE`
    whenever no escalated critical finding is outstanding."

    Design: Difficulty/cross_entity_state_dependency/impact_submission_depends_on_recovery_group_posture_ready
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    blocked_exercise = fx.setup_scoped_exercise(
        api,
        estate,
        name="Submitted after the slip",
        planned_start_at="2026-09-20T00:00:00Z",
        planned_end_at="2026-09-20T06:00:00Z",
    )
    validate_success(
        api.patch_stakeholder(
            estate["operator"]["id"], {"status": "SUSPENDED"}, estate["admin_headers"]
        )
    )

    validate_error(
        api.submit_impact(blocked_exercise["id"], {}, coordinator),
        ApiErrorId.ERR_GROUP_NOT_READY,
        422,
    )

    assert_posture(
        fx.read_group(api, coordinator, estate["group"]["id"]),
        "RESTRICTED",
        "RUNBOOK_STALE",
    )
    unscored = fx.read_exercise(api, coordinator, blocked_exercise["id"])
    assert_axes(unscored, execution_state="SCOPED")
    assert unscored["provisional_impact_score"] is None
    assert unscored["production_impact_score"] is None
    assert unscored["required_approval_level"] is None


def test_capacity_booked_to_exactly_the_ceiling_is_allowed(api):
    """A six-unit exercise fits a six-unit site exactly.

    PRD: "Equality is allowed — a site may be booked to exactly its stated
    ceiling — and only genuinely exceeding it is rejected, with
    `ERR_SITE_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/capacity_exactly_equal_to_usable_is_allowed_one_unit_over_rejects
    """
    estate = fx.setup_small_site_capacity_scenario(api)
    coordinator = estate["coordinator_headers"]
    assert_impact_scores(estate["big_exercise"], 50.00, 53.00, "LEVEL_2")

    scheduled = validate_success(
        api.schedule_exercise(estate["big_exercise"]["id"], {}, coordinator), 201
    )

    assert_axes(scheduled, execution_state="SCHEDULED")
    site = fx.read_site(api, coordinator, estate["site_small"]["id"])
    assert site["usable_capacity_units"] == 6
    assert_reserved_capacity(site, 6)


def test_one_unit_over_the_ceiling_is_rejected(api):
    """The next two units would exceed the ceiling, so the schedule is refused.

    PRD: "The site's current `reserved_capacity_units` plus this exercise's
    `required_capacity_units` must not exceed the site's
    `usable_capacity_units`."

    Design: Difficulty/boundary_precision_check/capacity_exactly_equal_to_usable_is_allowed_one_unit_over_rejects
    """
    estate = fx.setup_small_site_capacity_scenario(api)
    coordinator = estate["coordinator_headers"]
    fx.schedule(api, coordinator, estate["big_exercise"]["id"])

    validate_error(
        api.schedule_exercise(estate["small_exercise"]["id"], {}, coordinator),
        ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED,
        409,
    )

    assert_axes(
        fx.read_exercise(api, coordinator, estate["small_exercise"]["id"]),
        execution_state="APPROVED",
    )
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_small"]["id"]), 6
    )


def test_touching_site_windows_do_not_conflict(api):
    """An exercise starting at the instant another ends may be scheduled.

    PRD: "Because both windows are half-open, two exercises that merely touch —
    one ending at the exact instant the other begins — do **not** conflict."

    Design: Difficulty/resource_temporal_overlap/site_windows_are_half_open_so_touching_is_allowed_and_one_minute_of_overlap_rejects
    """
    estate = fx.setup_touching_windows_scenario(api)
    coordinator = estate["coordinator_headers"]

    scheduled = validate_success(
        api.schedule_exercise(estate["touching_exercise"]["id"], {}, coordinator), 201
    )

    assert_axes(scheduled, execution_state="SCHEDULED")
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_recovery"]["id"]), 4
    )


def test_one_minute_of_overlap_is_a_window_conflict(api):
    """A window overlapping by a single minute collides with the booked one.

    PRD: "That window is **half-open**: the start instant is inside the
    occupation and the end instant is outside it."

    Design: Difficulty/resource_temporal_overlap/site_windows_are_half_open_so_touching_is_allowed_and_one_minute_of_overlap_rejects
    """
    estate = fx.setup_touching_windows_scenario(api)
    coordinator = estate["coordinator_headers"]
    fx.schedule(api, coordinator, estate["touching_exercise"]["id"])

    validate_error(
        api.schedule_exercise(estate["overlapping_exercise"]["id"], {}, coordinator),
        ApiErrorId.ERR_SITE_WINDOW_CONFLICT,
        409,
    )

    assert_axes(
        fx.read_exercise(api, coordinator, estate["overlapping_exercise"]["id"]),
        execution_state="APPROVED",
    )
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_recovery"]["id"]), 4
    )


def test_reserved_capacity_is_recomputed_after_a_cancellation(api):
    """Cancelling a scheduled exercise rebuilds the site figure from the survivors.

    PRD: "The reserved figure is always produced by a **full recomputation** from
    the exercise table, never by adding or subtracting a delta: it is the sum of
    `required_capacity_units` across every exercise whose `recovery_site_id` is
    this site and whose `execution_state` is `SCHEDULED`, `IN_EXECUTION` or
    `FAILOVER_COMPLETE`."

    Design: Difficulty/compensating_invariant/site_reserved_capacity_equals_sum_over_active_exercises_after_cancellation
    """
    estate = fx.setup_two_approved_reservations(api)
    coordinator = estate["coordinator_headers"]
    site_id = estate["site_recovery"]["id"]

    fx.schedule(api, coordinator, estate["big_exercise"]["id"])
    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 6)
    fx.schedule(api, coordinator, estate["small_exercise"]["id"])
    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 8)
    fx.drive_execution(api, coordinator, estate["big_exercise"]["id"], "CANCEL")

    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 2)
    cancelled = fx.read_exercise(api, coordinator, estate["big_exercise"]["id"])
    assert_axes(
        cancelled, execution_state="CANCELLED", closure_reason="CANCELLED_BY_COORDINATOR"
    )
    assert cancelled["required_capacity_units"] == 6
    assert_axes(
        fx.read_exercise(api, coordinator, estate["small_exercise"]["id"]),
        execution_state="SCHEDULED",
    )


def test_cancelling_an_approved_exercise_leaves_the_site_untouched(api):
    """Only a cancellation out of SCHEDULED releases anything.

    PRD: "Only cancellation from `SCHEDULED` changes site capacity — that
    exercise held a reservation, so the recomputation lowers
    `reserved_capacity_units` by its `required_capacity_units`; the other four
    cancellations held no reservation and the recomputation leaves the site as it
    was."

    Design: Difficulty/compensating_invariant/site_reserved_capacity_equals_sum_over_active_exercises_after_cancellation
    """
    estate = fx.setup_two_approved_reservations(api)
    coordinator = estate["coordinator_headers"]
    site_id = estate["site_recovery"]["id"]
    fx.schedule(api, coordinator, estate["big_exercise"]["id"])

    fx.drive_execution(api, coordinator, estate["small_exercise"]["id"], "CANCEL")

    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 6)
    fx.drive_execution(api, coordinator, estate["big_exercise"]["id"], "CANCEL")
    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 0)
