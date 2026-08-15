"""Exercises: plan-approval gate at start, half-open interval overlap, and
cancellation legality."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_plan,
    assert_exercise_event,
    create_exercise_for_plan,
    create_exercise_payload,
    create_manager_admin_pair,
    create_plan_draft,
    create_started_exercise,
    submit_plan_for_review,
    validate_error,
    validate_success,
)

EM = TEST_USERS["emergency_manager_headers"]


class TestStartRequiresApprovedPlan:
    def test_exercise_start_while_plan_draft_rejected(self, api):
        """PRD §3.3: "Starting requires the referenced plan revision to be
        `APPROVED` at start time — exercising against an unapproved plan is
        rejected with `ERR_PLAN_NOT_APPROVED` — and moves the exercise
        `SCHEDULED` → `IN_PROGRESS`, stamping `started_at`."

        Design: Difficulty/cross_entity_state_dependency/exercise_start_requires_plan_approved
        """
        plan = create_plan_draft(revision_label="EOP-2026-A")
        exercise = create_exercise_for_plan(plan["id"], exercise_name="Tabletop Alpha")
        resp = api.start_exercise(exercise["id"], EM)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_APPROVED)
        reread = validate_success(api.get_exercise(exercise["id"], EM))
        assert reread["status"] == "SCHEDULED"

    def test_exercise_start_succeeds_after_plan_approved(self, api):
        """PRD §3.3: "Starting requires the referenced plan revision to be
        `APPROVED` at start time — exercising against an unapproved plan is
        rejected with `ERR_PLAN_NOT_APPROVED` — and moves the exercise
        `SCHEDULED` → `IN_PROGRESS`, stamping `started_at`."

        Design: Difficulty/cross_entity_state_dependency/exercise_start_requires_plan_approved
        """
        manager_plan = create_plan_draft(revision_label="EOP-2026-A")
        exercise = create_exercise_for_plan(manager_plan["id"],
                                            exercise_name="Tabletop Alpha")
        # Walk the plan through its own review cycle, then start the exercise.
        # The plan was drafted with the shared EM identity; approval runs under
        # an independent administrator identity (segregation of duties, §2.7).
        _, admin = create_manager_admin_pair()
        submit_plan_for_review(manager_plan["id"])
        approve_plan(manager_plan["id"], admin["id"])

        started = validate_success(api.start_exercise(exercise["id"], EM))
        assert_exercise_event(started)
        assert started["status"] == "IN_PROGRESS"
        assert started["started_at"] is not None


class TestHalfOpenOverlap:
    def _plan(self, api):
        return create_plan_draft(revision_label="EOP-2026-X")

    def test_back_to_back_exercises_permitted(self, api):
        """PRD §3.3: "Back-to-back exercises, where one's end equals another's
        start, do not overlap and are permitted."

        Design: Difficulty/resource_temporal_overlap/exercise_half_open_interval_adjacency
        """
        plan = self._plan(api)
        ex_a = create_exercise_for_plan(
            plan["id"], exercise_name="Ex-A", exercise_type="FUNCTIONAL",
            scenario_category="HAZMAT",
            scheduled_start="2026-09-01T10:00:00Z",
            scheduled_end="2026-09-01T12:00:00Z",
        )
        ex_b = create_exercise_for_plan(
            plan["id"], exercise_name="Ex-B", exercise_type="FUNCTIONAL",
            scenario_category="HAZMAT",
            scheduled_start="2026-09-01T12:00:00Z",
            scheduled_end="2026-09-01T14:00:00Z",
        )
        assert ex_a["status"] == "SCHEDULED"
        assert ex_b["status"] == "SCHEDULED", (
            "B.start == A.end is adjacency, not overlap, under half-open semantics"
        )

    def test_straddling_exercise_rejected(self, api):
        """PRD §3.3: "Scheduling treats each exercise as a half-open interval that
        includes its start and excludes its end: the new exercise is rejected with
        `ERR_EXERCISE_TIME_CONFLICT` when its interval overlaps any existing
        exercise in `SCHEDULED` or `IN_PROGRESS` — overlap meaning the new start
        falls strictly before the other's end and the new end falls strictly after
        the other's start."

        Design: Difficulty/resource_temporal_overlap/exercise_half_open_interval_adjacency
        """
        plan = self._plan(api)
        create_exercise_for_plan(
            plan["id"], exercise_name="Ex-A",
            scheduled_start="2026-09-01T10:00:00Z",
            scheduled_end="2026-09-01T12:00:00Z",
        )
        create_exercise_for_plan(
            plan["id"], exercise_name="Ex-B",
            scheduled_start="2026-09-01T12:00:00Z",
            scheduled_end="2026-09-01T14:00:00Z",
        )
        resp = api.create_exercise(
            create_exercise_payload(
                plan["id"], exercise_name="Ex-C",
                scheduled_start="2026-09-01T11:00:00Z",
                scheduled_end="2026-09-01T13:00:00Z",
            ),
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_EXERCISE_TIME_CONFLICT)


class TestCancelLegality:
    def test_exercise_cancel_in_progress_rejected(self, api):
        """PRD §3.3: "An exercise already underway cannot be cancelled; the
        attempt is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/exercise_cancel_in_progress_rejected
        """
        started, _plan, _ctx = create_started_exercise(
            exercise_name="Live drill", exercise_type="FULL_SCALE",
            scenario_category="HUMAN",
        )
        resp = api.cancel_exercise(started["id"], EM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        reread = validate_success(api.get_exercise(started["id"], EM))
        assert reread["status"] == "IN_PROGRESS"

    def test_exercise_invalid_time_range_rejected(self, api):
        """PRD §3.3: "The scheduled end must be strictly after the scheduled
        start, else the create is rejected with `ERR_INVALID_TIME_RANGE`."

        Design: Corner/validations/exercise_invalid_time_range_rejected
        """
        plan = create_plan_draft(revision_label="EOP-time")
        resp = api.create_exercise(
            create_exercise_payload(
                plan["id"], exercise_name="Zero-length",
                scheduled_start="2026-09-01T10:00:00Z",
                scheduled_end="2026-09-01T10:00:00Z",
            ),
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)
