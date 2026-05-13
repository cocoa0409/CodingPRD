"""Identity verification: PRE_EXAM PASS/MISMATCH, IN_EXAM_RECHECK,
and the identity_verification_count invariant.

Covers PRD §3.2 (PRE_EXAM gating ACTIVE) and §3.4 (IN_EXAM_RECHECK
triggered by CRITICAL forced_recheck events).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    advance_clock,
    api_client,
    assert_attempt,
    assert_attempt_invariants,
    assert_identity_record,
    attempt_active,
    attempt_enrolled_only,
    exam_ready_for_candidates,
    identity_verification_payload,
    make_candidate_headers,
    post_abnormal_event,
    validate_error,
    validate_success,
)


def _begin_then_verify(api, exam, factors):
    """Drive attempt to IDENTITY_PENDING then submit PRE_EXAM with the
    given factors."""
    reg, attempt, cid = attempt_enrolled_only(exam)
    cand_headers = make_candidate_headers(cid)
    validate_success(
        api.begin_identity_check(exam["id"], attempt["id"], cand_headers),
        200,
    )
    res = api.submit_identity_verification(
        exam["id"], attempt["id"],
        identity_verification_payload(
            verification_phase="PRE_EXAM",
            id_card=factors["id_card"],
            face=factors["face"],
            live_detection=factors["live_detection"],
        ),
        cand_headers,
    )
    return reg, attempt, cid, cand_headers, res


# ===========================================================================
# PRE_EXAM PASS — transitions to ACTIVE, increments count, composes paper
# ===========================================================================
def test_pre_exam_pass_transitions_to_active(api):
    """PRD §3.2: "A PASS outcome transitions the attempt
    IDENTITY_PENDING → ACTIVE, stamps started_at from the server clock,
    runs the paper composition described in §3.3, and increments
    identity_verification_count by 1."
    """
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    reg, attempt, cid, cand_headers, res = _begin_then_verify(
        api, exam,
        {"id_card": True, "face": True, "live_detection": True},
    )
    record = validate_success(res, 201)
    assert_identity_record(record)
    assert record["outcome"] == "PASS"
    assert record["verification_phase"] == "PRE_EXAM"

    # Fetch the attempt and verify state + count.
    refreshed = validate_success(
        api.get_attempt(exam["id"], attempt["id"], cand_headers), 200,
    )
    assert_attempt(refreshed)
    assert refreshed["status"] == "ACTIVE"
    assert refreshed["identity_verification_count"] == 1
    assert refreshed["started_at"] is not None
    # PRD §3.3: paper_question_ids is computed at this moment.
    assert isinstance(refreshed["paper_question_ids"], list)
    assert len(refreshed["paper_question_ids"]) >= 1
    assert refreshed["paper_version_hash"] is not None


# ===========================================================================
# PRE_EXAM MISMATCH — cascades to DISQUALIFIED
# ===========================================================================
@pytest.mark.parametrize("failing_factor", ["id_card", "face", "live_detection"])
def test_pre_exam_mismatch_disqualifies(api, failing_factor):
    """PRD §3.2: "A MISMATCH outcome instead transitions the attempt
    IDENTITY_PENDING → DISQUALIFIED, cascades the registration to
    DISQUALIFIED, appends an AuditLogEntry with action_code
    IDENTITY_MISMATCH, and likewise increments
    identity_verification_count."
    """
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    factors = {"id_card": True, "face": True, "live_detection": True}
    factors[failing_factor] = False
    reg, attempt, cid, cand_headers, res = _begin_then_verify(
        api, exam, factors,
    )
    # Implementations may signal the MISMATCH via the response body
    # (HTTP 201 with record.outcome == 'MISMATCH') OR by returning
    # ERR_IDENTITY_MISMATCH (HTTP 422). PRD §3.2 + §5 leave the
    # response-code choice open, but the side effects (DISQUALIFIED
    # cascade + count increment + audit row) MUST hold either way.
    assert res.status_code in (201, 422)
    refreshed = validate_success(
        api.get_attempt(exam["id"], attempt["id"], cand_headers), 200,
    )
    assert refreshed["status"] == "DISQUALIFIED"
    assert refreshed["identity_verification_count"] == 1
    assert_attempt_invariants(refreshed)


def test_pre_exam_outcome_is_pass_only_when_all_three_factors_true(api):
    """PRD §3.2: "The record's outcome is computed: it is PASS when all
    three factors are true, and MISMATCH if any factor is false."

    Sanity check: even with two factors true, the outcome must be
    MISMATCH.
    """
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    reg, attempt, cid, cand_headers, res = _begin_then_verify(
        api, exam,
        {"id_card": True, "face": False, "live_detection": True},
    )
    refreshed = validate_success(
        api.get_attempt(exam["id"], attempt["id"], cand_headers), 200,
    )
    assert refreshed["status"] == "DISQUALIFIED"


# ===========================================================================
# IN_EXAM_RECHECK — requires a forced_recheck event
# ===========================================================================
def test_in_exam_recheck_without_pending_recheck_rejected(api):
    """PRD §3.4: "The transition is admitted only when at least one
    such event exists for the attempt with forced_recheck_emitted true
    and no later IdentityVerificationRecord already settles it;
    otherwise the call is rejected with ERR_NO_PENDING_RECHECK."
    """
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    reg, attempt, cid = attempt_active(exam)
    cand_headers = make_candidate_headers(cid)
    res = api.submit_identity_verification(
        exam["id"], attempt["id"],
        identity_verification_payload(
            verification_phase="IN_EXAM_RECHECK",
            triggered_by_event_id=NON_EXISTENT_UUID,
        ),
        cand_headers,
    )
    validate_error(res, "ERR_NO_PENDING_RECHECK")


# Silence-pattern note (branch-asymmetry): PRD §3.4 names FACE_LEAVE and
# MULTI_PERSON as the two forced-recheck-emitting rules, but a paper
# walk-through of PRD §3.4's severity formula shows FACE_LEAVE (base 30)
# multiplied by its richest channel (CAMERA/AUDIO 1.2) and REALTIME_ALERT
# (1.0) caps at severity_score 36 — below the 70 CRITICAL cutoff. The
# only rule in the forced-recheck set that can reach CRITICAL is
# MULTI_PERSON, which simultaneously fires the disqualification cascade
# (PRD §3.4 explicit clause: "MULTI_PERSON triggers both cascades
# simultaneously when it reaches CRITICAL"). PRD therefore leaves no
# documented path that reaches IN_EXAM_RECHECK PASS or MISMATCH against
# a still-ACTIVE attempt with an outstanding forced_recheck. Tests
# omitted under the branch-asymmetry silence pattern. The earlier test
# (test_in_exam_recheck_without_pending_recheck_rejected) exercises the
# only PRD-uniquely-derivable IN_EXAM_RECHECK rule.


# ===========================================================================
# identity_verification_count invariant (PRD §3.2)
# ===========================================================================
def test_identity_verification_count_matches_record_count_after_pre_exam(api):
    """PRD §3.2: "The aggregate identity_verification_count carried on
    the attempt is required to equal at every observation the number of
    IdentityVerificationRecord rows whose attempt_id is this attempt's
    id."
    """
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    reg, attempt, cid = attempt_active(exam)
    cand_headers = make_candidate_headers(cid)
    refreshed = validate_success(
        api.get_attempt(exam["id"], attempt["id"], cand_headers), 200,
    )
    # After exactly one PASS PRE_EXAM, count == 1.
    assert refreshed["identity_verification_count"] == 1


def test_identity_verification_count_increments_on_pre_exam_mismatch(api):
    """PRD §3.2: "A MISMATCH outcome ... likewise increments
    identity_verification_count." Plus invariant carry-through: count
    stays 1 even after cascade (cascade does NOT delete records).
    """
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    reg, attempt, cid, cand_headers, res = _begin_then_verify(
        api, exam,
        {"id_card": False, "face": True, "live_detection": True},
    )
    refreshed = validate_success(
        api.get_attempt(exam["id"], attempt["id"], cand_headers), 200,
    )
    assert refreshed["identity_verification_count"] == 1
    assert refreshed["status"] == "DISQUALIFIED"
