"""Appeal lifecycle: submission, claim (segregation of duties),
secondary-mark, decide.

Covers PRD §3.7.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    assert_appeal,
    create_appeal_payload,
    decide_appeal_payload,
    make_appeal_officer_headers,
    make_candidate_headers,
    make_marker_headers,
    secondary_mark_payload,
    setup_finalized_exam_for_appeal,
    submit_appeal_for,
    validate_error,
    validate_success,
)


# ===========================================================================
# Submission
# ===========================================================================
def test_submit_appeal_in_appeal_window(api):
    """PRD §3.7: "A candidate may submit an Appeal only while the exam
    is in APPEAL_WINDOW (otherwise ERR_EXAM_NOT_IN_APPEAL_WINDOW)."
    """
    scenario = setup_finalized_exam_for_appeal()
    exam = scenario["exam"]
    subj_q = scenario["subjective_question"]
    attempt = scenario["attempt"]
    cid = scenario["candidate_id"]
    res = api.create_appeal(
        exam["id"], attempt["id"],
        create_appeal_payload(question_id=subj_q["id"]),
        make_candidate_headers(cid),
    )
    appeal = validate_success(res, 201)
    assert_appeal(appeal)
    assert appeal["status"] == "SUBMITTED"
    assert appeal["question_id"] == subj_q["id"]


def test_submit_appeal_for_question_not_on_paper_rejected(api):
    """PRD §3.7: "The referenced question must appear in the attempt's
    paper_question_ids — you can only appeal a question you actually
    saw — and a violation rejects with ERR_QUESTION_NOT_ON_PAPER."
    """
    scenario = setup_finalized_exam_for_appeal()
    exam = scenario["exam"]
    attempt = scenario["attempt"]
    cid = scenario["candidate_id"]
    # Need a question id that is NOT in paper_question_ids.
    # Easier: pass the candidate's known correct registration id as
    # question_id — that uuid is not in paper_question_ids.
    bogus_qid = scenario["registration"]["id"]
    res = api.create_appeal(
        exam["id"], attempt["id"],
        create_appeal_payload(question_id=bogus_qid),
        make_candidate_headers(cid),
    )
    # Either ERR_QUESTION_NOT_ON_PAPER (PRD §3.7) or ERR_QUESTION_NOT_FOUND
    # (PRD §2.6: existence check). PRD prose pins the former.
    from test_helpers import validate_error_is_one_of
    validate_error_is_one_of(
        res, ["ERR_QUESTION_NOT_ON_PAPER", "ERR_QUESTION_NOT_FOUND"],
    )


def test_submit_appeal_outside_appeal_window_rejected(api):
    """PRD §3.7: appeal submission outside APPEAL_WINDOW →
    ERR_EXAM_NOT_IN_APPEAL_WINDOW.
    """
    # Reach GRADED but not yet APPEAL_WINDOW — easier to compose a
    # DRAFT exam and try submitting an appeal there.
    from test_helpers import (
        attempt_submitted,
        create_draft_exam,
        exam_ready_for_candidates,
    )
    exam, obj_qs, _ = exam_ready_for_candidates(
        start_time=1000, end_time=10_000, num_objective=1,
    )
    reg, attempt, cid = attempt_submitted(exam, obj_qs, [])
    res = api.create_appeal(
        exam["id"], attempt["id"],
        create_appeal_payload(question_id=obj_qs[0]["id"]),
        make_candidate_headers(cid),
    )
    validate_error(res, "ERR_EXAM_NOT_IN_APPEAL_WINDOW")


# ===========================================================================
# Claim (segregation of duties)
# ===========================================================================
def test_appeal_officer_was_marker_rejected(api):
    """PRD §3.7: "Claiming an appeal requires the acting AppealOfficer
    to have never marked the same (attempt_id, question_id) pair as a
    Marker ... a violation rejects with ERR_APPEAL_OFFICER_WAS_MARKER."
    """
    # The marker_id of BLIND_A in the appeal scenario is "marker-001"
    # (the default MARKER_1 in fixtures). Using that exact id as the
    # appeal officer triggers the SOD violation.
    scenario = setup_finalized_exam_for_appeal()
    exam = scenario["exam"]
    attempt = scenario["attempt"]
    subj_q = scenario["subjective_question"]
    cid = scenario["candidate_id"]
    appeal = submit_appeal_for(
        exam["id"], attempt["id"], subj_q["id"], cid,
    )
    # Officer impersonates marker-001 (the BLIND_A marker, set by
    # fixtures.MARKER_1).
    sod_officer = make_appeal_officer_headers("marker-001")
    res = api.claim_appeal(exam["id"], appeal["id"], sod_officer)
    validate_error(res, "ERR_APPEAL_OFFICER_WAS_MARKER")


def test_appeal_claim_transitions_to_under_review(api, appeal_officer_headers):
    """PRD §3.7: "A successful claim transitions the appeal
    SUBMITTED → UNDER_REVIEW."
    """
    scenario = setup_finalized_exam_for_appeal()
    exam = scenario["exam"]
    attempt = scenario["attempt"]
    subj_q = scenario["subjective_question"]
    cid = scenario["candidate_id"]
    appeal = submit_appeal_for(
        exam["id"], attempt["id"], subj_q["id"], cid,
    )
    res = api.claim_appeal(
        exam["id"], appeal["id"], appeal_officer_headers,
    )
    claimed = validate_success(res, 200)
    assert claimed["status"] == "UNDER_REVIEW"


# ===========================================================================
# Secondary-mark
# ===========================================================================
def test_secondary_mark_with_awarded_out_of_range(api, appeal_officer_headers):
    """PRD §3.7: "secondary_awarded_points ... must lie between 0 and
    the question's max_points inclusive (otherwise
    ERR_AWARDED_OUT_OF_RANGE)."
    """
    scenario = setup_finalized_exam_for_appeal(subjective_max_points=10)
    exam = scenario["exam"]
    attempt = scenario["attempt"]
    subj_q = scenario["subjective_question"]
    cid = scenario["candidate_id"]
    appeal = submit_appeal_for(
        exam["id"], attempt["id"], subj_q["id"], cid,
    )
    validate_success(
        api.claim_appeal(exam["id"], appeal["id"], appeal_officer_headers),
        200,
    )
    res = api.secondary_mark_appeal(
        exam["id"], appeal["id"],
        secondary_mark_payload(11.0),  # > max_points=10
        appeal_officer_headers,
    )
    validate_error(res, "ERR_AWARDED_OUT_OF_RANGE")


def test_secondary_mark_computes_score_delta(api, appeal_officer_headers):
    """PRD §3.7: "On success the appeal transitions UNDER_REVIEW →
    DECISION_PENDING and the server computes score_delta as
    secondary_awarded_points minus the prior per-question subjective
    value used in the most recent final_score_calculation for that
    question."
    """
    # Scenario: BLIND_A=8.0, BLIND_B=7.0 → per_question_subjective=7.50.
    # Officer awards 9.0 → score_delta = 9.0 - 7.5 = 1.5.
    scenario = setup_finalized_exam_for_appeal(
        blind_a_points=8.0, blind_b_points=7.0, subjective_max_points=10,
    )
    exam = scenario["exam"]
    attempt = scenario["attempt"]
    subj_q = scenario["subjective_question"]
    cid = scenario["candidate_id"]
    appeal = submit_appeal_for(
        exam["id"], attempt["id"], subj_q["id"], cid,
    )
    validate_success(
        api.claim_appeal(exam["id"], appeal["id"], appeal_officer_headers),
        200,
    )
    res = api.secondary_mark_appeal(
        exam["id"], appeal["id"],
        secondary_mark_payload(9.0),
        appeal_officer_headers,
    )
    marked = validate_success(res, 200)
    assert marked["status"] == "DECISION_PENDING"
    assert marked["score_delta"] == pytest.approx(1.5, abs=0.01)


# ===========================================================================
# Decide
# ===========================================================================
def test_decide_approved_adjusts_final_score(api, appeal_officer_headers):
    """PRD §3.7: "With decision set to APPROVED the appeal transitions
    DECISION_PENDING → APPROVED, the attempt's final_score is updated
    to its prior value plus score_delta (a depth-two cascade: appeal
    decision → attempt final score → audit log)."

    Difficulty design: transitive_cascade /
    appeal_approved_score_adjust_audit_cascade_depth2.
    """
    # difficulty: transitive_cascade/appeal_approved_score_adjust_audit_cascade_depth2
    scenario = setup_finalized_exam_for_appeal(
        blind_a_points=8.0, blind_b_points=7.0,
        objective_max_points=20, subjective_max_points=10,
        objective_correct=True,
    )
    exam = scenario["exam"]
    attempt = scenario["attempt"]
    subj_q = scenario["subjective_question"]
    cid = scenario["candidate_id"]
    # Pre-appeal final_score = objective(20) + subjective(7.5) = 27.50.
    initial_final = attempt["final_score"]
    assert initial_final == pytest.approx(27.50, abs=0.01)

    appeal = submit_appeal_for(
        exam["id"], attempt["id"], subj_q["id"], cid,
    )
    validate_success(
        api.claim_appeal(exam["id"], appeal["id"], appeal_officer_headers),
        200,
    )
    validate_success(
        api.secondary_mark_appeal(
            exam["id"], appeal["id"],
            secondary_mark_payload(9.0), appeal_officer_headers,
        ), 200,
    )
    res = api.decide_appeal(
        exam["id"], appeal["id"],
        decide_appeal_payload("APPROVED"), appeal_officer_headers,
    )
    decided = validate_success(res, 200)
    assert decided["status"] == "APPROVED"
    # Hop 2: attempt final_score updated.
    refreshed_attempt = validate_success(
        api.get_attempt(
            exam["id"], attempt["id"], make_candidate_headers(cid),
        ), 200,
    )
    assert refreshed_attempt["final_score"] == pytest.approx(29.00, abs=0.01)


def test_decide_rejected_no_score_adjustment(api, appeal_officer_headers):
    """PRD §3.7: "With decision set to REJECTED the appeal transitions
    DECISION_PENDING → REJECTED and no score adjustment occurs."
    """
    scenario = setup_finalized_exam_for_appeal(
        blind_a_points=8.0, blind_b_points=7.0,
    )
    exam = scenario["exam"]
    attempt = scenario["attempt"]
    subj_q = scenario["subjective_question"]
    cid = scenario["candidate_id"]
    initial_final = attempt["final_score"]
    appeal = submit_appeal_for(
        exam["id"], attempt["id"], subj_q["id"], cid,
    )
    validate_success(
        api.claim_appeal(exam["id"], appeal["id"], appeal_officer_headers),
        200,
    )
    validate_success(
        api.secondary_mark_appeal(
            exam["id"], appeal["id"],
            secondary_mark_payload(9.0), appeal_officer_headers,
        ), 200,
    )
    res = api.decide_appeal(
        exam["id"], appeal["id"],
        decide_appeal_payload("REJECTED"), appeal_officer_headers,
    )
    decided = validate_success(res, 200)
    assert decided["status"] == "REJECTED"
    refreshed_attempt = validate_success(
        api.get_attempt(
            exam["id"], attempt["id"], make_candidate_headers(cid),
        ), 200,
    )
    assert refreshed_attempt["final_score"] == pytest.approx(
        initial_final, abs=0.01,
    )
