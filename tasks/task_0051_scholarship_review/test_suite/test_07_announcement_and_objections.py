"""Rank/award via REVIEWING->ANNOUNCED, objection cascades, and
ANNOUNCED->FINALIZED preconditions."""
from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    advance_clock,
    announce_scholarship,
    api_client,
    create_objection,
    finalize_scholarship,
    find_external_sync_events,
    list_external_sync,
    list_quota_slices,
    rule_objection,
    setup_announced_with_one_awarded,
    setup_announced_with_winner_and_runnerup,
    setup_review_complete,
    validate_error,
    validate_success,
)


class TestAnnouncementTransition:

    def test_announce_with_one_review_complete_awards_application(self):
        """PRD §3.8: "Every candidate whose final_rank is at most the
        slice's current_slots transitions REVIEW_COMPLETE → AWARDED, and
        the slice's filled_slots is incremented by one for each."

        Claim: when REVIEWING→ANNOUNCED, the only REVIEW_COMPLETE app
        becomes AWARDED with final_rank == 1.
        """
        state = setup_announced_with_one_awarded()
        assert state["application"]["status"] == "AWARDED"
        assert state["application"].get("final_rank") == 1

    def test_announce_emits_im_notify_award_external_sync(self):
        """PRD §3.8: "one IM_NOTIFY_AWARD external-sync event per AWARDED
        application and one IM_NOTIFY_REJECT per NOT_AWARDED
        application".

        Claim: announce -> ExternalSyncEvent(kind=IM_NOTIFY_AWARD,
        application_id=awarded.id) exists.
        """
        state = setup_announced_with_one_awarded()
        events = list_external_sync()
        awarded_events = find_external_sync_events(
            events, kind="IM_NOTIFY_AWARD",
            application_id=state["application"]["id"],
        )
        assert awarded_events, (
            "PRD §3.8 requires IM_NOTIFY_AWARD per AWARDED application"
        )

    def test_announce_emits_academic_affairs_finalized(self):
        """PRD §3.8: "emits one ExternalSyncEvent with kind
        ACADEMIC_AFFAIRS_FINALIZED (scholarship-scoped, so its
        application_id is absent)".

        Claim: ANNOUNCED -> ExternalSyncEvent(kind=ACADEMIC_AFFAIRS_FINALIZED,
        scholarship_id=sch.id) exists.
        """
        state = setup_announced_with_one_awarded()
        events = list_external_sync()
        finalized = find_external_sync_events(
            events, kind="ACADEMIC_AFFAIRS_FINALIZED",
            scholarship_id=state["scholarship"]["id"],
        )
        assert finalized, (
            "PRD §3.8: one ExternalSyncEvent with kind "
            "ACADEMIC_AFFAIRS_FINALIZED expected"
        )

    def test_announce_with_pending_under_review_app_rejected(self):
        """PRD §3.8: "every non-rejected application must have reached
        REVIEW_COMPLETE (i.e. every application that is not in WITHDRAWN,
        DRAFT, or DEPT_PRELIM_REJECTED must be in REVIEW_COMPLETE);
        otherwise the transition is rejected with ERR_REVIEW_NOT_COMPLETE."

        Claim: REVIEWING->ANNOUNCED with at least one non-rejected app
        not in REVIEW_COMPLETE -> ERR_REVIEW_NOT_COMPLETE.
        """
        # Build state: scholarship in REVIEWING with an app in
        # UNDER_REVIEW (not REVIEW_COMPLETE).
        from test_helpers import setup_application_under_review
        state = setup_application_under_review()
        # No scores have been submitted yet, so the app is in
        # UNDER_REVIEW.
        resp = api_client.transition_scholarship(
            state["scholarship"]["id"],
            {"to_status": "ANNOUNCED"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_COMPLETE.value)


class TestObjectionWindow:

    def test_objection_after_announcement_window_rejected(self):
        """PRD §3.9: "An objection may be submitted only while the
        logical "now" is strictly earlier than the scholarship's
        announcement_window_end; later attempts are rejected with
        ERR_WINDOW_CLOSED."

        Claim: clock past announcement_window_end -> POST objection
        returns ERR_WINDOW_CLOSED.
        """
        state = setup_announced_with_one_awarded()
        advance_clock(state["scholarship"]["announcement_window_end"])
        from test_helpers import (
            create_objection_payload, make_student_headers, new_student_id,
        )
        sid = new_student_id("objector")
        headers = make_student_headers(sid)
        resp = api_client.create_objection(
            state["scholarship"]["id"],
            create_objection_payload(
                application_id=state["application"]["id"],
                objector_student_id=sid,
            ),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_CLOSED.value)


class TestObjectionRulingAndCascade:

    def test_upheld_objection_revokes_awarded_application(self):
        """PRD §3.9: "An upheld ruling transitions the objection from
        PENDING to UPHELD. If the objected-against application is
        currently in AWARDED, that application transitions AWARDED →
        REVOKED by cascade; on revocation the application's
        revocation_reason is set to OBJECTION_UPHELD".

        Claim: upholding objection on AWARDED app -> app.status=REVOKED
        with revocation_reason=OBJECTION_UPHELD.
        """
        state = setup_announced_with_winner_and_runnerup()
        objection = create_objection(
            state["scholarship"]["id"],
            state["winner"]["id"],
            reason_code="MATERIAL_FALSE",
        )
        rule_objection(
            state["scholarship"]["id"], objection["id"],
            decision="UPHOLD", ruling_comment="Transcript forged",
        )
        # Refresh winner.
        winner = validate_success(
            api_client.get_application(
                state["scholarship"]["id"], state["winner"]["id"], ADMIN,
            ),
        )
        assert winner["status"] == "REVOKED"
        assert winner["revocation_reason"] == "OBJECTION_UPHELD"

    def test_upheld_objection_promotes_runner_up(self):
        """PRD §3.9: "a single promotion cascade runs: the highest-ranked
        NOT_AWARDED application in the same slice (selected by descending
        aggregated_score_x100, then ascending student_id lexically as the
        tie-break) is flipped to AWARDED."

        Claim: after upheld objection on AWARDED app, the runner-up
        NOT_AWARDED in the same slice becomes AWARDED.
        # difficulty: transitive_cascade/objection_upheld_revoke_and_promote_chain
        """
        state = setup_announced_with_winner_and_runnerup()
        objection = create_objection(
            state["scholarship"]["id"],
            state["winner"]["id"],
            reason_code="MATERIAL_FALSE",
        )
        rule_objection(
            state["scholarship"]["id"], objection["id"],
            decision="UPHOLD", ruling_comment="Forged",
        )
        runner_up = validate_success(
            api_client.get_application(
                state["scholarship"]["id"],
                state["runner_up"]["id"], ADMIN,
            ),
        )
        assert runner_up["status"] == "AWARDED", (
            "PRD §3.9: runner-up must be cascade-promoted to AWARDED"
        )

    def test_upheld_objection_emits_im_notify_objection_ruling(self):
        """PRD §3.9: "The upheld ruling also emits an ExternalSyncEvent
        with kind IM_NOTIFY_OBJECTION_RULING."

        Claim: upholding objection -> ExternalSyncEvent(kind=
        IM_NOTIFY_OBJECTION_RULING) exists.
        """
        state = setup_announced_with_winner_and_runnerup()
        objection = create_objection(
            state["scholarship"]["id"],
            state["winner"]["id"],
            reason_code="MATERIAL_FALSE",
        )
        rule_objection(
            state["scholarship"]["id"], objection["id"],
            decision="UPHOLD", ruling_comment="Forged",
        )
        events = list_external_sync()
        ruling_events = find_external_sync_events(
            events, kind="IM_NOTIFY_OBJECTION_RULING",
        )
        assert ruling_events, (
            "PRD §3.9 upheld ruling must emit "
            "IM_NOTIFY_OBJECTION_RULING ExternalSyncEvent"
        )

    def test_upheld_objection_conserves_quota_invariant(self):
        """PRD §3.9 + §3.1: 'filled_slots is the running count of
        applications in the slice with status AWARDED or DISBURSED';
        and 'the slice's filled_slots is decremented by one ... a single
        promotion cascade runs ... is flipped to AWARDED.'

        Claim: post-upheld with a single-slot slice and one runner-up,
        QuotaAllocation.filled_slots remains 1 (decrement + increment).
        # difficulty: compensating_invariant/award_count_invariant_under_revoke_and_promote
        """
        state = setup_announced_with_winner_and_runnerup()
        pre_slices = list_quota_slices(state["scholarship"]["id"])
        pre_filled = sum(s["filled_slots"] for s in pre_slices)
        assert pre_filled == 1

        objection = create_objection(
            state["scholarship"]["id"],
            state["winner"]["id"],
            reason_code="MATERIAL_FALSE",
        )
        rule_objection(
            state["scholarship"]["id"], objection["id"],
            decision="UPHOLD", ruling_comment="Forged",
        )
        post_slices = list_quota_slices(state["scholarship"]["id"])
        post_filled = sum(s["filled_slots"] for s in post_slices)
        assert post_filled == 1, (
            "PRD §3.9 quota slot invariant: "
            "filled_slots conserved under revoke + promote cascade"
        )


class TestFinalizedPreconditions:

    def test_finalize_with_pending_objection_rejected(self):
        """PRD §3.9: "no objection against any application of this
        scholarship may still be in PENDING (else ERR_OBJECTION_PENDING)".

        Claim: ANNOUNCED -> FINALIZED while a PENDING objection exists
        -> ERR_OBJECTION_PENDING.
        """
        state = setup_announced_with_one_awarded()
        from test_helpers import (
            create_objection_payload, make_student_headers, new_student_id,
        )
        sid = new_student_id("objector")
        headers = make_student_headers(sid)
        validate_success(
            api_client.create_objection(
                state["scholarship"]["id"],
                create_objection_payload(
                    application_id=state["application"]["id"],
                    objector_student_id=sid,
                ),
                headers,
            ),
            expected_status=201,
        )
        advance_clock(state["scholarship"]["announcement_window_end"])
        resp = api_client.transition_scholarship(
            state["scholarship"]["id"],
            {"to_status": "FINALIZED"}, ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_OBJECTION_PENDING.value)

    def test_finalize_before_window_closed_rejected(self):
        """PRD §3.9: "the logical "now" must be at least
        announcement_window_end (else ERR_WINDOW_NOT_CLOSED)".

        Claim: admin tries to finalize before announcement_window_end
        -> ERR_WINDOW_NOT_CLOSED.
        """
        state = setup_announced_with_one_awarded()
        # Clock still inside announcement window.
        resp = api_client.transition_scholarship(
            state["scholarship"]["id"],
            {"to_status": "FINALIZED"}, ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_CLOSED.value)
