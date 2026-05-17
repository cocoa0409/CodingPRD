"""Adverse events — intake, severity-driven auto-escalation,
workflow transitions, AE-blocking of visit-complete.

PRD §3.7 (AE lifecycle and cascades), §3.6 (AE gate on visit-complete).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_adverse_event,
    create_adverse_event_payload,
    enroll_participant,
    iso_anchor_offset,
    list_aes,
    list_visits_for_participant,
    re_get_participant,
    report_adverse_event,
    resolve_ae,
    schedule_visit,
    setup_enrolled_participant,
    setup_trial_open_for_enrollment,
    start_review_ae,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.7 AE intake — MILD/MODERATE stay OPEN; SEVERE/LIFE_THREATENING
# auto-escalate.
# ===========================================================================
class TestAdverseEventIntake:
    """PRD §3.7 intake branching."""

    def test_mild_intake_stays_open(self, api):
        """PRD §3.7: "When severity is MILD or MODERATE, the event
        remains in OPEN and no cascade fires beyond the bump of
        open_ae_count."

        Claim: a MILD AE intake produces an AE in OPEN and bumps
        open_ae_count to 1.
        """
        trial, p, _arms = setup_enrolled_participant()
        res = api.create_adverse_event(
            p["id"],
            create_adverse_event_payload(severity="MILD"),
            TEST_USERS["study_coordinator_headers"],
        )
        ae = validate_success(res, 201)
        assert_adverse_event(ae)
        assert ae["status"] == "OPEN"
        p_after = re_get_participant(p["id"])
        assert p_after["open_ae_count"] == 1

    def test_moderate_intake_stays_open(self, api):
        """PRD §3.7: "When severity is MILD or MODERATE, the event
        remains in OPEN".

        Claim: MODERATE intake also stays in OPEN.
        """
        trial, p, _arms = setup_enrolled_participant()
        res = api.create_adverse_event(
            p["id"],
            create_adverse_event_payload(severity="MODERATE"),
            TEST_USERS["study_coordinator_headers"],
        )
        ae = validate_success(res, 201)
        assert ae["status"] == "OPEN"

    def test_severe_intake_auto_escalates(self, api):
        """PRD §3.7: "When severity is SEVERE or LIFE_THREATENING, the
        newly created event is immediately transitioned OPEN →
        ESCALATED_HOLD by the system as part of the same commit."

        Claim: a SEVERE AE intake yields an AE in ESCALATED_HOLD.
        """
        trial, p, _arms = setup_enrolled_participant()
        res = api.create_adverse_event(
            p["id"],
            create_adverse_event_payload(severity="SEVERE"),
            TEST_USERS["study_coordinator_headers"],
        )
        ae = validate_success(res, 201)
        assert ae["status"] == "ESCALATED_HOLD"
        # open_ae_count still counts the escalated AE as open until
        # RESOLVED, per PRD §3.7.
        p_after = re_get_participant(p["id"])
        assert p_after["open_ae_count"] == 1

    def test_life_threatening_intake_auto_escalates(self, api):
        """PRD §3.7: "When severity is SEVERE or LIFE_THREATENING, the
        newly created event is immediately transitioned OPEN →
        ESCALATED_HOLD".

        Claim: LIFE_THREATENING intake also auto-escalates.
        """
        trial, p, _arms = setup_enrolled_participant()
        res = api.create_adverse_event(
            p["id"],
            create_adverse_event_payload(severity="LIFE_THREATENING"),
            TEST_USERS["study_coordinator_headers"],
        )
        ae = validate_success(res, 201)
        assert ae["status"] == "ESCALATED_HOLD"

    def test_life_threatening_auto_closes_open_trial(self, api):
        """PRD §3.7: "Additionally, when severity is LIFE_THREATENING
        and the parent trial is currently OPEN_FOR_ENROLLMENT, the
        trial itself is cascaded to CLOSED_TO_ENROLLMENT in the same
        commit."

        Claim: a LIFE_THREATENING AE on an OPEN trial cascades the
        trial to CLOSED_TO_ENROLLMENT.
        """
        trial, p, _arms = setup_enrolled_participant()
        api.create_adverse_event(
            p["id"],
            create_adverse_event_payload(severity="LIFE_THREATENING"),
            TEST_USERS["study_coordinator_headers"],
        )
        from test_helpers import re_get_trial
        t_after = re_get_trial(trial["id"])
        assert t_after["status"] == "CLOSED_TO_ENROLLMENT"


# ===========================================================================
# §3.7 cross-participant attribution.
# ===========================================================================
class TestAECrossParticipantReference:
    """PRD §3.7: "If caused_visit_id is set and the referenced visit
    belongs to a different participant, the report is rejected with
    ERR_CROSS_PARTICIPANT_REFERENCE at HTTP 422.\""""

    def test_cross_participant_caused_visit_rejected(self, api):
        """PRD §3.7: "If caused_visit_id is set and the referenced
        visit belongs to a different participant, the report is
        rejected with ERR_CROSS_PARTICIPANT_REFERENCE at HTTP 422."

        Claim: AE intake on P_a with caused_visit_id pointing to a
        visit on P_b fires ERR_CROSS_PARTICIPANT_REFERENCE.
        """
        trial, p_a, _arms = setup_enrolled_participant()
        p_b = enroll_participant(
            trial["id"], active_consent_version=1,
            profile={"age": 40},
        )
        v_on_b = schedule_visit(
            p_b["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        res = api.create_adverse_event(
            p_a["id"],
            create_adverse_event_payload(
                severity="MILD", caused_visit_id=v_on_b["id"],
            ),
            TEST_USERS["study_coordinator_headers"],
        )
        validate_error(res, "ERR_CROSS_PARTICIPANT_REFERENCE")


# ===========================================================================
# §3.7 workflow transitions and §3.6 AE gate on visit-complete.
# ===========================================================================
class TestAEWorkflow:
    """PRD §3.7 OPEN → UNDER_REVIEW → RESOLVED and the
    open_ae_count delta."""

    def test_start_review_keeps_open_ae_count_unchanged(self, api):
        """PRD §3.7: "Starting review transitions OPEN → UNDER_REVIEW;
        the participant's open_ae_count is unchanged by this move
        because an under-review event still counts as open against the
        visit-complete gate of §3.6."

        Claim: open_ae_count is unchanged after start-review.
        """
        trial, p, _arms = setup_enrolled_participant()
        ae = report_adverse_event(p["id"], severity="MILD")
        before = re_get_participant(p["id"])["open_ae_count"]
        ae2 = start_review_ae(p["id"], ae["id"])
        assert ae2["status"] == "UNDER_REVIEW"
        after = re_get_participant(p["id"])["open_ae_count"]
        assert after == before

    def test_resolve_decrements_open_ae_count(self, api):
        """PRD §3.7: "this writes RESOLVED as the new status, records
        the resolution note on the event, and decrements open_ae_count
        by one."

        Claim: resolve drops open_ae_count by 1.
        """
        trial, p, _arms = setup_enrolled_participant()
        ae = report_adverse_event(p["id"], severity="MILD")
        start_review_ae(p["id"], ae["id"])
        before = re_get_participant(p["id"])["open_ae_count"]
        resolved = resolve_ae(p["id"], ae["id"])
        assert resolved["status"] == "RESOLVED"
        after = re_get_participant(p["id"])["open_ae_count"]
        assert after == before - 1


class TestAEGatesVisitComplete:
    """PRD §3.6 priority-30 AE gate."""

    def test_visit_complete_blocked_by_open_ae(self, api):
        """PRD §3.6: "the participant's open_ae_count must be exactly
        zero; if any adverse event is still in OPEN or UNDER_REVIEW,
        the visit-complete is rejected with ERR_AE_BLOCKING."

        Claim: a MILD AE on a participant blocks visit-complete with
        ERR_AE_BLOCKING.
        """
        trial, p, _arms = setup_enrolled_participant(
            blood_draw_window_days=7,
        )
        v = schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        report_adverse_event(p["id"], severity="MILD")
        advance_clock_to(iso_anchor_offset(days=10, hours=12))
        res = api.complete_visit(
            v["id"],
            {"actual_draw_at": iso_anchor_offset(days=10, hours=12)},
            TEST_USERS["study_coordinator_headers"],
        )
        validate_error(res, "ERR_AE_BLOCKING")
