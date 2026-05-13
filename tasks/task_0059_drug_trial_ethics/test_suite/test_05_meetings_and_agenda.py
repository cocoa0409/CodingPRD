"""Meetings, agenda items, publish, open, close, cancel.

PRD §3.3.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    SEC,
    add_agenda_item,
    advance_clock,
    api_client,
    assert_agenda_item,
    assert_meeting,
    create_application,
    create_member,
    create_meeting,
    iso_z,
    parse_iso,
    publish_agenda,
    seed_committee,
    setup_application_pending_review,
    setup_meeting_lead_time_cases,
    validate_error,
    validate_success,
)
from datetime import timedelta


# ===========================================================================
# Meeting scheduling — convener qualification (PRD §3.3)
# ===========================================================================
class TestMeetingScheduling:
    """PRD §3.3: 'The convener must be currently is_active and must
    hold the MEDICAL_EXPERT qualification; violations yield
    ERR_MEMBER_NOT_QUALIFIED with HTTP 422.'"""

    def test_convener_not_medical_expert_rejected(self, api):
        """PRD §3.3: 'The convener must be currently is_active and must
        hold the MEDICAL_EXPERT qualification; violations yield
        ERR_MEMBER_NOT_QUALIFIED with HTTP 422.'"""
        m = create_member(qualification="ETHICIST")
        res = api.create_meeting(
            {
                "meeting_type": "STANDARD",
                "scheduled_at": "2030-01-01T00:00:00.000Z",
                "convener_member_id": m["id"],
            },
            SEC,
        )
        validate_error(res, ApiErrorId.ERR_MEMBER_NOT_QUALIFIED.value)

    def test_medical_expert_convener_accepted(self, api):
        """PRD §3.3: 'the convener_member_id of the committee member
        who will chair the session. The convener must be currently
        is_active and must hold the MEDICAL_EXPERT qualification'."""
        m = create_member(qualification="MEDICAL_EXPERT")
        m_obj = create_meeting(
            convener_member_id=m["id"],
            scheduled_at="2030-01-01T00:00:00.000Z",
            meeting_type="STANDARD",
        )
        assert_meeting(m_obj)
        assert m_obj["status"] == "SCHEDULED", (
            f"PRD §3.3: 'The meeting begins life in SCHEDULED status'; "
            f"got {m_obj['status']!r}"
        )

    def test_meeting_lead_time_standard_is_168(self, api):
        """PRD §3.3: 'lead_time_hours field on a meeting is derived from
        meeting_type — 168 hours (which is 7 days) for a STANDARD
        meeting'."""
        m = create_member(qualification="MEDICAL_EXPERT")
        meeting = create_meeting(
            convener_member_id=m["id"],
            scheduled_at="2030-01-01T00:00:00.000Z",
            meeting_type="STANDARD",
        )
        assert meeting["lead_time_hours"] == 168, (
            f"PRD §3.3: '168 hours (which is 7 days) for a STANDARD "
            f"meeting'; got {meeting['lead_time_hours']!r}"
        )

    def test_meeting_lead_time_expedited_is_24(self, api):
        """PRD §3.3: '24 hours (which is 1 day) for an EXPEDITED
        meeting'."""
        m = create_member(qualification="MEDICAL_EXPERT")
        meeting = create_meeting(
            convener_member_id=m["id"],
            scheduled_at="2030-01-01T00:00:00.000Z",
            meeting_type="EXPEDITED",
        )
        assert meeting["lead_time_hours"] == 24, (
            f"PRD §3.3: '24 hours (which is 1 day) for an EXPEDITED "
            f"meeting'; got {meeting['lead_time_hours']!r}"
        )


# ===========================================================================
# Agenda creation (PRD §3.3)
# ===========================================================================
class TestAgendaItemCreation:
    """PRD §3.3: 'Every newly-added agenda item begins in DRAFT per-item
    status. At creation the item's pinned_submission_version,
    eligible_voter_count, and quorum_required are all null/unset; they
    are frozen only at publication.'"""

    def test_new_agenda_item_starts_in_draft(self, api):
        """PRD §3.3: 'Every newly-added agenda item begins in DRAFT
        per-item status.'"""
        m = create_member(qualification="MEDICAL_EXPERT")
        meeting = create_meeting(
            convener_member_id=m["id"],
            scheduled_at="2030-01-01T00:00:00.000Z",
            meeting_type="STANDARD",
        )
        app, _ = setup_application_pending_review()
        item = add_agenda_item(meeting["id"], app["id"],
                               review_kind="INITIAL_REVIEW")
        assert_agenda_item(item)
        assert item["status"] == "DRAFT", (
            f"PRD §3.3: 'every newly-added agenda item begins in DRAFT'; "
            f"got {item['status']!r}"
        )


