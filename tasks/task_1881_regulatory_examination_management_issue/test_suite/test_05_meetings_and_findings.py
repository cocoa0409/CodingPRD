"""Examiner meetings, informal findings, and the examination transitions that
depend on them (PRD §3.2, §3.4)."""
from test_helpers import (
    RAM,
    ApiErrorId,
    assert_examiner_meeting,
    create_examiner_meeting_payload,
    create_informal_finding_payload,
    create_meeting,
    setup_exam_fieldwork,
    setup_exam_first_day_issued,
    validate_error,
    validate_success,
)


class TestMeetingDateCollision:
    def test_same_calendar_date_as_finalized_meeting_conflicts(self, api):
        """PRD §3.4: "One calendar rule applies at logging time: two meetings on
        the same examination may not share a UTC calendar date once one of them
        is `FINALIZED`. Unlike the interval-overlap arithmetic of exam
        scheduling, this is a point collision at the date grain — the same
        calendar day is a conflict regardless of hour — and a collision is
        rejected with `ERR_MEETING_DATE_CONFLICT`."

        A finalized meeting at 2026-07-08T09:00 collides with a new meeting at
        2026-07-08T15:00 — the hour is irrelevant at the date grain.

        Design: Difficulty/resource_temporal_overlap/meeting_point_collision_same_calendar_date
        """
        ctx = setup_exam_fieldwork()
        meeting_a = create_meeting(ctx["exam"]["id"],
                                   meeting_date="2026-07-08T09:00:00Z")
        validate_success(api.finalize_examiner_meeting(meeting_a["id"], RAM))
        resp = api.create_examiner_meeting(
            create_examiner_meeting_payload(
                ctx["exam"]["id"], meeting_date="2026-07-08T15:00:00Z",
                attendees=["Examiner B", "Officer C"], minutes_summary="second"),
            RAM)
        validate_error(resp, ApiErrorId.ERR_MEETING_DATE_CONFLICT)

    def test_different_calendar_date_accepted(self, api):
        """PRD §3.4: "One calendar rule applies at logging time: two meetings on
        the same examination may not share a UTC calendar date once one of them
        is `FINALIZED`."

        2026-07-09 does not share the finalized meeting's 2026-07-08 date.

        Design: Difficulty/resource_temporal_overlap/meeting_point_collision_same_calendar_date
        """
        ctx = setup_exam_fieldwork()
        meeting_a = create_meeting(ctx["exam"]["id"],
                                   meeting_date="2026-07-08T09:00:00Z")
        validate_success(api.finalize_examiner_meeting(meeting_a["id"], RAM))
        resp = api.create_examiner_meeting(
            create_examiner_meeting_payload(
                ctx["exam"]["id"], meeting_date="2026-07-09T09:00:00Z"),
            RAM)
        data = validate_success(resp, 201)
        assert_examiner_meeting(data)

    def test_empty_attendees_array_rejected(self, api):
        """PRD §3.4: "the `attendees` array — which must include at least one
        examiner and at least one bank officer, else `ERR_INVALID_REQUEST`"

        Design: Difficulty/boundary_precision_check/empty_attendees_and_adjacent_exam_interval
        """
        ctx = setup_exam_first_day_issued()
        resp = api.create_examiner_meeting(
            create_examiner_meeting_payload(
                ctx["exam"]["id"], meeting_date="2026-07-07T10:00:00Z",
                attendees=[]),
            RAM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestMeetingLifecycle:
    def test_meeting_finalize_valid_transition(self, api):
        """PRD §3.4: "Finalizing the minutes is the manager's seal: the meeting
        must be `DRAFT`, its `minutes_summary` must be non-empty, and the
        examination must be in `FIELDWORK` or `FINDINGS_DELIVERED`.
        Finalization moves the meeting `DRAFT` → `FINALIZED`, bumps its
        `version`, and renders it immutable thereafter."

        Design: Corner/state_machines/meeting_finalize_valid_transition
        """
        ctx = setup_exam_fieldwork()
        meeting = create_meeting(ctx["exam"]["id"])
        assert meeting["status"] == "DRAFT"
        resp = api.finalize_examiner_meeting(meeting["id"], RAM)
        data = validate_success(resp, 200)
        assert data["status"] == "FINALIZED"

    def test_informal_findings_require_finalized_meeting(self, api):
        """PRD §3.4: "Only a `FINALIZED` meeting may carry informal findings;
        capturing one against a still-`DRAFT` meeting is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/informal_findings_require_finalized_meeting
        """
        ctx = setup_exam_fieldwork()
        meeting = create_meeting(ctx["exam"]["id"])
        resp = api.create_informal_finding(
            meeting["id"],
            create_informal_finding_payload(finding_text="t", severity_hint="HIGH"),
            RAM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_deliver_findings_requires_finalized_meeting(self, api):
        """PRD §3.4: "When at least one meeting has been finalized, delivering
        findings moves the examination `FIELDWORK` → `FINDINGS_DELIVERED`."
        PRD §2.9: "The target resource's current state permits the requested
        transition — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/deliver_findings_requires_finalized_meeting
        """
        ctx = setup_exam_fieldwork()
        create_meeting(ctx["exam"]["id"])  # left DRAFT
        resp = api.deliver_findings(ctx["exam"]["id"], RAM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCancelOnlyFromScheduled:
    def test_cancel_from_first_day_issued_rejected(self, api):
        """PRD §3.2: "Should the examination be called off before work begins,
        the manager may cancel it from `SCHEDULED` to `CANCELLED` by supplying a
        non-empty `cancelled_reason`; the reason is immutable once recorded, and
        `CANCELLED` is terminal."
        PRD §2.9: "The target resource's current state permits the requested
        transition — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/exam_cancel_from_scheduled_only
        """
        ctx = setup_exam_first_day_issued()
        resp = api.cancel_examination(
            ctx["exam"]["id"], {"cancelled_reason": "bad"}, RAM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
