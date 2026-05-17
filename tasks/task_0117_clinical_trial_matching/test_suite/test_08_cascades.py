"""Cascade chains — trial termination, participant withdrawal,
AE auto-escalation.

PRD §3.7 cascades (withdraw, terminate, AE escalate).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    complete_visit,
    enroll_participant,
    find_visit_in_list,
    iso_anchor_offset,
    list_payments,
    list_visits_for_participant,
    re_get_participant,
    re_get_trial,
    report_adverse_event,
    schedule_visit,
    setup_enrolled_participant,
    setup_enrolled_with_one_completed_visit,
    setup_trial_open_for_enrollment,
    terminate_trial_payload,
    validate_success,
    withdraw_participant,
)


# ===========================================================================
# §3.7 participant-withdraw cascade.
# ===========================================================================
class TestWithdrawCascade:
    """PRD §3.7: "When the coordinator or the participant themselves
    submits the withdraw action … the transition ENROLLED → WITHDRAWN
    first sets the participant's status accordingly, then cascades
    every SCHEDULED visit on that participant to CANCELLED."
    """

    def test_withdraw_cascades_scheduled_visits_to_cancelled(self, api):
        """PRD §3.7: "cascades every SCHEDULED visit on that
        participant to CANCELLED."

        Claim: after withdraw, all SCHEDULED visits on the participant
        are CANCELLED; previously-COMPLETED visits remain COMPLETED.
        """
        trial, p, v_completed, _pmt = (
            setup_enrolled_with_one_completed_visit(
                blood_draw_window_days=7,
            )
        )
        v2 = schedule_visit(
            p["id"], sequence_no=2,
            target_date=iso_anchor_offset(days=20),
        )
        v3 = schedule_visit(
            p["id"], sequence_no=3,
            target_date=iso_anchor_offset(days=30),
        )
        withdraw_participant(p["id"])
        visits = list_visits_for_participant(p["id"])
        v1_after = find_visit_in_list(visits, v_completed["id"])
        v2_after = find_visit_in_list(visits, v2["id"])
        v3_after = find_visit_in_list(visits, v3["id"])
        assert v1_after["status"] == "COMPLETED"
        assert v2_after["status"] == "CANCELLED"
        assert v3_after["status"] == "CANCELLED"


# ===========================================================================
# §3.7 AE auto-escalation cascade.
# ===========================================================================
class TestAEEscalationCascade:
    """PRD §3.7: "The escalation cascades: every visit on that
    participant whose status is SCHEDULED is moved to CANCELLED, and
    for each such cancelled visit that was holding a PROVISIONAL
    payment row, a corresponding REVERSAL Payment row is written
    whose amount_cents is the negation of the provisional row's
    amount_cents."""

    def test_severe_ae_cancels_scheduled_visits(self, api):
        """PRD §3.7: "every visit on that participant whose status is
        SCHEDULED is moved to CANCELLED".

        Claim: SEVERE AE intake cancels SCHEDULED visits; previously
        COMPLETED visits are not touched.
        """
        trial, p, v_completed, _pmt = (
            setup_enrolled_with_one_completed_visit(
                blood_draw_window_days=7,
            )
        )
        v2 = schedule_visit(
            p["id"], sequence_no=2,
            target_date=iso_anchor_offset(days=20),
        )
        report_adverse_event(p["id"], severity="SEVERE")
        visits = list_visits_for_participant(p["id"])
        v1_after = find_visit_in_list(visits, v_completed["id"])
        v2_after = find_visit_in_list(visits, v2["id"])
        assert v1_after["status"] == "COMPLETED"
        assert v2_after["status"] == "CANCELLED"


# ===========================================================================
# §3.7 Trial termination cascade-of-cascade.
# ===========================================================================
class TestTrialTerminateCascade:
    """PRD §3.7: "When the investigator terminates the trial from
    OPEN_FOR_ENROLLMENT, every participant whose status is in
    SCREENING, ELIGIBLE, CONSENT_PENDING, or ENROLLED is cascaded to
    WITHDRAWN. Each such cascaded Participant → WITHDRAWN then itself
    cascades: every SCHEDULED visit on that participant is moved to
    CANCELLED."
    """

    def test_terminate_cascades_enrolled_to_withdrawn_and_visits_cancelled(
        self, api,
    ):
        """PRD §3.7: "every SCHEDULED visit on that participant is
        moved to CANCELLED. This is the cascade-of-cascade pattern".

        Claim: terminating the trial leaves participants WITHDRAWN
        and their SCHEDULED visits CANCELLED.
        """
        trial, p, _arms = setup_enrolled_participant(
            blood_draw_window_days=7,
        )
        v1 = schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        api.terminate_trial(
            trial["id"], terminate_trial_payload(reason="sponsor pull"),
            TEST_USERS["pi_headers"],
        )
        p_after = re_get_participant(p["id"])
        assert p_after["status"] == "WITHDRAWN"
        visits = list_visits_for_participant(p["id"])
        v_after = find_visit_in_list(visits, v1["id"])
        assert v_after["status"] == "CANCELLED"
        t_after = re_get_trial(trial["id"])
        assert t_after["status"] == "TERMINATED"
