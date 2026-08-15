"""Evaluation pipeline: request gating, scheduling rules, scoring, appeals."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_active_evaluator,
    create_active_handler,
    create_forming_team,
    register_animal,
    request_evaluation,
    run_sweeps,
    schedule_evaluation_ok,
    score_evaluation_ok,
    set_clock,
    make_evaluator_headers,
    make_handler_headers,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _forming_team_with_evaluation(name: str):
    """Handler (ACTIVE) + animal + FORMING team + REQUESTED evaluation."""
    handler = create_active_handler(full_name=name)
    animal = register_animal(handler["id"], name=f"{name} Animal")
    team = create_forming_team(handler["id"], animal["id"], f"{name} Team")
    evaluation = request_evaluation(handler["id"], team["id"])
    return handler, animal, team, evaluation


def _three_requested_evaluations():
    """Three FORMING teams each holding a REQUESTED evaluation; one shared evaluator."""
    evaluator = create_active_evaluator(full_name="Ev Buf", specializations=["DOG"])
    evals = []
    for i in (1, 2, 3):
        _h, _a, _t, e = _forming_team_with_evaluation(f"H E{i}")
        evals.append(e)
    return evaluator, evals


class TestCompositeBoundary:
    def test_first_attempt_composite_below_bar_fails_then_appeal(self):
        """PRD §3.2: "The `composite_score` is sixty percent of the aptitude score plus forty percent of the obedience score, rounded half-up to two decimal places. The pass rule depends on the attempt: on a first attempt the team passes when both section scores are at least seventy and the composite is at least 75.0; on a retake — `attempt_number` two or higher — the bar rises to a composite of at least 80.0 alongside the same section floors."
        PRD §3.2: "The handler may appeal within fourteen days of `failed_at`: appealing a non-`FAILED` evaluation fails with `ERR_EVALUATION_NOT_FAILED`, and appealing after the fourteenth day fails with `ERR_EVALUATION_APPEAL_WINDOW_CLOSED`; a timely appeal moves the evaluation `FAILED → APPEALED`, from which a `ProgramAdmin` schedules the retake under the ordinary scheduling rules."

        Design: Difficulty/boundary_precision_check/evaluation_composite_boundary
        """
        handler, _a, _t, evaluation = _forming_team_with_evaluation("H B2")
        evaluator = create_active_evaluator(full_name="Ev B2", specializations=["DOG"])
        schedule_evaluation_ok(evaluation["id"], evaluator["id"])
        scored = score_evaluation_ok(evaluation["id"], evaluator["id"],
                                     aptitude_score=70, obedience_score=70)
        # Section floors met (70 >= 70 both) but composite 70.0 < 75.0 -> FAILED.
        assert scored["status"] == "FAILED"
        assert scored["composite_score"] == pytest.approx(70.0), (
            f"composite must be 0.6*70 + 0.4*70 = 70.0, got {scored['composite_score']}"
        )
        appealed = validate_success(
            api_client.appeal_evaluation(evaluation["id"], make_handler_headers(handler["id"]))
        )
        assert appealed["status"] == "APPEALED"

    def test_retake_passes_at_equality_of_higher_bar(self):
        """PRD §3.2: "The `composite_score` is sixty percent of the aptitude score plus forty percent of the obedience score, rounded half-up to two decimal places. The pass rule depends on the attempt: on a first attempt the team passes when both section scores are at least seventy and the composite is at least 75.0; on a retake — `attempt_number` two or higher — the bar rises to a composite of at least 80.0 alongside the same section floors."
        PRD §3.2: "Successful scheduling sets `evaluator_id`, `scheduled_start`, and `scheduled_end`, moves the evaluation to `SCHEDULED`, and — when the evaluation was re-scheduled out of `APPEALED` — increments `attempt_number` by one."

        Design: Difficulty/boundary_precision_check/evaluation_composite_boundary
        """
        handler, _a, _t, evaluation = _forming_team_with_evaluation("H B2r")
        evaluator = create_active_evaluator(full_name="Ev B2r", specializations=["DOG"])
        schedule_evaluation_ok(evaluation["id"], evaluator["id"])
        scored = score_evaluation_ok(evaluation["id"], evaluator["id"],
                                     aptitude_score=70, obedience_score=70)
        assert scored["status"] == "FAILED"
        validate_success(
            api_client.appeal_evaluation(evaluation["id"], make_handler_headers(handler["id"]))
        )
        rescheduled = schedule_evaluation_ok(
            evaluation["id"], evaluator["id"],
            "2026-08-04T10:00:00Z", "2026-08-04T11:00:00Z",
        )
        assert rescheduled["attempt_number"] == 2, (
            "Re-scheduling out of APPEALED must increment attempt_number"
        )
        rescored = score_evaluation_ok(
            evaluation["id"], evaluator["id"],
            aptitude_score=80, obedience_score=80,
            score_at="2026-08-04T11:00:00Z",
        )
        # Retake bar: composite >= 80.0; 80/80 yields exactly 80.0 -> PASSED at equality.
        assert rescored["status"] == "PASSED"
        assert rescored["composite_score"] == pytest.approx(80.0)


class TestEvaluationRequestGating:
    def test_evaluation_request_requires_active_handler(self):
        """PRD §3.2: "A handler initiates the certification pipeline by requesting an evaluation for a team — the payload carries the `team_id` — provided the handler is `ACTIVE` (otherwise `ERR_HANDLER_NOT_ACTIVE`) and the team is still `FORMING` (otherwise `ERR_TEAM_NOT_FORMING`)."
        PRD §3.1: "Reinstatement by a `ComplianceOfficer` requires `SUSPENDED` (otherwise `ERR_HANDLER_NOT_SUSPENDED`) and clears `suspension_reason`."

        Design: Difficulty/cross_entity_state_dependency/evaluation_request_requires_handler_active
        """
        handler, _a, team, _e = _forming_team_with_evaluation("H X3")
        # Team already consumed its first evaluation request above; make a fresh one
        # so the trigger call targets a FORMING team with no prior evaluation.
        validate_success(
            api_client.suspend_handler(handler["id"], {"reason": "background check refresh"}, COMPLIANCE)
        )
        blocked = api_client.create_evaluation({"team_id": team["id"]},
                                               make_handler_headers(handler["id"]))
        validate_error(blocked, ApiErrorId.ERR_HANDLER_NOT_ACTIVE)

        validate_success(api_client.reinstate_handler(handler["id"], COMPLIANCE))
        allowed = api_client.create_evaluation({"team_id": team["id"]},
                                               make_handler_headers(handler["id"]))
        assert validate_success(allowed, 201)["status"] == "REQUESTED"

    def test_evaluation_request_after_reinstate_carries_defaults(self):
        """PRD §3.2: "The new evaluation starts `REQUESTED` with `requested_at` stamped at creation, `attempt_number` at one, and `evaluator_id`, `scheduled_start`, `scheduled_end`, and both score fields unset."
        PRD §3.2: "A handler initiates the certification pipeline by requesting an evaluation for a team — the payload carries the `team_id` — provided the handler is `ACTIVE` (otherwise `ERR_HANDLER_NOT_ACTIVE`) and the team is still `FORMING` (otherwise `ERR_TEAM_NOT_FORMING`)."

        Design: Difficulty/cross_entity_state_dependency/evaluation_request_requires_handler_active
        """
        handler = create_active_handler(full_name="H X3b")
        animal = register_animal(handler["id"], name="D")
        team = create_forming_team(handler["id"], animal["id"], "TX3b")
        validate_success(
            api_client.suspend_handler(handler["id"], {"reason": "audit"}, COMPLIANCE)
        )
        validate_success(api_client.reinstate_handler(handler["id"], COMPLIANCE))
        resp = api_client.create_evaluation({"team_id": team["id"]},
                                            make_handler_headers(handler["id"]))
        data = validate_success(resp, 201)
        assert data["status"] == "REQUESTED"
        assert data["attempt_number"] == 1
        assert data.get("requested_at"), "requested_at must be stamped at creation"
        assert data.get("evaluator_id") is None


class TestEvaluatorSchedulingRules:
    def test_buffered_interval_gap_zero_conflicts(self):
        """PRD §3.2: "First, a conflict rule with a thirty-minute hygiene buffer: the new evaluation's raw interval — start inclusive, end exclusive — may not intersect the buffered interval of any other `SCHEDULED` evaluation of the same evaluator, where each existing evaluation is padded by thirty minutes on both sides; equivalently the gap between back-to-back sessions must be at least thirty minutes, so bare adjacency conflicts while a gap of exactly thirty minutes passes (`ERR_EVALUATOR_SCHEDULING_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/evaluator_buffered_interval
        """
        evaluator, (e1, e2, _e3) = _three_requested_evaluations()
        first = schedule_evaluation_ok(
            e1["id"], evaluator["id"], "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z"
        )
        assert first["status"] == "SCHEDULED"
        # Bare adjacency (gap 0) conflicts under the buffered-interval rule.
        conflict = api_client.schedule_evaluation(
            e2["id"],
            {"evaluator_id": evaluator["id"],
             "scheduled_start": "2026-08-03T10:00:00Z",
             "scheduled_end": "2026-08-03T11:00:00Z"},
            ADMIN,
        )
        validate_error(conflict, ApiErrorId.ERR_EVALUATOR_SCHEDULING_CONFLICT)

    def test_buffered_interval_gap_thirty_passes(self):
        """PRD §3.2: "First, a conflict rule with a thirty-minute hygiene buffer: the new evaluation's raw interval — start inclusive, end exclusive — may not intersect the buffered interval of any other `SCHEDULED` evaluation of the same evaluator, where each existing evaluation is padded by thirty minutes on both sides; equivalently the gap between back-to-back sessions must be at least thirty minutes, so bare adjacency conflicts while a gap of exactly thirty minutes passes (`ERR_EVALUATOR_SCHEDULING_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/evaluator_buffered_interval
        """
        evaluator, (e1, _e2, e3) = _three_requested_evaluations()
        first = schedule_evaluation_ok(
            e1["id"], evaluator["id"], "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z"
        )
        assert first["status"] == "SCHEDULED"
        # Gap exactly 30 minutes: raw [10:30, 11:30) clears buffered [08:30, 10:30).
        ok = api_client.schedule_evaluation(
            e3["id"],
            {"evaluator_id": evaluator["id"],
             "scheduled_start": "2026-08-03T10:30:00Z",
             "scheduled_end": "2026-08-03T11:30:00Z"},
            ADMIN,
        )
        assert validate_success(ok, 200)["status"] == "SCHEDULED"


class TestEvaluationViolations:
    def test_evaluation_cancelled_cannot_be_scored(self):
        """PRD §3.2: "Scoring belongs to the assigned `Evaluator` and only after the session has concluded: the evaluation must be `SCHEDULED` (otherwise `ERR_EVALUATION_NOT_SCHEDULED`), the acting evaluator must be the one named in `evaluator_id` (otherwise `ERR_OWNERSHIP_MISMATCH`), and the current time must be at or past `scheduled_end` (otherwise `ERR_EVALUATION_NOT_CONCLUDED`)."
        PRD §3.2: "Cancellation, available to the handler or a `ProgramAdmin` from `REQUESTED`, `SCHEDULED`, or `APPEALED` (otherwise `ERR_EVALUATION_NOT_CANCELLABLE`), moves the evaluation to the terminal `CANCELLED` state."

        Design: Corner/state_machines/evaluation_cancelled_cannot_be_scored
        """
        handler, _a, _t, evaluation = _forming_team_with_evaluation("H EC")
        evaluator = create_active_evaluator(full_name="Ev EC", specializations=["DOG"])
        validate_success(
            api_client.cancel_evaluation(evaluation["id"], make_handler_headers(handler["id"]))
        )
        resp = api_client.score_evaluation(
            evaluation["id"], {"aptitude_score": 90, "obedience_score": 90},
            make_evaluator_headers(evaluator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_SCHEDULED)

    def test_evaluation_appeal_window_closed_then_swept(self):
        """PRD §3.2: "The handler may appeal within fourteen days of `failed_at`: appealing a non-`FAILED` evaluation fails with `ERR_EVALUATION_NOT_FAILED`, and appealing after the fourteenth day fails with `ERR_EVALUATION_APPEAL_WINDOW_CLOSED`; a timely appeal moves the evaluation `FAILED → APPEALED`, from which a `ProgramAdmin` schedules the retake under the ordinary scheduling rules."
        PRD §3.2: "Two sweeps keep the pipeline clean: a `REQUESTED` evaluation left unscheduled for more than sixty days after `requested_at` expires, and a `FAILED` evaluation whose appeal window lapses — more than fourteen days past `failed_at` — likewise moves to `EXPIRED`."

        Design: Corner/state_machines/evaluation_appeal_window_closed_then_swept
        """
        handler, _a, _t, evaluation = _forming_team_with_evaluation("H AW")
        evaluator = create_active_evaluator(full_name="Ev AW", specializations=["DOG"])
        schedule_evaluation_ok(evaluation["id"], evaluator["id"])
        scored = score_evaluation_ok(evaluation["id"], evaluator["id"],
                                     aptitude_score=60, obedience_score=60)
        assert scored["status"] == "FAILED"
        set_clock("2026-08-17T00:00:00Z")  # > failed_at (2026-08-02T11:00Z) + 14 days
        resp = api_client.appeal_evaluation(evaluation["id"], make_handler_headers(handler["id"]))
        validate_error(resp, ApiErrorId.ERR_EVALUATION_APPEAL_WINDOW_CLOSED)

        sweep = run_sweeps()
        assert sweep["evaluations_expired"] == 1, (
            f"The lapsed FAILED evaluation must be swept to EXPIRED, got {sweep}"
        )
        fetched = validate_success(api_client.get_evaluation(evaluation["id"], ADMIN))
        assert fetched["status"] == "EXPIRED"

    def test_evaluator_species_mismatch_rejected(self):
        """PRD §3.2: "Scheduling is performed by a `ProgramAdmin`, who supplies the `evaluator_id`, `scheduled_start`, and `scheduled_end`. The evaluation must stand in `REQUESTED` or `APPEALED` (otherwise `ERR_EVALUATION_NOT_SCHEDULABLE`); the evaluator must be `ACTIVE` (`ERR_EVALUATOR_NOT_ACTIVE`); the team's animal species must appear in the evaluator's `specializations` (`ERR_EVALUATOR_SPECIES_MISMATCH`); the `scheduled_start` must not lie in the past (`ERR_EVALUATION_SCHEDULE_IN_PAST`); and the session must run between thirty and one hundred twenty minutes inclusive (`ERR_EVALUATION_DURATION_INVALID`)."

        Design: Corner/errors/evaluator_species_mismatch_rejected
        """
        _h, _a, _t, evaluation = _forming_team_with_evaluation("H SM")  # DOG team
        cat_only = create_active_evaluator(full_name="Ev SM", specializations=["CAT"])
        resp = api_client.schedule_evaluation(
            evaluation["id"],
            {"evaluator_id": cat_only["id"],
             "scheduled_start": "2026-08-03T10:00:00Z",
             "scheduled_end": "2026-08-03T11:00:00Z"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATOR_SPECIES_MISMATCH)

    def test_evaluator_daily_cap_rejected(self):
        """PRD §3.2: "Second, a daily cap: the evaluator must have fewer than `max_evaluations_per_day` `SCHEDULED` evaluations on that UTC calendar day (`ERR_EVALUATOR_DAILY_CAP_EXCEEDED`)."

        Design: Corner/errors/evaluator_daily_cap_rejected
        """
        _h1, _a1, _t1, e1 = _forming_team_with_evaluation("H D1")
        _h2, _a2, _t2, e2 = _forming_team_with_evaluation("H D2")
        evaluator = create_active_evaluator(
            full_name="Ev DC", specializations=["DOG"], max_evaluations_per_day=1,
        )
        first = schedule_evaluation_ok(
            e1["id"], evaluator["id"], "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z"
        )
        assert first["status"] == "SCHEDULED"
        # Buffer gap is 60 minutes (>= 30) but the daily cap of 1 is already used.
        resp = api_client.schedule_evaluation(
            e2["id"],
            {"evaluator_id": evaluator["id"],
             "scheduled_start": "2026-08-03T11:00:00Z",
             "scheduled_end": "2026-08-03T12:00:00Z"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATOR_DAILY_CAP_EXCEEDED)

    def test_score_before_conclusion_rejected(self):
        """PRD §3.2: "Scoring belongs to the assigned `Evaluator` and only after the session has concluded: the evaluation must be `SCHEDULED` (otherwise `ERR_EVALUATION_NOT_SCHEDULED`), the acting evaluator must be the one named in `evaluator_id` (otherwise `ERR_OWNERSHIP_MISMATCH`), and the current time must be at or past `scheduled_end` (otherwise `ERR_EVALUATION_NOT_CONCLUDED`)."

        Design: Corner/errors/score_before_conclusion_rejected
        """
        _h, _a, _t, evaluation = _forming_team_with_evaluation("H SC")
        evaluator = create_active_evaluator(full_name="Ev SC", specializations=["DOG"])
        schedule_evaluation_ok(
            evaluation["id"], evaluator["id"],
            "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z",
        )
        set_clock("2026-08-03T10:30:00Z")  # mid-session: now < scheduled_end
        resp = api_client.score_evaluation(
            evaluation["id"], {"aptitude_score": 90, "obedience_score": 90},
            make_evaluator_headers(evaluator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_CONCLUDED)
