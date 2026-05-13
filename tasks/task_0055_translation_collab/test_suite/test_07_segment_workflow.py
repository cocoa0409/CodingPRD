"""Three-stage translation pipeline: translate → review → final-approve.

PRD §3.4 (The Three-Stage Translation Pipeline), §2.12 (Compound State).
"""
from __future__ import annotations
import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    PM,
    api_client,
    assert_segment,
    dispatch_assignment,
    find_audit_entries,
    get_segment,
    list_all_audit_entries,
    make_translator_headers,
    reject_segment,
    setup_full_pipeline_one_segment,
    setup_quoted_project_with_one_word_segment,
    setup_segment_at_reviewed,
    setup_segment_at_translated,
    setup_translator_passed,
    submit_review,
    submit_translation,
)


# ===========================================================================
# Translator submits translation (PRD §3.4)
# ===========================================================================
class TestSubmitTranslation:

    def test_submit_translation_transitions_segment_to_translated(self):
        """PRD §3.4: "The translator who has accepted a TRANSLATOR-role
        assignment submits the translation of each covered segment by
        supplying translated_text (which must be non-empty); the segment
        transitions from ASSIGNED to TRANSLATED."

        Claim: submit-translation -> Segment.state == "TRANSLATED".
        """
        ctx = setup_segment_at_translated()
        seg = get_segment(ctx["segments"][0]["id"])
        assert seg["state"] == "TRANSLATED"

    def test_submit_translation_by_non_assignee_is_rejected(self):
        """PRD §3.4: "The submitter must be the assignee of the current
        Assignment with role TRANSLATOR covering the segment; any other
        caller is refused with ERR_INVALID_SEGMENT_STATE (because the
        segment is held by a different translator) or ERR_FORBIDDEN
        (because the role check fails first)."

        Claim: a Translator not assigned to the segment cannot submit
        translation — surface as ERR_FORBIDDEN or ERR_INVALID_SEGMENT_STATE.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t = setup_translator_passed(grade="SENIOR")
        other = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
        api_client.activate_project(project["id"], PM)
        api_client.accept_assignment(a["id"], make_translator_headers(t["id"]))
        # Other tries to submit (not the assignee)
        from prd_bench_local_runner.testing import validate_error_is_one_of
        resp = api_client.submit_translation(
            seg_ids[0], {"translated_text": "x"},
            make_translator_headers(other["id"]),
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_FORBIDDEN.value,
            ApiErrorId.ERR_INVALID_SEGMENT_STATE.value,
        ])

    def test_submit_translation_on_new_segment_returns_invalid_segment_state(self):
        """PRD §3.4: "A segment whose state is not ASSIGNED cannot be
        translated; that case yields ERR_INVALID_SEGMENT_STATE."

        Claim: attempting submit-translation on a NEW (unassigned) segment
        yields ERR_INVALID_SEGMENT_STATE.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        # Don't dispatch / accept — segment still in NEW state.
        resp = api_client.submit_translation(
            seg_ids[0], {"translated_text": "x"},
            make_translator_headers(t["id"]),
        )
        # Without an assignment, depending on validation priority the
        # response is ERR_INVALID_SEGMENT_STATE (priority 5) — PRD §3.4
        # explicitly names this error for this case.
        validate_error(resp, ApiErrorId.ERR_INVALID_SEGMENT_STATE)


# ===========================================================================
# Reviewer (PRD §3.4)
# ===========================================================================
class TestSubmitReview:

    def test_submit_review_transitions_segment_to_reviewed(self):
        """PRD §3.4: "The translator who holds the REVIEWER-role
        assignment covering the segment submits review by supplying the
        revised text (reviewed_text, non-empty); the segment transitions
        from TRANSLATED to REVIEWED."

        Claim: submit-review -> Segment.state == "REVIEWED".
        """
        ctx = setup_segment_at_reviewed()
        seg = get_segment(ctx["segments"][0]["id"])
        assert seg["state"] == "REVIEWED"


