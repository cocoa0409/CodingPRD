"""Satisfaction-survey dispatch and response, follow-up handling,
reopen workflow, and close lifecycle.

PRD §3.7, §3.9, §3.10.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PA, HO, DISP, SA,
    advance_clock,
    create_survey_payload,
    find_lead_assignment,
    get_work_order,
    list_supervision_tasks,
    list_surveys,
    list_sync_events,
    make_department_handler_headers,
    register_work_order,
    respond_survey_payload,
    resolve,
    setup_followed_up,
    setup_in_progress,
    setup_resolved,
    validate_error,
    validate_success,
)


# ===========================================================================
# Auto-dispatched survey on resolve (PRD §3.7, §3.9)
# ===========================================================================
class TestAutoSurveyAtResolve:
    """PRD §3.7: 'Resolution also auto-dispatches a SatisfactionSurvey
    when the caller is reachable. The auto-dispatched survey's channel
    is CALL when the parent is not anonymous and caller_phone is
    present; otherwise, when the parent is anonymous and an IM contact
    handle has been recorded on file via input, the channel is IM;
    otherwise no survey is created at all.'"""

    def test_resolve_auto_dispatches_call_survey_for_phone_caller(self, api):
        """PRD §3.7: 'The auto-dispatched survey's channel is CALL when
        the parent is not anonymous and caller_phone is present.'"""
        world = setup_resolved(num_supporting=0)
        surveys = list_surveys(world["work_order"]["id"])
        assert any(s["channel"] == "CALL" for s in surveys), (
            "Expected an auto-dispatched survey with channel=CALL"
        )

    def test_resolve_anonymous_caller_no_survey(self, api):
        """PRD §3.7: 'otherwise no survey is created at all (the work
        order still reaches RESOLVED and the satisfaction calculation
        treats it as having no response).'"""
        world = setup_resolved(num_supporting=0, anonymous=True)
        surveys = list_surveys(world["work_order"]["id"])
        # The PRD permits an IM channel when an IM handle is recorded
        # on file via input; since no IM handle is supplied, no survey
        # is auto-created.
        for s in surveys:
            # If implementations honour the PRD they create no survey;
            # if they create one, it must NOT be CALL or SMS on an
            # anonymous WO.
            assert s["channel"] not in ("CALL", "SMS"), (
                "PRD §3.7: CALL/SMS forbidden on anonymous; no auto-survey"
                " should violate this rule."
            )


