"""Peer-to-peer review scheduling, completion, and cancellation.

PRD §3.5 (scheduling, time conflict, capacity, outcomes,
cascades).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    cancel_peer_to_peer,
    complete_peer_to_peer,
    complete_peer_to_peer_payload,
    iso_offset,
    make_provider_headers,
    re_get_authorization,
    re_get_peer_to_peer,
    schedule_peer_to_peer,
    schedule_peer_to_peer_payload,
    setup_authorization_in_peer_review,
    setup_authorization_with_two_p2p_calls_for_same_payer_reviewer,
    setup_completed_p2p_on_authorization,
    setup_under_review_authorization,
    validate_error,
    validate_success,
)


# ===========================================================================
# Schedule
# ===========================================================================
class TestSchedulePeerToPeer:
    """PRD §3.5: scheduling P2P."""

    def test_schedule_transitions_to_peer_review(self, api):
        """PRD §3.5: "Scheduling is permitted only from UNDER_REVIEW; on
        success, the parent authorization advances from UNDER_REVIEW to
        PEER_REVIEW and a PeerToPeerReview row is created with status
        SCHEDULED and outcome PENDING."

        Claim: scheduling a P2P transitions parent to PEER_REVIEW and
        creates a P2P with status=SCHEDULED, outcome=PENDING.
        """
        _, _, _, auth, p2p = setup_authorization_in_peer_review()
        assert auth["status"] == "PEER_REVIEW"
        assert p2p["status"] == "SCHEDULED"
        assert p2p["outcome"] == "PENDING"

    def test_at_most_one_p2p_per_authorization(self, api):
        """PRD §3.5: "At most one peer-to-peer review per authorization
        may exist in SCHEDULED or COMPLETED status; an attempt to
        schedule a second is rejected with
        ERR_PEER_REVIEW_ALREADY_SCHEDULED."

        Claim: after one COMPLETED P2P (cascades parent back to
        UNDER_REVIEW), scheduling a second P2P on the same
        authorization returns ERR_PEER_REVIEW_ALREADY_SCHEDULED.

        Difficulty: resource_temporal_overlap/peer_to_peer_per_authorization_aggregate_capacity_one
        """
        # difficulty: resource_temporal_overlap/peer_to_peer_per_authorization_aggregate_capacity_one
        _, provider, _, auth, _ = setup_completed_p2p_on_authorization()
        assert auth["status"] == "UNDER_REVIEW"
        res = api.schedule_peer_to_peer(
            auth["id"],
            schedule_peer_to_peer_payload(
                scheduled_at=iso_offset(hours=48),
                duration_minutes=30,
                payer_reviewer_id="payer-rev-X",
                version=auth["version"],
            ),
            make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_PEER_REVIEW_ALREADY_SCHEDULED")

    def test_time_conflict_overlapping_slot_rejected(self, api):
        """PRD §3.5: "the proposed scheduled_at must not overlap, within
        the half-open interval that starts at scheduled_at and ends at
        scheduled_at plus duration_minutes minutes (so the endpoint is
        exclusive), with any other SCHEDULED review whose
        payer_reviewer_id is the same; a conflict is rejected with
        ERR_PEER_REVIEW_TIME_CONFLICT."

        Claim: two P2Ps for the same payer_reviewer_id whose intervals
        overlap (10:00–10:30 and 10:29–10:59) → the second is rejected.

        Difficulty: resource_temporal_overlap/peer_to_peer_half_open_interval_overlap
        """
        # difficulty: resource_temporal_overlap/peer_to_peer_half_open_interval_overlap
        payer_id = "payer-overlap-test"
        first_slot = "2026-05-20T10:00:00.000Z"
        (_, (_, prov2, _, auth2)) = (
            setup_authorization_with_two_p2p_calls_for_same_payer_reviewer(
                payer_reviewer_id=payer_id,
                first_slot_iso=first_slot,
                first_duration_minutes=30,
            )
        )
        # Second slot starts 10:29, overlap with first's [10:00, 10:30).
        second_slot = "2026-05-20T10:29:00.000Z"
        res = api.schedule_peer_to_peer(
            auth2["id"],
            schedule_peer_to_peer_payload(
                scheduled_at=second_slot,
                duration_minutes=30,
                payer_reviewer_id=payer_id,
                version=auth2["version"],
            ),
            make_provider_headers(prov2["id"]),
        )
        validate_error(res, "ERR_PEER_REVIEW_TIME_CONFLICT")

    def test_time_boundary_touch_accepted(self, api):
        """PRD §3.5: "the half-open interval that starts at scheduled_at
        and ends at scheduled_at plus duration_minutes minutes (so the
        endpoint is exclusive)".

        Claim: a second P2P beginning at exactly the prior slot's
        end-time (10:30 after first slot [10:00,10:30)) succeeds.

        Difficulty: resource_temporal_overlap/peer_to_peer_half_open_interval_overlap
        """
        # difficulty: resource_temporal_overlap/peer_to_peer_half_open_interval_overlap
        payer_id = "payer-boundary-test"
        first_slot = "2026-05-20T10:00:00.000Z"
        (_, (_, prov2, _, auth2)) = (
            setup_authorization_with_two_p2p_calls_for_same_payer_reviewer(
                payer_reviewer_id=payer_id,
                first_slot_iso=first_slot,
                first_duration_minutes=30,
            )
        )
        # Second slot starts at exactly 10:30 — does NOT overlap.
        second_slot = "2026-05-20T10:30:00.000Z"
        res = api.schedule_peer_to_peer(
            auth2["id"],
            schedule_peer_to_peer_payload(
                scheduled_at=second_slot,
                duration_minutes=30,
                payer_reviewer_id=payer_id,
                version=auth2["version"],
            ),
            make_provider_headers(prov2["id"]),
        )
        p2p_b = validate_success(res, 201)
        assert p2p_b["status"] == "SCHEDULED"


# ===========================================================================
# Complete
# ===========================================================================
class TestCompletePeerToPeer:
    """PRD §3.5: SCHEDULED → COMPLETED."""

    def test_complete_transitions_to_completed_and_reverts_parent(
        self, api,
    ):
        """PRD §3.5: "Completing the review cascades back to the parent
        authorization, returning it from PEER_REVIEW to UNDER_REVIEW."

        Claim: complete a SCHEDULED P2P → P2P.status=COMPLETED and
        parent.status=UNDER_REVIEW.
        """
        _, _, _, auth, p2p = setup_authorization_in_peer_review()
        complete_peer_to_peer(p2p=p2p, outcome="UPHELD")
        p2p_after = re_get_peer_to_peer(p2p["id"])
        assert p2p_after["status"] == "COMPLETED"
        assert p2p_after["outcome"] == "UPHELD"
        auth_after = re_get_authorization(auth["id"])
        assert auth_after["status"] == "UNDER_REVIEW"

    def test_invalid_p2p_outcome_rejected(self, api):
        """PRD §3.5: "an outcome that must be one of UPHELD,
        OVERTURNED, or NO_SHOW (otherwise ERR_INVALID_P2P_OUTCOME)".

        Claim: complete with an outcome not in {UPHELD, OVERTURNED,
        NO_SHOW} returns ERR_INVALID_P2P_OUTCOME.
        """
        _, _, _, _, p2p = setup_authorization_in_peer_review()
        res = api.complete_peer_to_peer_review(
            p2p["id"],
            complete_peer_to_peer_payload(
                outcome="MAYBE", version=p2p["version"],
            ),
            TEST_USERS["payer_reviewer_headers"],
        )
        validate_error(res, "ERR_INVALID_P2P_OUTCOME")

    def test_overturned_p2p_applies_010_bonus_to_score(self, api):
        """PRD §3.5: "If the outcome is OVERTURNED, the parent
        authorization's evidence_completeness_score is recomputed using
        the post-peer-to-peer variant, which adds a bonus of 0.10 to the
        base score before clamping (see §3.7)."

        Claim: starting from a base score of 0.75 (3 of 4 required),
        completing an OVERTURNED P2P recomputes the parent score to
        0.85.

        Difficulty: transitive_cascade/p2p_overturn_recompute_unlocks_decision_chain_depth_two
        """
        # difficulty: transitive_cascade/p2p_overturn_recompute_unlocks_decision_chain_depth_two
        from test_helpers import (
            setup_authorization_in_peer_review_with_partial_evidence,
        )
        _, _, _, auth, p2p = (
            setup_authorization_in_peer_review_with_partial_evidence()
        )
        complete_peer_to_peer(p2p=p2p, outcome="OVERTURNED")
        auth_after = re_get_authorization(auth["id"])
        assert auth_after["status"] == "UNDER_REVIEW"
        assert auth_after["evidence_completeness_score"] == 0.85


# ===========================================================================
# Cancel
# ===========================================================================
class TestCancelPeerToPeer:
    """PRD §3.5: SCHEDULED → CANCELLED reverts the parent."""

    def test_cancel_reverts_parent_to_under_review(self, api):
        """PRD §3.5: "Cancellation transitions the
        PeerToPeerReview.status from SCHEDULED to CANCELLED and reverts
        the parent authorization from PEER_REVIEW back to UNDER_REVIEW
        (the revert path)."

        Claim: cancel a SCHEDULED P2P → P2P.status=CANCELLED and
        parent.status=UNDER_REVIEW.

        Difficulty: compensating_invariant/peer_to_peer_cancel_preserves_under_review_state_and_evidence_score
        """
        # difficulty: compensating_invariant/peer_to_peer_cancel_preserves_under_review_state_and_evidence_score
        _, provider, _, auth, p2p = setup_authorization_in_peer_review()
        score_before = auth["evidence_completeness_score"]
        cancel_peer_to_peer(p2p=p2p, actor_provider=provider)
        p2p_after = re_get_peer_to_peer(p2p["id"])
        assert p2p_after["status"] == "CANCELLED"
        auth_after = re_get_authorization(auth["id"])
        assert auth_after["status"] == "UNDER_REVIEW"
        # PRD §3.5 says the post-P2P bonus only fires on COMPLETED
        # outcome=OVERTURNED; cancellation never completes the P2P, so
        # the score is unchanged.
        assert auth_after["evidence_completeness_score"] == score_before