# ===========================================================================
# Publish agenda (PRD §3.3) — lead time, empty agenda, freeze
# ===========================================================================
class TestPublishAgenda:
    """PRD §3.3: 'Publishing the agenda is the moment the meeting's
    review materials become committee-visible. The transition from
    SCHEDULED to AGENDA_PUBLISHED is the Secretary's action and is
    gated by two preconditions: at least one AgendaItem must belong to
    the meeting, and the time gap between the meeting's scheduled_at
    and the current logical clock must be at least the meeting's
    required lead-time hours.'"""

    def test_publish_empty_agenda_rejected(self, api):
        """PRD §3.3: 'at least one AgendaItem must belong to the
        meeting'."""
        m = create_member(qualification="MEDICAL_EXPERT")
        advance_clock("2026-06-01T00:00:00.000Z")
        meeting = create_meeting(
            convener_member_id=m["id"],
            scheduled_at="2026-06-15T00:00:00.000Z",
            meeting_type="STANDARD",
        )
        res = api.publish_agenda(meeting["id"], SEC)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_publish_standard_at_exact_168h_accepted(self, api):
        """PRD §3.3: 'compared as a strict inequality: the request is
        rejected with ERR_AGENDA_LEAD_TIME_VIOLATION only when the
        seconds remaining until the meeting are strictly less than the
        required hours multiplied by 3600; a meeting scheduled exactly
        the required-hours interval away from now is allowed.'"""
        bundle = setup_meeting_lead_time_cases()
        res = api.publish_agenda(bundle["meet_std_ok"]["id"], SEC)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "AGENDA_PUBLISHED"

    def test_publish_standard_under_168h_rejected(self, api):
        """PRD §3.3: 'rejected with ERR_AGENDA_LEAD_TIME_VIOLATION only
        when the seconds remaining until the meeting are strictly less
        than the required hours multiplied by 3600'."""
        bundle = setup_meeting_lead_time_cases()
        res = api.publish_agenda(bundle["meet_std_fail"]["id"], SEC)
        validate_error(res, ApiErrorId.ERR_AGENDA_LEAD_TIME_VIOLATION.value)

    def test_publish_freezes_pinned_submission_version(self, api):
        """PRD §3.3: 'On success the meeting's agenda_published_at is
        set to the current clock time, every child AgendaItem moves
        from DRAFT to PUBLISHED, and for each item the
        pinned_submission_version is taken from the application's
        current_submission_version'."""
        advance_clock("2026-06-01T00:00:00.000Z")
        m = create_member(qualification="MEDICAL_EXPERT")
        app, _ = setup_application_pending_review()
        meeting = create_meeting(
            convener_member_id=m["id"],
            scheduled_at="2026-06-08T00:00:00.000Z",
            meeting_type="STANDARD",
        )
        item = add_agenda_item(meeting["id"], app["id"],
                               review_kind="INITIAL_REVIEW")
        publish_agenda(meeting["id"])
        item_after = api_client.get_agenda_item(item["id"], SEC).json()["data"]
        assert item_after["status"] == "PUBLISHED", (
            f"PRD §3.3: 'every child AgendaItem moves from DRAFT to "
            f"PUBLISHED'; got {item_after['status']!r}"
        )
        # current_submission_version is 1 after one submission upload
        assert item_after["pinned_submission_version"] == 1, (
            f"PRD §3.3: 'pinned_submission_version is taken from the "
            f"application's current_submission_version'; got "
            f"{item_after.get('pinned_submission_version')!r}"
        )


# ===========================================================================
# Cancel SCHEDULED meeting (PRD §3.3)
# ===========================================================================
class TestCancelMeeting:
    """PRD §3.3: 'A meeting still in SCHEDULED status — that is, with no
    agenda yet published — can be cancelled outright, which moves the
    meeting to CANCELLED and cascade-deletes every child agenda item.
    After publication, cancellation is not available.'"""

    def test_cancel_scheduled_meeting_returns_204(self, api):
        """PRD §4: 'the cancellation of a SCHEDULED meeting returns
        HTTP 204.'"""
        m = create_member(qualification="MEDICAL_EXPERT")
        meeting = create_meeting(
            convener_member_id=m["id"],
            scheduled_at="2030-01-01T00:00:00.000Z",
            meeting_type="STANDARD",
        )
        res = api.cancel_meeting(meeting["id"], SEC)
        assert res.status_code == 204, (
            f"PRD §4: 'the cancellation of a SCHEDULED meeting returns "
            f"HTTP 204'; got {res.status_code}"
        )

    def test_cancel_after_publication_rejected(self, api):
        """PRD §3.3: 'After publication, cancellation is not available.'"""
        advance_clock("2026-06-01T00:00:00.000Z")
        m = create_member(qualification="MEDICAL_EXPERT")
        app, _ = setup_application_pending_review()
        meeting = create_meeting(
            convener_member_id=m["id"],
            scheduled_at="2026-06-08T00:00:00.000Z",
            meeting_type="STANDARD",
        )
        add_agenda_item(meeting["id"], app["id"])
        publish_agenda(meeting["id"])
        res = api.cancel_meeting(meeting["id"], SEC)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