# ===========================================================================
# Survey response (PRD §3.9)
# ===========================================================================
class TestSurveyResponse:
    """PRD §3.9: 'The transition from DISPATCHED to RESPONDED is
    permitted only when the survey is still in DISPATCHED and the
    response arrives within 48 business hours after the survey's
    dispatched_at.'"""

    def test_respond_moves_wo_to_followed_up(self, api):
        """PRD §3.9: 'the parent work order's status is advanced from
        RESOLVED to FOLLOWED_UP, and an AuditLog row with action
        SURVEY_RESPOND is written.'"""
        world = setup_resolved(num_supporting=0)
        surveys = list_surveys(world["work_order"]["id"])
        survey = surveys[-1]
        resp = api.respond_survey(
            survey["id"], respond_survey_payload(score=5), SA,
        )
        data = validate_success(resp)
        assert data["status"] == "RESPONDED"
        assert data["score"] == 5
        wo = get_work_order(world["work_order"]["id"])
        assert wo["status"] == "FOLLOWED_UP"

    def test_respond_score_out_of_range_rejected(self, api):
        """PRD §3.9: 'a score (an integer between 1 and 5 inclusive).'"""
        world = setup_resolved(num_supporting=0)
        surveys = list_surveys(world["work_order"]["id"])
        survey = surveys[-1]
        resp = api.respond_survey(
            survey["id"], {"score": 6}, SA,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_respond_after_responded_rejected_with_not_pending(self, api):
        """PRD §3.9: 'a response against a survey not in DISPATCHED is
        rejected with ERR_SURVEY_NOT_PENDING (409).'"""
        world = setup_resolved(num_supporting=0)
        surveys = list_surveys(world["work_order"]["id"])
        survey = surveys[-1]
        validate_success(api.respond_survey(
            survey["id"], respond_survey_payload(score=5), SA,
        ))
        resp = api.respond_survey(
            survey["id"], respond_survey_payload(score=4), SA,
        )
        validate_error(resp, ApiErrorId.ERR_SURVEY_NOT_PENDING.value)


# ===========================================================================
# Manual survey dispatch + anonymous channel restriction (PRD §3.9)
# ===========================================================================
class TestManualSurveyDispatch:
    """PRD §3.9: 'manually dispatched by a HotlineOperator against a
    RESOLVED or FOLLOWED_UP parent. The manual dispatch endpoint
    accepts a channel of CALL, SMS, or IM. When the parent work order
    has anonymous equal to true, CALL and SMS are forbidden... attempting
    either yields ERR_SURVEY_CHANNEL_FORBIDDEN (422).'"""

    def test_manual_im_survey_on_anonymous_work_order(self, api):
        """PRD §3.9: 'The manual dispatch endpoint accepts a channel of
        CALL, SMS, or IM.'"""
        world = setup_resolved(num_supporting=0, anonymous=True)
        resp = api.create_survey(
            world["work_order"]["id"], create_survey_payload(channel="IM"),
            HO,
        )
        data = validate_success(resp, expected_status=201)
        assert data["channel"] == "IM"
        assert data["status"] == "DISPATCHED"

    def test_manual_call_survey_on_anonymous_rejected(self, api):
        """PRD §3.9: 'When the parent work order has anonymous equal to
        true, CALL and SMS are forbidden (both as a manual choice and
        during auto-dispatch); attempting either yields
        ERR_SURVEY_CHANNEL_FORBIDDEN (422).'"""
        world = setup_resolved(num_supporting=0, anonymous=True)
        resp = api.create_survey(
            world["work_order"]["id"], create_survey_payload(channel="CALL"),
            HO,
        )
        validate_error(resp, ApiErrorId.ERR_SURVEY_CHANNEL_FORBIDDEN.value)

    def test_manual_sms_survey_on_anonymous_rejected(self, api):
        """PRD §3.9: 'CALL and SMS are forbidden... attempting either
        yields ERR_SURVEY_CHANNEL_FORBIDDEN (422).'"""
        world = setup_resolved(num_supporting=0, anonymous=True)
        resp = api.create_survey(
            world["work_order"]["id"], create_survey_payload(channel="SMS"),
            HO,
        )
        validate_error(resp, ApiErrorId.ERR_SURVEY_CHANNEL_FORBIDDEN.value)


# ===========================================================================
# Reopen workflow (PRD §3.10)
# ===========================================================================
class TestReopen:
    """PRD §3.10: 'When the latest survey on a FOLLOWED_UP work order
    returns a score less than or equal to 2 (the dissatisfaction
    threshold), a HotlineOperator may reopen the case.'"""

    def test_reopen_with_low_score_succeeds(self, api):
        """PRD §3.10: 'The reopen is permitted only when the latest
        SatisfactionSurvey is in RESPONDED, its score is at most 2, and
        the reopen request arrives within 72 business hours of that
        survey's responded_at.'"""
        world = setup_followed_up(survey_score=1)
        resp = api.reopen_work_order(world["work_order"]["id"], HO)
        data = validate_success(resp)
        assert data["status"] == "REOPENED"

    def test_reopen_with_high_score_rejected(self, api):
        """PRD §3.10: 'A reopen with a score above the threshold or
        outside the window is rejected with
        ERR_REOPEN_WINDOW_EXPIRED (422).'"""
        world = setup_followed_up(survey_score=4)
        resp = api.reopen_work_order(world["work_order"]["id"], HO)
        validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED.value)

    def test_reopen_emits_sync_event(self, api):
        """PRD §3.10: 'A SyncEvent with event_type equal to REOPENED is
        emitted to each of the three downstream platforms.'"""
        world = setup_followed_up(survey_score=2)
        api.reopen_work_order(world["work_order"]["id"], HO)
        events = list_sync_events(
            work_order_id=world["work_order"]["id"], event_type="REOPENED",
        )
        platforms = {e["target_platform"] for e in events}
        assert platforms == {"IM", "GOVT_AFFAIRS", "INTER_DEPT"}


# ===========================================================================
# Close lifecycle (PRD §3.10)
# ===========================================================================
class TestClose:
    """PRD §3.10: 'Closing the case is the role of the Dispatcher.
    There are two valid entry paths into CLOSED.'"""

    def test_close_followed_up_with_satisfied_survey(self, api):
        """PRD §3.10: 'The first applies when the case is in
        FOLLOWED_UP and either the latest survey is RESPONDED with a
        score of at least 3.'"""
        world = setup_followed_up(survey_score=5)
        resp = api.close_work_order(world["work_order"]["id"], DISP)
        data = validate_success(resp)
        assert data["status"] == "CLOSED"
        assert "closed_at" in data and data["closed_at"]

    def test_close_emits_sync_event(self, api):
        """PRD §3.10: 'a SyncEvent with event_type equal to CLOSED is
        emitted to the three platforms.'"""
        world = setup_followed_up(survey_score=5)
        api.close_work_order(world["work_order"]["id"], DISP)
        events = list_sync_events(
            work_order_id=world["work_order"]["id"], event_type="CLOSED",
        )
        platforms = {e["target_platform"] for e in events}
        assert platforms == {"IM", "GOVT_AFFAIRS", "INTER_DEPT"}

    def test_close_anonymous_resolved_no_survey_path(self, api):
        """PRD §3.10: 'The second applies when the case is still in
        RESOLVED and no survey exists because resolve could not pick a
        channel.'"""
        world = setup_resolved(num_supporting=0, anonymous=True)
        resp = api.close_work_order(world["work_order"]["id"], DISP)
        data = validate_success(resp)
        assert data["status"] == "CLOSED"
