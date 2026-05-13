"""CandidateRegistration creation, ExamAttempt creation, and
begin-identity-check.

Covers the ENROLLED → IDENTITY_PENDING transition with its Exam.status
== IN_SESSION precondition.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    assert_attempt,
    assert_registration,
    attempt_enrolled_only,
    close_registration,
    create_attempt_payload,
    create_registration_payload,
    exam_ready_for_candidates,
    make_candidate_headers,
    open_registration,
    register_candidate,
    unique_candidate_id,
    validate_error,
    validate_success,
)


# ===========================================================================
# Registration
# ===========================================================================
def test_registration_starts_in_registered(api, exam_admin_headers):
    """PRD §3.1: "the administrator submits a candidate's candidate_id
    and id_card_number against the exam, producing a CandidateRegistration
    in status REGISTERED."
    """
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    cid = unique_candidate_id()
    res = api.create_registration(
        exam["id"],
        create_registration_payload(candidate_id=cid),
        exam_admin_headers,
    )
    reg = validate_success(res, 201)
    assert_registration(reg)
    assert reg["status"] == "REGISTERED"
    assert reg["candidate_id"] == cid


# ===========================================================================
# Attempt creation — ownership + IN_SESSION precondition
# ===========================================================================
def test_create_attempt_requires_exam_in_session(api):
    """PRD §3.2: "When the server clock reaches the exam's start_time,
    the exam transitions automatically READY → IN_SESSION, and only
    then may a Candidate open an attempt."

    Claim: attempt creation BEFORE start_time → ERR_EXAM_NOT_IN_SESSION.
    """
    exam, _, _ = exam_ready_for_candidates(
        start_time=10_000, end_time=20_000, num_objective=1,
    )
    cid = unique_candidate_id()
    reg = register_candidate(exam["id"], candidate_id=cid)
    close_registration(exam["id"])
    # Do NOT advance clock — exam is still READY, not IN_SESSION.
    res = api.create_attempt(
        exam["id"],
        create_attempt_payload(reg["id"]),
        make_candidate_headers(cid),
    )
    validate_error(res, "ERR_EXAM_NOT_IN_SESSION")


def test_create_attempt_succeeds_in_session(api):
    """PRD §3.2: "and only then may a Candidate open an attempt ...
    the server mirrors the registration's candidate_id onto the attempt
    as a computed field and creates the row in status ENROLLED."
    """
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    cid = unique_candidate_id()
    reg = register_candidate(exam["id"], candidate_id=cid)
    close_registration(exam["id"])
    advance_clock(exam["start_time"])
    res = api.create_attempt(
        exam["id"],
        create_attempt_payload(reg["id"]),
        make_candidate_headers(cid),
    )
    attempt = validate_success(res, 201)
    assert_attempt(attempt)
    assert attempt["status"] == "ENROLLED"
    assert attempt["registration_id"] == reg["id"]
    assert attempt["candidate_id"] == cid


def test_one_attempt_per_registration_enforced(api):
    """PRD §3.2: "Exactly one attempt is allowed per registration."
    """
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    reg, attempt, cid = attempt_enrolled_only(exam)
    res = api.create_attempt(
        exam["id"],
        create_attempt_payload(reg["id"]),
        make_candidate_headers(cid),
    )
    validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# begin-identity-check
# ===========================================================================
def test_begin_identity_check_transitions_to_identity_pending(api):
    """PRD §3.2: "The candidate next initiates identity verification: a
    transition ENROLLED → IDENTITY_PENDING that requires the exam to be
    IN_SESSION (otherwise ERR_EXAM_NOT_IN_SESSION) and has no other
    preconditions or side effects."
    """
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    reg, attempt, cid = attempt_enrolled_only(exam)
    res = api.begin_identity_check(
        exam["id"], attempt["id"], make_candidate_headers(cid),
    )
    updated = validate_success(res, 200)
    assert updated["status"] == "IDENTITY_PENDING"


def test_begin_identity_check_requires_exam_in_session(api):
    """PRD §3.2: "The candidate next initiates identity verification: a
    transition ENROLLED → IDENTITY_PENDING that requires the exam to be
    IN_SESSION (otherwise ERR_EXAM_NOT_IN_SESSION) and has no other
    preconditions or side effects."

    Difficulty design: cross_entity_state_dependency /
    exam_attempt_start_requires_exam_in_session.

    Setup: create the attempt while IN_SESSION (necessary), then advance
    the clock past end_time so the exam leaves IN_SESSION; the
    begin-identity-check call then fails its exam-state precondition.
    """
    # difficulty: cross_entity_state_dependency/exam_attempt_start_requires_exam_in_session
    exam, _, _ = exam_ready_for_candidates(
        start_time=5_000, end_time=6_000, num_objective=1,
    )
    cid = unique_candidate_id()
    reg = register_candidate(exam["id"], candidate_id=cid)
    close_registration(exam["id"])
    # Advance to IN_SESSION so we can create the attempt at all.
    advance_clock(exam["start_time"])
    cand_headers = make_candidate_headers(cid)
    attempt = validate_success(
        api.create_attempt(
            exam["id"], create_attempt_payload(reg["id"]), cand_headers,
        ), 201,
    )
    # Force exam → GRADING by advancing past end_time. The attempt is
    # ENROLLED, so the §2.7 forced_submit override does not apply (the
    # override targets ACTIVE/SUSPENDED only); the §3.2 IN_SESSION
    # precondition for begin-identity-check is the one that fires.
    advance_clock(exam["end_time"])
    res = api.begin_identity_check(exam["id"], attempt["id"], cand_headers)
    validate_error(res, "ERR_EXAM_NOT_IN_SESSION")


def test_create_attempt_with_unknown_registration(api):
    """PRD §2.7: existence precedes business-state. Unknown registration_id
    on a valid attempt-creation path → registration not found.
    """
    from test_helpers import NON_EXISTENT_UUID
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    close_registration(exam["id"])
    advance_clock(exam["start_time"])
    cand_headers = make_candidate_headers("some-candidate")
    res = api.create_attempt(
        exam["id"],
        create_attempt_payload(NON_EXISTENT_UUID),
        cand_headers,
    )
    # Implementations may surface either ERR_REGISTRATION_NOT_FOUND
    # (lookup failure) or ERR_INSUFFICIENT_PERMISSIONS (ownership
    # traversal). PRD §3.2 + §2.1 are not precise about precedence
    # here; either is faithful.
    from test_helpers import validate_error_is_one_of
    validate_error_is_one_of(
        res,
        ["ERR_REGISTRATION_NOT_FOUND", "ERR_INSUFFICIENT_PERMISSIONS"],
    )
