"""Operations refused because of the lifecycle state of a different entity.

A review that is itself perfectly scorable is refused because the sampling period
two hops away was locked by a filed accreditation report; a retraining session is
refused because the curriculum version is still a draft; a go-live is refused
because a count of certified dispatchers has not reached the rollout's target.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import approx1, approx2, assert_instant_equals
from test_helpers.test_users import ADMIN, DIRECTOR, REVIEWER, SUPERVISOR

WORKING_CLOCK = "2026-08-20T00:00:00Z"

CLEAN_SECTIONS = {
    "case_entry": (23, 25),
    "key_questions": (23, 25),
    "pre_arrival": (23, 25),
    "final_coding": (23, 25),
}
WEAK_SECTIONS = {
    "case_entry": (20, 25),
    "key_questions": (20, 25),
    "pre_arrival": (20, 25),
    "final_coding": (20, 25),
}


def _locked_period_with_a_frozen_scored_review(api):
    """One review FINALIZED and one left SCORED inside a period frozen by a filed report."""
    program = fx.new_program(api, target_compliance_pct=90.0, watch_floor_pct=80.0)
    fx.new_approved_version(api, program["id"], version_label="MPDS-13.0")
    dispatcher = fx.new_dispatcher(api, program["id"], employee_code="EMD-J01",
                                   full_name="Vera Osei")
    fx.set_clock(api, WORKING_CLOCK)
    call_one = fx.ingest_call(api, dispatcher["id"], call_reference="C-J001",
                              received_at="2026-08-05T09:00:00Z")
    call_two = fx.ingest_call(api, dispatcher["id"], call_reference="C-J002",
                              received_at="2026-08-06T09:00:00Z")
    period = fx.new_period(api, program["id"], target_sample_count=2)
    review_one = fx.target(api, period["id"], call_one["id"], "COMPLAINT")
    review_two = fx.target(api, period["id"], call_two["id"], "COMPLAINT")
    fx.score(api, review_one["id"], sections=CLEAN_SECTIONS,
             expected_review_version=review_one["version"])
    fx.score(api, review_two["id"], sections=WEAK_SECTIONS,
             expected_review_version=review_two["version"])
    fx.finalize(api, review_one["id"], "clean")
    fx.close_period(api, period["id"])
    report = fx.new_report(api, program["id"])
    fx.submit_report(api, report["id"])
    return {
        "program_id": program["id"],
        "period_id": period["id"],
        "review_one_id": review_one["id"],
        "review_two_id": review_two["id"],
    }


def test_scoring_a_frozen_review_inside_a_locked_period_is_refused(api):
    """PRD 3.5: "The review's sampling period must not be `LOCKED`; a frozen work-product
    review can no longer be re-scored and the attempt is rejected with `ERR_PERIOD_LOCKED`."
    PRD 3.9: "A review in `SCORED` or `DISPUTED`, by contrast, is real audit work product
    and is deliberately preserved rather than discarded — it is simply frozen, so any later
    attempt to submit a score against it or to finalize it fails with `ERR_PERIOD_LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/scoring_and_finalizing_are_blocked_by_the_periods_locked_state
    """
    env = _locked_period_with_a_frozen_scored_review(api)
    frozen = fx.get_review(api, env["review_two_id"])
    assert frozen["status"] == "SCORED"

    response = api.submit_scores(
        env["review_two_id"],
        f.section_score_payload(
            frozen["version"],
            {
                "case_entry": (25, 25),
                "key_questions": (25, 25),
                "pre_arrival": (25, 25),
                "final_coding": (25, 25),
            },
            "10-C-4",
        ),
        REVIEWER,
    )
    validate_error(response, err.ERR_PERIOD_LOCKED)

    sheets = fx.list_sheets(api, env["review_two_id"])
    assert len(sheets) == 1, f"the refused submission must append nothing, got {sheets}"
    assert fx.get_review(api, env["review_two_id"])["current_sheet_round"] == 1


def test_finalizing_a_frozen_review_inside_a_locked_period_is_refused(api):
    """PRD 3.7: "The review's sampling period must not be `LOCKED`, or the request is
    refused with `ERR_PERIOD_LOCKED`."
    PRD 3.9: "A review in `SCORED` or `DISPUTED`, by contrast, is real audit work product
    and is deliberately preserved rather than discarded — it is simply frozen, so any later
    attempt to submit a score against it or to finalize it fails with `ERR_PERIOD_LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/scoring_and_finalizing_are_blocked_by_the_periods_locked_state
    """
    env = _locked_period_with_a_frozen_scored_review(api)

    response = api.finalize_review(
        env["review_two_id"], {"finalization_note": "late finalization"}, SUPERVISOR
    )
    validate_error(response, err.ERR_PERIOD_LOCKED)

    still_scored = fx.get_review(api, env["review_two_id"])
    assert still_scored["status"] == "SCORED"
    assert still_scored["finalized_at"] is None
    assert still_scored["final_composite_score"] is None


def test_locking_freezes_the_scored_review_and_leaves_the_finalized_one_untouched(api):
    """PRD 3.9: "Every sampling period of the programme that is in `CLOSED` and whose
    half-open window overlaps the report's half-open window transitions `CLOSED → LOCKED`,
    stamping `locked_at` from the logical clock."
    PRD 3.9: "Reviews already `FINALIZED` are of course untouched: they are the very rows
    the filed figure was computed from."

    Design: Difficulty/cross_entity_state_dependency/scoring_and_finalizing_are_blocked_by_the_periods_locked_state
    """
    env = _locked_period_with_a_frozen_scored_review(api)

    period = fx.get_period(api, env["program_id"], env["period_id"])
    assert period["status"] == "LOCKED"
    assert_instant_equals(period["locked_at"], WORKING_CLOCK)

    frozen = fx.get_review(api, env["review_two_id"])
    assert frozen["status"] == "SCORED", "only SELECTED reviews are voided by the lock"
    assert frozen["void_reason"] is None

    finalized = fx.get_review(api, env["review_one_id"])
    assert finalized["status"] == "FINALIZED"
    assert finalized["final_composite_score"] == approx1(92.0)


def _draft_curriculum_env(api):
    """A dispatcher with an ASSIGNED MANUAL plan and a curriculum version still in DRAFT."""
    program = fx.new_program(api, name="Tallow EMD QA", accreditation_body="NAED_LOCAL")
    version = fx.new_version(
        api,
        program["id"],
        version_label="MPDS-13.2",
        effective_from="2026-07-01T00:00:00Z",
    )
    dispatcher = fx.new_dispatcher(api, program["id"], employee_code="EMD-K01",
                                   full_name="Wren Adeyemi")
    fx.set_clock(api, WORKING_CLOCK)
    plan = fx.new_coaching_plan(
        api,
        dispatcher["id"],
        expected_dispatcher_version=dispatcher["version"],
        severity="STANDARD",
        focus_area="KEY_QUESTIONS",
    )
    return {
        "program_id": program["id"],
        "version_id": version["id"],
        "dispatcher_id": dispatcher["id"],
        "plan_id": plan["id"],
    }


def _session_request(version_id):
    return f.retraining_session_payload(
        version_id,
        starts_at="2026-08-25T09:00:00Z",
        ends_at="2026-08-25T13:00:00Z",
        modality="CLASSROOM",
    )


def test_scheduling_a_session_on_a_draft_curriculum_is_refused(api):
    """PRD 3.8: "The curriculum version must be in `APPROVED` or `ACTIVE` — a draft or
    superseded curriculum is refused with `ERR_CURRICULUM_VERSION_NOT_TRAINABLE` — and must
    belong to the coached dispatcher's programme, or the request is refused for programme
    scope."

    Design: Difficulty/cross_entity_state_dependency/retraining_session_requires_the_curriculum_version_to_be_out_of_draft
    """
    env = _draft_curriculum_env(api)
    assert fx.get_version(api, env["version_id"])["status"] == "DRAFT"

    response = api.create_retraining_session(
        env["plan_id"], _session_request(env["version_id"]), SUPERVISOR
    )
    validate_error(response, err.ERR_CURRICULUM_VERSION_NOT_TRAINABLE)

    plan = fx.get_plan(api, env["plan_id"])
    assert plan["status"] == "ASSIGNED"
    assert plan["credited_hours"] == approx2(0.00)
    sessions = validate_success(
        api.list_retraining_sessions(env["plan_id"], SUPERVISOR, {"limit": 100})
    )
    assert sessions == [], f"the refused request must create nothing, got {sessions}"


def test_approving_the_curriculum_lets_the_identical_request_schedule(api):
    """PRD 3.2: "Approving a draft moves it `DRAFT → APPROVED`, stamps
    `approved_by_user_id` with the director's `X-User-ID`, and may carry an optional
    `approval_note`."
    PRD 3.8: "A successful scheduling writes the session against its plan through
    `coaching_plan_id`, with `status` `SCHEDULED`, no `attendance_confirmed`, no
    `cancel_reason` and no `completed_at`, and computes `duration_hours` as the elapsed time
    from `starts_at` to `ends_at` expressed in hours — the elapsed seconds divided by 3600 —
    rounded half up to 2 decimal places."

    Design: Difficulty/cross_entity_state_dependency/retraining_session_requires_the_curriculum_version_to_be_out_of_draft
    """
    env = _draft_curriculum_env(api)
    refused = api.create_retraining_session(
        env["plan_id"], _session_request(env["version_id"]), SUPERVISOR
    )
    validate_error(refused, err.ERR_CURRICULUM_VERSION_NOT_TRAINABLE)

    approved = validate_success(
        api.approve_protocol_version(env["version_id"], {"approval_note": "adopted"}, DIRECTOR)
    )
    assert approved["status"] == "APPROVED"

    session = validate_success(
        api.create_retraining_session(
            env["plan_id"], _session_request(env["version_id"]), SUPERVISOR
        ),
        expected_status=201,
    )
    assert session["protocol_version_id"] == env["version_id"]
    assert session["coaching_plan_id"] == env["plan_id"]
    assert session["status"] == "SCHEDULED"
    assert session["duration_hours"] == approx2(4.00)
    assert session["completed_at"] is None
    assert session["cancel_reason"] is None


def test_scheduling_moves_the_plan_out_of_assigned_and_lists_under_the_curriculum(api):
    """PRD 3.8: "If the plan was in `ASSIGNED`, scheduling moves it
    `ASSIGNED → IN_PROGRESS`."

    Design: Difficulty/cross_entity_state_dependency/retraining_session_requires_the_curriculum_version_to_be_out_of_draft
    """
    env = _draft_curriculum_env(api)
    fx.approve_version(api, env["version_id"])
    session = fx.new_session(
        api,
        env["plan_id"],
        env["version_id"],
        starts_at="2026-08-25T09:00:00Z",
        ends_at="2026-08-25T13:00:00Z",
    )

    plan = fx.get_plan(api, env["plan_id"])
    assert plan["status"] == "IN_PROGRESS"
    assert plan["credited_hours"] == approx2(0.00), "a scheduled session credits no hours yet"

    listed = validate_success(
        api.list_sessions_for_version(env["version_id"], ADMIN, {"limit": 100})
    )
    assert [row["id"] for row in listed] == [session["id"]]


def _half_trained_rollout_env(api):
    """A rollout needing two certified dispatchers but holding only one, window already open."""
    program = fx.new_program(api, name="Umber EMD QA", accreditation_body="IAED")
    version = fx.new_approved_version(
        api, program["id"], version_label="MPDS-14.0",
        effective_from="2026-07-01T00:00:00Z",
    )
    first = fx.new_dispatcher(api, program["id"], employee_code="EMD-L01",
                              full_name="Xiomara Petit")
    second = fx.new_dispatcher(api, program["id"], employee_code="EMD-L02",
                               full_name="Yosef Brandt")
    fx.set_clock(api, WORKING_CLOCK)
    rollout = fx.new_rollout(
        api,
        version["id"],
        scheduled_golive_at="2026-08-01T00:00:00Z",
        target_dispatcher_count=2,
        required_training_hours=3.0,
    )
    fx.certify(api, first["id"], version["id"])
    return {
        "program_id": program["id"],
        "version_id": version["id"],
        "first_id": first["id"],
        "second_id": second["id"],
        "rollout_id": rollout["id"],
    }


def test_go_live_is_refused_while_the_training_rollup_is_only_in_progress(api):
    """PRD 3.3: "When that count is 0 the training dimension reads `NOT_STARTED`; when it is
    at or above `target_dispatcher_count` it reads `COMPLETE`, so hitting the target exactly
    is enough; anything between reads `IN_PROGRESS`."
    PRD 3.3: "The `training_status` must be `COMPLETE`, or the request is refused with
    `ERR_TRAINING_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/golive_requires_the_rollouts_training_dimension_to_be_complete
    """
    env = _half_trained_rollout_env(api)
    before = fx.get_rollout(api, env["version_id"], env["rollout_id"])
    assert before["trained_dispatcher_count"] == 1
    assert before["training_status"] == "IN_PROGRESS"
    assert before["golive_status"] == "SCHEDULED"

    response = api.go_live(
        env["rollout_id"], {"golive_note": "premature go-live attempt"}, ADMIN
    )
    validate_error(response, err.ERR_TRAINING_INCOMPLETE)


def test_the_refused_go_live_runs_no_part_of_the_activation_cascade(api):
    """PRD 3.3: "And the logical clock must be at or after `scheduled_golive_at` — the
    instant itself qualifies — or the request is refused with `ERR_GOLIVE_WINDOW_NOT_OPEN`."
    PRD 3.3: "The first link takes the rollout's own version `APPROVED → ACTIVE` and stamps
    its `activated_at`."

    Design: Difficulty/cross_entity_state_dependency/golive_requires_the_rollouts_training_dimension_to_be_complete
    """
    env = _half_trained_rollout_env(api)

    response = api.go_live(
        env["rollout_id"], {"golive_note": "premature go-live attempt"}, ADMIN
    )
    validate_error(response, err.ERR_TRAINING_INCOMPLETE)

    rollout = fx.get_rollout(api, env["version_id"], env["rollout_id"])
    assert rollout["golive_status"] == "SCHEDULED"
    assert rollout["went_live_at"] is None
    assert_instant_equals(rollout["scheduled_golive_at"], "2026-08-01T00:00:00Z")

    version = fx.get_version(api, env["version_id"])
    assert version["status"] == "APPROVED", "the readiness gate blocks activation entirely"
    assert version["activated_at"] is None


def test_certifying_the_second_dispatcher_completes_the_rollup_and_unblocks_go_live(api):
    """PRD 3.3: "A successful certification moves `certification_status` from
    `PROVISIONAL → CERTIFIED`, or from `LAPSED → CERTIFIED` when it is a re-certification
    onto a newer version, sets `certified_protocol_version_id` and `certified_at`, and then
    bubbles upward: every rollout on the target version — and, on a re-certification, every
    rollout on the version the dispatcher is leaving — recomputes its
    `trained_dispatcher_count` and re-derives its `training_status`, which is how a rollout
    crosses `TRAINING_NOT_STARTED → TRAINING_IN_PROGRESS` on the first certification and
    `TRAINING_IN_PROGRESS → TRAINING_COMPLETE` on the one that reaches the target."
    PRD 3.3: "When all four hold, the rollout crosses `GOLIVE_SCHEDULED → GOLIVE_LIVE`,
    `went_live_at` is stamped from the logical clock, and Cascade B runs in five links."

    Design: Difficulty/cross_entity_state_dependency/golive_requires_the_rollouts_training_dimension_to_be_complete
    """
    env = _half_trained_rollout_env(api)
    validate_error(
        api.go_live(env["rollout_id"], {"golive_note": "premature go-live attempt"}, ADMIN),
        err.ERR_TRAINING_INCOMPLETE,
    )

    fx.certify(api, env["second_id"], env["version_id"])
    ready = fx.get_rollout(api, env["version_id"], env["rollout_id"])
    assert ready["trained_dispatcher_count"] == 2
    assert ready["training_status"] == "COMPLETE"

    gone_live = validate_success(
        api.go_live(env["rollout_id"], {"golive_note": "premature go-live attempt"}, ADMIN)
    )
    assert gone_live["golive_status"] == "LIVE"
    assert_instant_equals(gone_live["went_live_at"], WORKING_CLOCK)

    version = fx.get_version(api, env["version_id"])
    assert version["status"] == "ACTIVE"
    assert_instant_equals(version["activated_at"], WORKING_CLOCK)
