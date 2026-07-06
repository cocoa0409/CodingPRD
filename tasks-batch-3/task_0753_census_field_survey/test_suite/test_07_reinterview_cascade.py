"""Reinterview finalize branches, the case-reopen cycle, the depth-3 fraud
cascade, and the referential-vs-safety reinterview priority.

Translates queue-A non_linear_state_machine (both instances), transitive_cascade
(fraud leg), priority_pair_validation_conflict (reinterview leg); and queue-B SoD.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    create_reinterview_payload,
    setup_captured_response,
    setup_reinterview_in_review,
    finalize_reinterview,
)

ADMIN = TEST_USERS["survey_admin_headers"]
QC = TEST_USERS["qc_reviewer_headers"]


# ── non_linear_state_machine: reinterview_branch_confirmed_vs_fraud ───────────

def test_reinterview_confirmed_accepts_response_case_stays_complete(api):
    """PRD §3.8: "A `CONFIRMED` outcome is a benign confirmation: the reinterview
    moves to `CONFIRMED` and the audited response transitions from `CAPTURED` to
    `ACCEPTED`."

    Design: Difficulty/non_linear_state_machine/reinterview_branch_confirmed_vs_fraud
    """
    ctx = setup_reinterview_in_review()
    ri = finalize_reinterview(ctx["reinterview"]["id"], "CONFIRMED")
    assert ri["status"] == "CONFIRMED"

    resp = validate_success(api.get_response(ctx["response"]["id"], ADMIN), 200)
    assert resp["status"] == "ACCEPTED"
    case = validate_success(api.get_case(ctx["case"]["id"], ADMIN), 200)
    assert case["status"] == "COMPLETE"


def test_reinterview_discrepant_leaves_response_captured(api):
    """PRD §3.8: "A `DISCREPANT` outcome moves the reinterview to `DISCREPANT`,
    notes the discrepancy, and triggers no cascade — the response remains
    `CAPTURED`."

    Design: Difficulty/non_linear_state_machine/reinterview_branch_confirmed_vs_fraud
    """
    ctx = setup_reinterview_in_review()
    ri = finalize_reinterview(ctx["reinterview"]["id"], "DISCREPANT")
    assert ri["status"] == "DISCREPANT"

    resp = validate_success(api.get_response(ctx["response"]["id"], ADMIN), 200)
    assert resp["status"] == "CAPTURED"
    case = validate_success(api.get_case(ctx["case"]["id"], ADMIN), 200)
    assert case["status"] == "COMPLETE"


# ── non_linear_state_machine: case_reopen_cycle ───────────────────────────────

def test_fraud_finalize_reopens_case_and_invalidates_response(api):
    """PRD §3.8: "First, the audited response transitions from `CAPTURED` to
    `INVALIDATED`. Second, invalidating the response reopens its parent case from
    `COMPLETE` back to `IN_PROGRESS`".

    Design: Difficulty/non_linear_state_machine/case_reopen_cycle
    """
    ctx = setup_reinterview_in_review()
    finalize_reinterview(ctx["reinterview"]["id"], "FRAUD")

    case = validate_success(api.get_case(ctx["case"]["id"], ADMIN), 200)
    assert case["status"] == "IN_PROGRESS"
    resp = validate_success(api.get_response(ctx["response"]["id"], ADMIN), 200)
    assert resp["status"] == "INVALIDATED"


def test_case_traverses_complete_to_in_progress_cycle_edge(api):
    """PRD §3.8: "Second, invalidating the response reopens its parent case from
    `COMPLETE` back to `IN_PROGRESS`".

    The case is observed COMPLETE immediately before the FRAUD finalize and
    IN_PROGRESS immediately after, tracing the reopen cycle edge explicitly.

    Design: Difficulty/non_linear_state_machine/case_reopen_cycle
    """
    ctx = setup_reinterview_in_review()
    before = validate_success(api.get_case(ctx["case"]["id"], ADMIN), 200)
    assert before["status"] == "COMPLETE"

    finalize_reinterview(ctx["reinterview"]["id"], "FRAUD")
    after = validate_success(api.get_case(ctx["case"]["id"], ADMIN), 200)
    assert after["status"] == "IN_PROGRESS"


# ── transitive_cascade: fraud_cascade_depth3 ──────────────────────────────────

def test_fraud_cascade_reopens_case_reverts_area_and_flags_enumerator(api):
    """PRD §3.8: "A `FRAUD` outcome moves the reinterview to `FRAUD` and drives a
    cascade three links deep. First, the audited response transitions from
    `CAPTURED` to `INVALIDATED`. Second, invalidating the response reopens its
    parent case from `COMPLETE` back to `IN_PROGRESS`: the area's
    `complete_case_count` decrements by one, its `in_progress_case_count`
    increments by one, and coverage is recomputed. Third, if that area had bubbled
    up to `COMPLETE`, the reopened in-progress case reverts the area from
    `COMPLETE` back to `IN_FIELD`. Alongside this chain, the capturing enumerator's
    `fraud_flag` is set true."

    Design: Difficulty/transitive_cascade/fraud_cascade_depth3
    """
    ctx = setup_reinterview_in_review(reason="HIGH_FRAUD_SCORE")
    finalize_reinterview(ctx["reinterview"]["id"], "FRAUD")

    resp = validate_success(api.get_response(ctx["response"]["id"], ADMIN), 200)
    assert resp["status"] == "INVALIDATED"
    case = validate_success(api.get_case(ctx["case"]["id"], ADMIN), 200)
    assert case["status"] == "IN_PROGRESS"
    area = validate_success(api.get_area(ctx["area"]["id"], ADMIN), 200)
    assert area["complete_case_count"] == 0
    assert area["in_progress_case_count"] == 1
    assert area["status"] == "IN_FIELD"
    en1 = validate_success(api.get_enumerator(ctx["enumerator"]["id"], ADMIN), 200)
    assert en1["fraud_flag"] is True


def test_fraud_cascade_recomputes_area_coverage(api):
    """PRD §3.8: "Second, invalidating the response reopens its parent case from
    `COMPLETE` back to `IN_PROGRESS`: the area's `complete_case_count` decrements
    by one, its `in_progress_case_count` increments by one, and coverage is
    recomputed."

    After the reopen the sole case is IN_PROGRESS (not COMPLETE), so projected
    coverage = (0+1)/1 = 1.0 while final coverage = 0/1 = 0.0.

    Design: Difficulty/transitive_cascade/fraud_cascade_depth3
    """
    ctx = setup_reinterview_in_review(reason="HIGH_FRAUD_SCORE")
    finalize_reinterview(ctx["reinterview"]["id"], "FRAUD")

    area = validate_success(api.get_area(ctx["area"]["id"], ADMIN), 200)
    assert area["projected_coverage_rate"] == pytest.approx(1.0, abs=1e-6)
    assert area["final_coverage_rate"] == pytest.approx(0.0, abs=1e-6)


# ── priority_pair_validation_conflict: referential_beats_safety_on_reinterview ─

def test_reviewer_not_active_beats_segregation_of_duties(api):
    """PRD §2.11: "then the reviewer-active and segregation-of-duties checks for
    reinterviews (`ERR_REVIEWER_NOT_ACTIVE`, then `ERR_SEGREGATION_OF_DUTIES`)".

    A reviewer who is BOTH suspended AND equal to the response's capturing
    enumerator surfaces the higher-priority ERR_REVIEWER_NOT_ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_safety_on_reinterview
    """
    ctx = setup_captured_response()  # E1 active, captured the response
    validate_success(api.suspend_enumerator(ctx["enumerator"]["id"], ADMIN), 200)
    res = api.create_reinterview(
        ctx["response"]["id"],
        create_reinterview_payload(reviewer_enumerator_id=ctx["enumerator"]["id"], reason="MANUAL"),
        QC)
    validate_error(res, "ERR_REVIEWER_NOT_ACTIVE", expected_status=422)


def test_segregation_of_duties_surfaces_when_reviewer_active(api):
    """PRD §2.11: "then the reviewer-active and segregation-of-duties checks for
    reinterviews (`ERR_REVIEWER_NOT_ACTIVE`, then `ERR_SEGREGATION_OF_DUTIES`)".

    When the reviewer equals the capturer but is still ACTIVE, the referential
    check passes and the lower-priority segregation-of-duties check fires.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_safety_on_reinterview
    """
    ctx = setup_captured_response()  # E1 active, captured the response
    res = api.create_reinterview(
        ctx["response"]["id"],
        create_reinterview_payload(reviewer_enumerator_id=ctx["enumerator"]["id"], reason="MANUAL"),
        QC)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=422)


# ── queue-B: segregation of duties (isolated) ─────────────────────────────────

def test_reinterview_reviewer_equals_capturer_returns_sod(api):
    """PRD §3.8: "And, enforcing segregation of duties, the `reviewer_enumerator_id`
    must differ from the response's `capturing_enumerator_id` — a reviewer may
    never audit their own captured response — or the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/reinterview_reviewer_equals_capturer_returns_sod
    """
    ctx = setup_captured_response()
    res = api.create_reinterview(
        ctx["response"]["id"],
        create_reinterview_payload(reviewer_enumerator_id=ctx["enumerator"]["id"], reason="MANUAL"),
        QC)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=422)
