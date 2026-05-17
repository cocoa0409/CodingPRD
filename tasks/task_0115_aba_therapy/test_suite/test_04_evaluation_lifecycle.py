"""Diagnostic evaluation lifecycle.

PRD §3.2 (schedule -> IN_PROGRESS -> COMPLETED; SCHEDULED|IN_PROGRESS -> VOID).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_seconds,
    advance_clock,
    assert_evaluation,
    complete_evaluation_payload,
    make_bcba_headers,
    schedule_evaluation,
    setup_clinic_with_roster,
    setup_completed_evaluation,
    start_evaluation,
    validate_error,
    validate_success,
)


class TestScheduleEvaluation:

    def test_schedule_evaluation_creates_in_scheduled(self, api):
        """PRD §3.2: "The new evaluation enters SCHEDULED status and
        carries the resolved patient_id."

        Claim: POST /patients/{id}/evaluations returns 201 with
        status == SCHEDULED.
        """
        roster = setup_clinic_with_roster()
        bcba = roster["bcbas"][0]
        evaluation = schedule_evaluation(
            patient_id=roster["patient"]["id"],
            evaluator_therapist_id=bcba["id"],
            scheduled_at=add_seconds(
                roster["clinic"]["now_ts"], seconds=3600,
            ),
        )
        assert evaluation["status"] == "SCHEDULED"
        assert_evaluation(evaluation)


class TestStartEvaluation:

    def test_start_before_scheduled_at_yields_invalid_state(self, api):
        """PRD §3.2: "If the request is made before the scheduled
        instant — that is, the clinic's now_ts is strictly earlier than
        scheduled_at — it is rejected with ERR_INVALID_STATE."

        Claim: calling /start while now_ts < scheduled_at returns
        ERR_INVALID_STATE.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        evaluation = schedule_evaluation(
            patient_id=roster["patient"]["id"],
            evaluator_therapist_id=bcba["id"],
            scheduled_at=add_seconds(
                clinic["now_ts"], seconds=3600,
            ),
        )
        # Do NOT advance the clock. now_ts is still strictly before
        # scheduled_at.
        res = api.start_evaluation(
            evaluation["id"], make_bcba_headers(bcba["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_start_by_wrong_bcba_yields_not_therapist_of_record(
        self, api,
    ):
        """PRD §3.2: "Starting the evaluation moves it from SCHEDULED
        to IN_PROGRESS; this is permitted only when the actor is the
        BCBA whose identifier equals the evaluation's
        evaluator_therapist_id, otherwise the request is rejected with
        ERR_NOT_THERAPIST_OF_RECORD."

        Claim: a DIFFERENT BCBA cannot start someone else's evaluation.
        """
        roster = setup_clinic_with_roster(num_bcbas=2)
        clinic = roster["clinic"]
        bcba_owner = roster["bcbas"][0]
        bcba_other = roster["bcbas"][1]
        scheduled_at = add_seconds(clinic["now_ts"], seconds=3600)
        evaluation = schedule_evaluation(
            patient_id=roster["patient"]["id"],
            evaluator_therapist_id=bcba_owner["id"],
            scheduled_at=scheduled_at,
        )
        advance_clock(clinic["id"], 3600)
        res = api.start_evaluation(
            evaluation["id"], make_bcba_headers(bcba_other["id"]),
        )
        validate_error(res, "ERR_NOT_THERAPIST_OF_RECORD")

    def test_start_at_or_after_scheduled_at_succeeds(self, api):
        """PRD §3.2: "the clinic's now_ts is at or after the
        evaluation's scheduled_at … Starting the evaluation moves it
        from SCHEDULED to IN_PROGRESS".

        Claim: when now_ts == scheduled_at, /start succeeds.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        scheduled_at = add_seconds(clinic["now_ts"], seconds=3600)
        evaluation = schedule_evaluation(
            patient_id=roster["patient"]["id"],
            evaluator_therapist_id=bcba["id"],
            scheduled_at=scheduled_at,
        )
        advance_clock(clinic["id"], 3600)
        res = api.start_evaluation(
            evaluation["id"], make_bcba_headers(bcba["id"]),
        )
        data = validate_success(res)
        assert data["status"] == "IN_PROGRESS"


class TestCompleteEvaluation:

    def test_complete_sets_completed_at(self, api):
        """PRD §3.2: "On the IN_PROGRESS -> COMPLETED transition,
        completed_at is set to the clinic's current now_ts."

        Claim: after /complete, evaluation.completed_at is set.
        """
        roster = setup_clinic_with_roster()
        evaluation = setup_completed_evaluation(
            clinic=roster["clinic"],
            patient=roster["patient"],
            bcba=roster["bcbas"][0],
        )
        assert evaluation["status"] == "COMPLETED"
        assert evaluation.get("completed_at") is not None

    @pytest.mark.parametrize("hours", [4, 41, 0, 100])
    def test_recommended_weekly_hours_out_of_range_rejected(
        self, api, hours,
    ):
        """PRD §3.2: "The recommended hours must be an integer in the
        inclusive range from 5 to 40."

        Claim: recommended_weekly_hours outside [5, 40] is rejected.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        scheduled_at = add_seconds(clinic["now_ts"], seconds=3600)
        evaluation = schedule_evaluation(
            patient_id=roster["patient"]["id"],
            evaluator_therapist_id=bcba["id"],
            scheduled_at=scheduled_at,
        )
        advance_clock(clinic["id"], 3600)
        start_evaluation(evaluation["id"], bcba_id=bcba["id"])
        res = api.complete_evaluation(
            evaluation["id"],
            complete_evaluation_payload(recommended_weekly_hours=hours),
            make_bcba_headers(bcba["id"]),
        )
        validate_error(res, "ERR_VALIDATION")


class TestVoidEvaluation:

    def test_clinic_admin_can_void_scheduled_evaluation(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.2: "The evaluation can also be voided by a
        ClinicAdmin from either SCHEDULED or IN_PROGRESS, terminating
        it in the VOID status."

        Claim: voiding a SCHEDULED evaluation transitions it to VOID.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        evaluation = schedule_evaluation(
            patient_id=roster["patient"]["id"],
            evaluator_therapist_id=bcba["id"],
            scheduled_at=add_seconds(clinic["now_ts"], seconds=3600),
        )
        res = api.void_evaluation(evaluation["id"], clinic_admin_headers)
        data = validate_success(res)
        assert data["status"] == "VOID"
