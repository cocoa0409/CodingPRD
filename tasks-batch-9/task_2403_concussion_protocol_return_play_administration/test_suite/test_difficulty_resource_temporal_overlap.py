"""
Two timed windows with opposite boundary conventions.

The rest buffer between rungs is half-open, so a stage may start on the boundary
instant; a consultant's examination block is closed at both ends, so a second
examination may not start on the instant the first one ends.  Both are proved one
second either side of the line.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INC_EXAM_WINDOW_CONFLICT, ERR_STAGE_REST_BUFFER_VIOLATION
from test_helpers.assertions import assert_instant, assert_page_meta, assert_return_step
from test_helpers.test_users import ADMIN


def _setup_second_screened_evaluation(api):
    """
    The canonical examination in progress with Dr Osei, plus a second Harbor City
    player screened at 18:35 and waiting for a locker room.
    """
    ctx = fx.setup_locker_room_exam(api)
    player2 = fx.add_second_player(api, ctx)

    fx.set_clock(api, "2026-09-13T18:35:00Z")
    evaluation = validate_success(
        api.create_sideline_evaluation(
            f.evaluation_payload(
                player2["id"], ctx["game_id"], trigger_source="CLUB_MEDICAL_STAFF"
            ),
            ctx["doc_h_headers"],
        ),
        201,
    )
    validate_success(
        api.screen_evaluation(
            evaluation["id"],
            f.screen_payload(no_go_signs=[], symptom_score=5),
            ctx["doc_h_headers"],
        )
    )
    ctx["eval2_id"] = evaluation["id"]
    return ctx


# ─── The rest buffer is half-open: the boundary instant is legal ──────────────

def test_a_stage_start_one_second_before_the_rest_buffer_is_refused(api):
    """
    Stage two is refused a single second before its rest buffer elapses, and the
    refusal leaves no step behind.

    PRD §3.6: "Concretely, `min_start_at` is the `evaluated_at` of the case's
    passed step for the immediately preceding stage plus that buffer, and a request
    to open the stage before `min_start_at` is refused with
    `ERR_STAGE_REST_BUFFER_VIOLATION` while a request at exactly `min_start_at`
    succeeds."

    Design: Difficulty/resource_temporal_overlap/stage_rest_buffer_half_open_admits_exact_boundary_start
    """
    # Stage one passed at 2026-09-16T12:00:00Z, so stage two opens from
    # 2026-09-17T12:00:00Z.
    ctx = fx.setup_case_through_stage(api, 1)
    fx.set_clock(api, "2026-09-17T11:59:59Z")

    validate_error(
        api.create_return_step(
            ctx["case_id"], f.return_step_payload(stage_index=2), ctx["doc_h_headers"]
        ),
        ERR_STAGE_REST_BUFFER_VIOLATION,
        409,
    )

    steps, meta = validate_paginated(api.list_return_steps(ADMIN, case_id=ctx["case_id"]))
    assert_page_meta(meta, total_count=1)
    assert [step["stage_index"] for step in steps] == [1]


def test_a_stage_start_at_exactly_the_rest_buffer_is_accepted(api):
    """
    One second later — exactly on the boundary — the identical request succeeds
    and the new step carries the boundary instant as its own opening figure.

    PRD §2.11: "A stage may not start before its `min_start_at`, but starting at
    exactly `min_start_at` is accepted — the forbidden window runs from the previous
    stage's sign-off instant up to, but not including, `min_start_at`."

    Design: Difficulty/resource_temporal_overlap/stage_rest_buffer_half_open_admits_exact_boundary_start
    """
    ctx = fx.setup_case_through_stage(api, 1)
    fx.set_clock(api, "2026-09-17T11:59:59Z")
    api.create_return_step(
        ctx["case_id"], f.return_step_payload(stage_index=2), ctx["doc_h_headers"]
    )

    fx.set_clock(api, "2026-09-17T12:00:00Z")
    step = validate_success(
        api.create_return_step(
            ctx["case_id"], f.return_step_payload(stage_index=2), ctx["doc_h_headers"]
        ),
        201,
    )

    assert_return_step(step, stage_index=2, status="IN_PROGRESS")
    assert_instant(step["started_at"], "2026-09-17T12:00:00.000Z")
    assert_instant(step["min_start_at"], "2026-09-17T12:00:00.000Z")
    assert_instant(step["dwell_complete_at"], "2026-09-18T12:00:00.000Z")


# ─── The examination block is closed: the boundary instant collides ───────────

def test_a_second_examination_touching_the_first_block_is_refused(api):
    """
    The attending clinician's block is closed at both ends, so a second
    examination requested at the instant the first block ends collides with it.

    PRD §3.4: "If the requested block shares even a single instant with any of
    those, the request is refused with `ERR_INC_EXAM_WINDOW_CONFLICT` — touching
    endpoints do collide, so a request made at exactly the instant an earlier block
    ends is refused while one made a second later succeeds."

    Design: Difficulty/resource_temporal_overlap/consultant_exam_block_closed_interval_rejects_touching_start
    """
    ctx = _setup_second_screened_evaluation(api)
    assert_instant(
        fx.read_evaluation(api, ctx["eval_id"])["inc_block_ends_at"], fx.EXAM_BLOCK_ENDS_AT
    )

    fx.set_clock(api, "2026-09-13T18:40:00Z")
    validate_error(
        api.start_locker_room_exam(
            ctx["eval2_id"], f.locker_room_exam_payload(ctx["obs_id"]), ctx["doc_h_headers"]
        ),
        ERR_INC_EXAM_WINDOW_CONFLICT,
        409,
    )

    evaluation = fx.read_evaluation(api, ctx["eval2_id"])
    assert evaluation["status"] == "SCREENED"
    assert evaluation["inc_clinician_id"] is None


def test_a_second_examination_one_second_clear_of_the_block_is_accepted(api):
    """
    A second later the same nomination is admitted and opens its own thirty-minute
    block from the instant it started.

    PRD §3.4: "The server stamps `exam_started_at` from the logical clock and
    derives `inc_block_ends_at` at exactly 30 minutes later, then increments the
    evaluation's `version` by 1."

    Design: Difficulty/resource_temporal_overlap/consultant_exam_block_closed_interval_rejects_touching_start
    """
    ctx = _setup_second_screened_evaluation(api)

    fx.set_clock(api, "2026-09-13T18:40:00Z")
    api.start_locker_room_exam(
        ctx["eval2_id"], f.locker_room_exam_payload(ctx["obs_id"]), ctx["doc_h_headers"]
    )

    fx.set_clock(api, "2026-09-13T18:40:01Z")
    evaluation = validate_success(
        api.start_locker_room_exam(
            ctx["eval2_id"], f.locker_room_exam_payload(ctx["obs_id"]), ctx["doc_h_headers"]
        )
    )

    assert evaluation["status"] == "LOCKER_ROOM_EXAM"
    assert evaluation["inc_clinician_id"] == ctx["obs_id"]
    assert_instant(evaluation["exam_started_at"], "2026-09-13T18:40:01.000Z")
    assert_instant(evaluation["inc_block_ends_at"], "2026-09-13T19:10:01.000Z")
