"""
Boundaries that decide an outcome: the symptom score that separates a pass from a
recurrence, and the collection size that separates "no ladder at all" from "an
unfinished ladder".
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_NO_RETURN_STEPS_RECORDED,
    ERR_RTP_STAGES_INCOMPLETE,
    ERR_SYMPTOM_OUTCOME_MISMATCH,
)
from test_helpers.assertions import assert_case_progress, assert_page_meta, assert_return_step
from test_helpers.test_users import ADMIN


# ─── The recurrence threshold sits on the recurrence side ────────────────────

def test_both_sides_of_the_recurrence_threshold_are_refused_when_mislabelled(api):
    """
    A score of 4 cannot be declared a pass and a score of 3 cannot be declared a
    recurrence; the threshold belongs to the recurrence side.

    PRD §3.6: "A symptom score of 4 or more is a **recurrence**; 3 or less is not.
    The two are not interchangeable: declaring `PASS` with a score of 4 or more, or
    declaring `SYMPTOM_RECURRENCE` with a score of 3 or less, is refused with
    `ERR_SYMPTOM_OUTCOME_MISMATCH`."

    Design: Difficulty/boundary_precision_check/stage_pass_symptom_score_at_recurrence_threshold_boundary
    """
    # Stage one open since 2026-09-15T12:00:00Z; the clock sits exactly on the
    # dwell boundary so timing cannot mask the score check.
    ctx = fx.setup_case_with_stage_open(api, 1)
    fx.set_clock(api, "2026-09-16T12:00:00Z")
    step_id = ctx["step_ids"][1]

    validate_error(
        api.evaluate_return_step(
            step_id,
            f.evaluate_step_payload(outcome="PASS", symptom_score=4),
            ctx["doc_h_headers"],
        ),
        ERR_SYMPTOM_OUTCOME_MISMATCH,
        422,
    )
    validate_error(
        api.evaluate_return_step(
            step_id,
            f.evaluate_step_payload(outcome="SYMPTOM_RECURRENCE", symptom_score=3),
            ctx["doc_h_headers"],
        ),
        ERR_SYMPTOM_OUTCOME_MISMATCH,
        422,
    )

    assert_return_step(fx.read_step(api, step_id), stage_index=1, status="IN_PROGRESS")
    assert_case_progress(fx.read_case(api, ctx["case_id"]), rtp_stage=0, recurrence_count=0)


def test_a_score_of_three_passes_the_stage_and_records_no_recurrence(api):
    """
    The highest non-recurrence score passes the rung and records itself on the
    step.

    PRD §3.6: "A `PASS` moves the step `IN_PROGRESS → PASSED`, stamps
    `evaluated_at` from the logical clock and `cleared_by_clinician_id` from the
    acting physician, and sets the case's `rtp_stage` to that step's
    `stage_index`."

    Design: Difficulty/boundary_precision_check/stage_pass_symptom_score_at_recurrence_threshold_boundary
    """
    ctx = fx.setup_case_with_stage_open(api, 1)
    fx.set_clock(api, "2026-09-16T12:00:00Z")

    step = validate_success(
        api.evaluate_return_step(
            ctx["step_ids"][1],
            f.evaluate_step_payload(outcome="PASS", symptom_score=3),
            ctx["doc_h_headers"],
        )
    )
    assert step["status"] == "PASSED"
    assert step["evaluation_symptom_score"] == 3
    assert step["cleared_by_clinician_id"] == ctx["doc_h_id"]

    assert_case_progress(fx.read_case(api, ctx["case_id"]), rtp_stage=1, recurrence_count=0)


# ─── Zero steps is a different refusal from an unfinished ladder ─────────────

def test_a_case_with_no_steps_at_all_reports_the_empty_collection(api):
    """
    A final-clearance request against a case that never opened a rung reports the
    empty-collection refusal, not the incomplete-ladder one.

    PRD §3.7: "The case must have at least one return step — a case with none is
    refused with `ERR_NO_RETURN_STEPS_RECORDED` — and every stage from 1 through 5
    must have a `PASSED`, non-`REVOKED` step, else the request is refused with
    `ERR_RTP_STAGES_INCOMPLETE`."

    Design: Difficulty/boundary_precision_check/inc_clearance_request_empty_versus_partial_step_collection
    """
    ctx = fx.setup_diagnosed_case(api)
    version = fx.case_version(api, ctx["case_id"])

    response = api.request_inc_clearance(
        ctx["case_id"],
        f.clearance_request_payload(ctx["inc_id"], version),
        ctx["doc_h_headers"],
    )
    error = validate_error(response, ERR_NO_RETURN_STEPS_RECORDED, 422)
    assert error["error_id"] != ERR_RTP_STAGES_INCOMPLETE

    clearances, meta = validate_paginated(api.list_inc_clearances(ADMIN, case_id=ctx["case_id"]))
    assert_page_meta(meta, total_count=0)
    assert clearances == []


def test_one_passed_stage_reports_the_incomplete_ladder_instead(api):
    """
    Once a single rung is passed the same request switches to the
    incomplete-ladder refusal, and still creates no clearance.

    PRD §2.5 rung 35: "`ERR_RTP_STAGES_INCOMPLETE` (422) — requesting final
    clearance, or approving one, when any stage from 1 to 5 lacks a `PASSED`,
    non-`REVOKED` step."

    Design: Difficulty/boundary_precision_check/inc_clearance_request_empty_versus_partial_step_collection
    """
    ctx = fx.setup_case_through_stage(api, 1)
    # The stage pass advanced the case's version, so re-read the concurrency token.
    version = fx.case_version(api, ctx["case_id"])

    response = api.request_inc_clearance(
        ctx["case_id"],
        f.clearance_request_payload(ctx["inc_id"], version),
        ctx["doc_h_headers"],
    )
    validate_error(response, ERR_RTP_STAGES_INCOMPLETE, 422)

    clearances, meta = validate_paginated(api.list_inc_clearances(ADMIN, case_id=ctx["case_id"]))
    assert_page_meta(meta, total_count=0)
    assert clearances == []

    case = fx.read_case(api, ctx["case_id"])
    assert case["case_status"] == "RTP_IN_PROGRESS"
    assert case["rtp_stage"] == 1
