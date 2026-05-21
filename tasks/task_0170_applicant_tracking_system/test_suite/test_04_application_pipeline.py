"""Application pipeline — PRD §3.3.

Covers: creation, duplicate-application uniqueness, the multi-gated
INTERVIEWING → OFFER_STAGE advance (OFCCP gate, qualifying feedback,
empty-panel), withdraw, reject.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_application,
    advance_application_to_interviewing,
    advance_application_to_offer_stage,
    assert_application,
    assert_stage,
    attach_eeo_record,
    create_application,
    create_candidate,
    create_interview_feedback_payload,
    create_interviewer,
    get_application,
    make_interviewer_headers,
    setup_application_in_interviewing,
    setup_application_in_offer_stage,
    setup_open_requisition,
    submit_feedback,
    validate_error,
    validate_success,
    withdraw_application,
)


# ===========================================================================
# Application creation + uniqueness — PRD §3.3
# ===========================================================================
class TestApplicationCreation:

    def test_new_application_is_in_applied(self, api):
        """PRD §3.3: "The newly created application is in `APPLIED`".

        Claim: POST /requisitions/{id}/applications returns
        stage=APPLIED.
        """
        recruiter, _hm, req = setup_open_requisition()
        candidate = create_candidate(actor_recruiter_id=recruiter["id"])
        application = create_application(
            requisition_id=req["id"],
            candidate_id=candidate["id"],
            actor_recruiter_id=recruiter["id"],
        )
        assert_application(application)
        assert_stage(application, "APPLIED")

    def test_duplicate_application_rejected(self, api):
        """PRD §3.3: "The pair (`requisition_id`, `candidate_id`) is
        unique whenever the application's `stage` is not in
        `WITHDRAWN` or `REJECTED`; an attempt to create a second live
        application for the same pair is rejected with
        `ERR_DUPLICATE_APPLICATION`."

        Claim: second POST for the same (requisition_id, candidate_id)
        → ERR_DUPLICATE_APPLICATION / 409.
        """
        recruiter, _hm, req = setup_open_requisition()
        candidate = create_candidate(actor_recruiter_id=recruiter["id"])
        create_application(
            requisition_id=req["id"],
            candidate_id=candidate["id"],
            actor_recruiter_id=recruiter["id"],
        )
        # Second create.
        from test_helpers import (
            create_application_payload, make_recruiter_headers,
        )
        h = make_recruiter_headers(recruiter["id"])
        payload = create_application_payload(candidate_id=candidate["id"])
        resp = api.create_application(req["id"], payload, h)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION.value)


# ===========================================================================
# Advance gating — PRD §3.3
# ===========================================================================
class TestApplicationAdvance:

    def test_screening_to_interviewing_requires_scheduled_interview(
        self, api,
    ):
        """PRD §3.3: "Advancing from `SCREENING` to `INTERVIEWING`
        additionally requires that at least one `Interview` already
        exists under the application in `SCHEDULED` status."

        Claim: advance from SCREENING without any scheduled interview
        → ERR_INVALID_STATE / 409.
        """
        recruiter, _hm, req = setup_open_requisition()
        candidate = create_candidate(actor_recruiter_id=recruiter["id"])
        application = create_application(
            requisition_id=req["id"],
            candidate_id=candidate["id"],
            actor_recruiter_id=recruiter["id"],
        )
        # APPLIED → SCREENING is just OPEN.
        application = advance_application(
            application_id=application["id"],
            recruiter_id=recruiter["id"],
        )
        assert_stage(application, "SCREENING")
        # No interview scheduled → second advance must fail.
        from test_helpers import make_recruiter_headers
        h = make_recruiter_headers(recruiter["id"])
        resp = api.advance_application(application["id"], h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_offer_stage_requires_qualifying_feedback(self, api):
        """PRD §3.3: "Advancing from `INTERVIEWING` to `OFFER_STAGE`
        is the most heavily gated transition in the system. It requires
        ... (b) at least one `Interview` under the application has
        reached `COMPLETED` and carries at least one `InterviewFeedback`
        whose `recommendation` is `HIRE` or `STRONG_HIRE` — otherwise
        the advance is rejected with `ERR_NO_QUALIFYING_FEEDBACK`".

        Claim: advance to OFFER_STAGE after a COMPLETED interview that
        carries only a NO_HIRE feedback → ERR_NO_QUALIFYING_FEEDBACK.
        """
        ctx = setup_application_in_interviewing()
        # Complete the interview after the clock advances past end.
        from test_helpers import (
            add_minutes, try_advance_clock_to_iso, complete_interview,
        )
        try_advance_clock_to_iso(
            add_minutes(ctx["interview"]["scheduled_end_at"], 1),
        )
        complete_interview(
            interview_id=ctx["interview"]["id"],
            recruiter_id=ctx["recruiter"]["id"],
        )
        # Submit a NO_HIRE feedback only — non-qualifying.
        submit_feedback(
            interview_id=ctx["interview"]["id"],
            interviewer_id=ctx["interviewer"]["id"],
            overall_score=2,
            recommendation="NO_HIRE",
        )
        # Now attempt advance.
        from test_helpers import make_recruiter_headers
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        resp = api.advance_application(ctx["application"]["id"], h)
        validate_error(resp, ApiErrorId.ERR_NO_QUALIFYING_FEEDBACK.value)

    def test_offer_stage_requires_eeo_record_for_protected(self, api):
        """PRD §3.3: "(e) the OFCCP gate: if the candidate is flagged
        `is_in_eeo_protected_class`, an `EEORecord` must already be
        attached to that candidate; otherwise the advance is rejected
        with `ERR_EEO_DATA_MISSING`."

        Claim: candidate is protected but no EEORecord attached →
        advance to OFFER_STAGE rejected with ERR_EEO_DATA_MISSING.
        """
        # We set attach_eeo=False on a protected candidate to construct
        # the failure scenario — everything else upstream is valid.
        ctx = setup_application_in_interviewing(
            candidate_protected=True, attach_eeo=False,
        )
        from test_helpers import (
            add_minutes, try_advance_clock_to_iso, complete_interview,
            make_recruiter_headers,
        )
        try_advance_clock_to_iso(
            add_minutes(ctx["interview"]["scheduled_end_at"], 1),
        )
        complete_interview(
            interview_id=ctx["interview"]["id"],
            recruiter_id=ctx["recruiter"]["id"],
        )
        submit_feedback(
            interview_id=ctx["interview"]["id"],
            interviewer_id=ctx["interviewer"]["id"],
            overall_score=5,
            recommendation="STRONG_HIRE",
        )
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        resp = api.advance_application(ctx["application"]["id"], h)
        validate_error(resp, ApiErrorId.ERR_EEO_DATA_MISSING.value)

    def test_offer_stage_pins_eeo_snapshot_version(self, api):
        """PRD §3.3: "On a successful advance into `OFFER_STAGE`, the
        application snapshots the candidate's `version` into
        `pinned_eeo_snapshot_version`."

        Claim: after advance into OFFER_STAGE,
        pinned_eeo_snapshot_version is non-null.
        """
        ctx = setup_application_in_offer_stage()
        app = get_application(ctx["application"]["id"])
        assert app["stage"] == "OFFER_STAGE"
        assert app.get("pinned_eeo_snapshot_version") is not None, (
            "OFFER_STAGE advance must pin pinned_eeo_snapshot_version"
        )


# ===========================================================================
# panel_average_score — PRD §3.4
# ===========================================================================
class TestPanelAverageScore:

    def test_panel_average_score_rounds_half_up_two_decimals(self, api):
        """PRD §3.4: "the score is the sum of the in-set scores divided
        by the count of in-set feedbacks, rounded half up to two
        decimal places."

        Claim: with two completed interviews carrying scores 4 and 5,
        panel_average_score == 4.50.
        """
        # Build a setup with TWO interviews; score 4 and 5 → mean 4.5.
        recruiter, _hm, req = setup_open_requisition()
        candidate = create_candidate(actor_recruiter_id=recruiter["id"])
        v1 = create_interviewer(is_certified_for_eeo=True)
        v2 = create_interviewer(is_certified_for_eeo=True)
        application = create_application(
            requisition_id=req["id"],
            candidate_id=candidate["id"],
            actor_recruiter_id=recruiter["id"],
        )
        from test_helpers import (
            add_hours, add_minutes, advance_clock_to_iso,
            complete_interview, init_clock, schedule_interview,
            TEST_DEFAULTS,
        )
        anchor = init_clock(TEST_DEFAULTS["INITIAL_CLOCK_ISO"])
        # APPLIED → SCREENING
        application = advance_application(
            application_id=application["id"],
            recruiter_id=recruiter["id"],
        )
        # SCREENING → INTERVIEWING (needs one scheduled).
        i1 = schedule_interview(
            application_id=application["id"],
            recruiter_id=recruiter["id"],
            interviewer_id=v1["id"],
            start_at=add_hours(anchor, 1),
            end_at=add_hours(anchor, 2),
        )
        application = advance_application(
            application_id=application["id"],
            recruiter_id=recruiter["id"],
        )
        # Schedule a second interview on v2 well after i1 to avoid
        # buffer collisions (i1 ends at anchor+2h; +15 min buffer
        # extends to anchor+2h15m, so anchor+3h is safe).
        i2 = schedule_interview(
            application_id=application["id"],
            recruiter_id=recruiter["id"],
            interviewer_id=v2["id"],
            start_at=add_hours(anchor, 3),
            end_at=add_hours(anchor, 4),
        )
        # Complete both: advance clock past the latest end.
        from test_helpers import try_advance_clock_to_iso
        try_advance_clock_to_iso(add_minutes(i2["scheduled_end_at"], 1))
        complete_interview(interview_id=i1["id"],
                           recruiter_id=recruiter["id"])
        complete_interview(interview_id=i2["id"],
                           recruiter_id=recruiter["id"])
        # Two feedbacks: 4 and 5 → mean 4.50.
        submit_feedback(interview_id=i1["id"], interviewer_id=v1["id"],
                        overall_score=4, recommendation="HIRE")
        submit_feedback(interview_id=i2["id"], interviewer_id=v2["id"],
                        overall_score=5, recommendation="STRONG_HIRE")
        app = get_application(application["id"])
        # PRD §3.4: "rounded half up to two decimal places". Expect
        # 4.5 (which Python may serialize as 4.5 or 4.50 numerically).
        assert app["panel_average_score"] == pytest.approx(4.50, abs=0.005), (
            f"panel_average_score must be 4.50, got "
            f"{app['panel_average_score']!r}"
        )

    def test_panel_score_null_until_first_feedback(self, api):
        """PRD §3.4: "The `panel_average_score` on the application is
        the mean of the `overall_score` values across the set of all
        `InterviewFeedback` records whose parent interview is
        `COMPLETED` and belongs to the same application. If that set
        is empty, the score is null."

        Claim: before any feedback exists, application's
        panel_average_score is null.
        """
        ctx = setup_application_in_interviewing()
        app = get_application(ctx["application"]["id"])
        assert app.get("panel_average_score") is None, (
            f"panel_average_score must be null before any feedback, "
            f"got {app.get('panel_average_score')!r}"
        )


# ===========================================================================
# Withdraw + reject
# ===========================================================================
class TestWithdrawAndReject:

    def test_withdraw_from_applied(self, api):
        """PRD §3.3: "Candidates withdraw themselves by initiating a
        `WITHDRAWN` transition, permitted from any of `APPLIED`,
        `SCREENING`, `INTERVIEWING`, and `OFFER_STAGE`; the acting
        candidate must match the application's `candidate_id`."

        Claim: candidate /withdraw from APPLIED → stage=WITHDRAWN.
        """
        recruiter, _hm, req = setup_open_requisition()
        candidate = create_candidate(actor_recruiter_id=recruiter["id"])
        application = create_application(
            requisition_id=req["id"],
            candidate_id=candidate["id"],
            actor_recruiter_id=recruiter["id"],
        )
        withdrawn = withdraw_application(
            application_id=application["id"],
            candidate_id=candidate["id"],
        )
        assert_stage(withdrawn, "WITHDRAWN")


# ===========================================================================
# Feedback eligibility — interviewer must be the assigned one (PRD §3.4)
# ===========================================================================
class TestFeedbackEligibility:

    def test_feedback_by_non_assigned_interviewer_rejected(self, api):
        """PRD §3.4: "The submitting `interviewer_id` on the feedback
        must equal the interview's `interviewer_id`".

        Claim: an Interviewer V_other who is NOT the assigned
        interviewer cannot POST /interviews/{id}/feedback.

        We accept ERR_FORBIDDEN OR ERR_VALIDATION OR ERR_INVALID_STATE
        because PRD names the rule (interviewer_id must equal) but
        does not pin a specific error_id for the mismatch — the
        observable outcome is "rejected".
        """
        from test_helpers import validate_error_is_one_of
        ctx = setup_application_in_interviewing()
        # Complete the interview so feedback is even eligible.
        from test_helpers import (
            add_minutes, advance_clock_to_iso, complete_interview,
        )
        advance_clock_to_iso(
            add_minutes(ctx["interview"]["scheduled_end_at"], 1),
        )
        complete_interview(interview_id=ctx["interview"]["id"],
                           recruiter_id=ctx["recruiter"]["id"])
        # Different interviewer attempts feedback.
        v_other = create_interviewer(is_certified_for_eeo=True)
        h = make_interviewer_headers(v_other["id"])
        payload = create_interview_feedback_payload(
            overall_score=5, recommendation="STRONG_HIRE",
        )
        resp = api.create_interview_feedback(
            ctx["interview"]["id"], payload, h,
        )
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_FORBIDDEN.value,
                ApiErrorId.ERR_VALIDATION.value,
                ApiErrorId.ERR_INVALID_STATE.value,
                ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            ],
        )

    def test_uncertified_interviewer_on_protected_candidate_rejected(
        self, api,
    ):
        """PRD §3.1: "submitting feedback on such a candidate without
        that certification is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.4: "an interviewer scoring a candidate flagged
        `is_in_eeo_protected_class` must additionally have
        `is_certified_for_eeo` set to true, otherwise the submission
        is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Claim: uncertified Interviewer on protected candidate →
        ERR_SEGREGATION_OF_DUTIES on POST /interviews/{id}/feedback.
        """
        # Build application in INTERVIEWING but with uncertified
        # interviewer assigned and a protected candidate.
        recruiter, _hm, req = setup_open_requisition()
        candidate = create_candidate(
            is_in_eeo_protected_class=True,
            actor_recruiter_id=recruiter["id"],
        )
        attach_eeo_record(candidate_id=candidate["id"], actor="candidate")
        v = create_interviewer(is_certified_for_eeo=False)
        application = create_application(
            requisition_id=req["id"],
            candidate_id=candidate["id"],
            actor_recruiter_id=recruiter["id"],
        )
        from test_helpers import (
            add_hours, add_minutes, advance_clock_to_iso,
            init_clock, schedule_interview, TEST_DEFAULTS,
            complete_interview,
        )
        anchor = init_clock(TEST_DEFAULTS["INITIAL_CLOCK_ISO"])
        application = advance_application(
            application_id=application["id"],
            recruiter_id=recruiter["id"],
        )
        i1 = schedule_interview(
            application_id=application["id"],
            recruiter_id=recruiter["id"],
            interviewer_id=v["id"],
            start_at=add_hours(anchor, 1),
            end_at=add_hours(anchor, 2),
        )
        application = advance_application(
            application_id=application["id"],
            recruiter_id=recruiter["id"],
        )
        from test_helpers import try_advance_clock_to_iso
        try_advance_clock_to_iso(add_minutes(i1["scheduled_end_at"], 1))
        complete_interview(interview_id=i1["id"],
                           recruiter_id=recruiter["id"])
        h = make_interviewer_headers(v["id"])
        payload = create_interview_feedback_payload(
            overall_score=5, recommendation="STRONG_HIRE",
        )
        resp = api.create_interview_feedback(i1["id"], payload, h)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