# ===========================================================================
# Final approval and rejection cycles
# ===========================================================================
class TestFinalApproveAndReject:

    def test_final_approve_transitions_to_final_approved(self):
        """PRD §3.4: "The translator who holds the FINAL_REVIEWER-role
        assignment performs final approval; the segment transitions from
        REVIEWED to FINAL_APPROVED."

        Claim: final-approve -> Segment.state == "FINAL_APPROVED".
        """
        ctx = setup_full_pipeline_one_segment(translator_grade="SENIOR")
        seg = get_segment(ctx["segments"][0]["id"])
        assert seg["state"] == "FINAL_APPROVED"

    def test_reviewer_reject_segment_regresses_to_new(self):
        """PRD §3.4: "A reviewer may reject a TRANSLATED segment by
        supplying a reason; the segment regresses to NEW, its
        assignment_id is cleared."

        Claim: REVIEWER rejection of a TRANSLATED segment regresses
        Segment.state to NEW and clears assignment_id.
        """
        ctx = setup_segment_at_translated()
        # Need a REVIEWER to call reject. Set one up + dispatch + accept.
        rev = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in ctx["segments"]]
        a = dispatch_assignment(
            ctx["project"]["id"], rev["id"], "REVIEWER", seg_ids,
        )
        api_client.accept_assignment(a["id"], make_translator_headers(rev["id"]))
        # REVIEWER rejects
        reject_segment(seg_ids[0], rev["id"], reason="rework")
        seg = get_segment(seg_ids[0])
        assert seg["state"] == "NEW"
        # assignment_id must be cleared
        assert seg.get("assignment_id") in (None, ""), \
            "PRD §3.4: 'its assignment_id is cleared.'"

    def test_final_reviewer_reject_segment_regresses_to_translated(self):
        """PRD §3.4: "A final reviewer may reject a REVIEWED segment by
        supplying a reason and, optionally, an errors array describing the
        defects spotted; the segment regresses to TRANSLATED."

        Claim: FINAL_REVIEWER rejection regresses Segment.state to
        TRANSLATED (not NEW).
        """
        ctx = setup_segment_at_reviewed()
        final = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in ctx["segments"]]
        a = dispatch_assignment(
            ctx["project"]["id"], final["id"], "FINAL_REVIEWER", seg_ids,
        )
        api_client.accept_assignment(
            a["id"], make_translator_headers(final["id"]),
        )
        reject_segment(seg_ids[0], final["id"], reason="rework")
        seg = get_segment(seg_ids[0])
        assert seg["state"] == "TRANSLATED", (
            "PRD §3.4: final-reviewer rejection regresses to TRANSLATED, "
            "not NEW."
        )


# ===========================================================================
# Compound state (PRD §2.12)
# ===========================================================================
class TestCompoundState:

    def test_all_translated_after_every_segment_translated(self):
        """PRD §2.12: "When every segment of a project has reached one of
        TRANSLATED, REVIEWED, or FINAL_APPROVED, the project transitions
        automatically from ACTIVE to ALL_TRANSLATED."

        Claim: Project.state advances to ALL_TRANSLATED.
        """
        ctx = setup_segment_at_translated()
        proj = api_client.get_project(ctx["project"]["id"], PM).json()["data"]
        assert proj["state"] in ("ALL_TRANSLATED", "ALL_REVIEWED", "PUBLISHED"), (
            f"Expected ALL_TRANSLATED bubble; got {proj['state']}"
        )

    def test_all_reviewed_demotes_to_all_translated_on_final_reject(self):
        """PRD §2.12: "if a final reviewer rejects a segment back to
        TRANSLATED while the project sits in ALL_REVIEWED, the project
        demotes back to ALL_TRANSLATED."

        Claim: Project.state demotes from ALL_REVIEWED to ALL_TRANSLATED.
        """
        ctx = setup_segment_at_reviewed()
        # Need ALL segments REVIEWED so the project bubbled to ALL_REVIEWED.
        proj = api_client.get_project(ctx["project"]["id"], PM).json()["data"]
        # Setup with one segment means after submit_review project is ALL_REVIEWED.
        assert proj["state"] == "ALL_REVIEWED", \
            f"setup must produce ALL_REVIEWED, got {proj['state']}"
        # Dispatch FINAL_REVIEWER and have them reject.
        final = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in ctx["segments"]]
        a = dispatch_assignment(
            ctx["project"]["id"], final["id"], "FINAL_REVIEWER", seg_ids,
        )
        api_client.accept_assignment(
            a["id"], make_translator_headers(final["id"]),
        )
        reject_segment(seg_ids[0], final["id"], reason="rework")
        proj2 = api_client.get_project(ctx["project"]["id"], PM).json()["data"]
        assert proj2["state"] == "ALL_TRANSLATED", (
            "PRD §2.12: final-reviewer rejection of a REVIEWED segment "
            "demotes Project ALL_REVIEWED -> ALL_TRANSLATED."
        )


# ===========================================================================
# Audit emission (PRD §2.7, §3.9)
# ===========================================================================
class TestAuditEmission:

    def test_state_transition_emits_audit_entry(self):
        """PRD §2.7: "Every state transition produced by a state machine
        in this document ... emits an AuditEntry whose event is
        STATE_TRANSITION."

        Claim: submit-translation produces a Segment STATE_TRANSITION
        AuditEntry with to_state == "TRANSLATED".
        """
        ctx = setup_segment_at_translated()
        seg = ctx["segments"][0]
        entries = list_all_audit_entries(
            subject_type="Segment", subject_id=seg["id"],
        )
        translated = find_audit_entries(
            entries, subject_type="Segment", subject_id=seg["id"],
            event="STATE_TRANSITION", to_state="TRANSLATED",
        )
        assert translated, (
            "PRD §2.7: state transitions emit AuditEntry STATE_TRANSITION"
        )
