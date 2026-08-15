"""Notification cadence and dispatch, the federal audit trail, and access control."""
import pytest

from test_helpers import (
    AID_ADMIN, AID_OFFICER, AUDITOR, NO_AUTH_HEADERS, REGISTRAR, api_client,
    close_and_evaluate, create_posted_enrollment, create_program, create_student,
    create_term, dispatch_notifications, get_student, list_audit_events,
    list_notifications, make_student_headers, program_payload, set_clock,
    setup_suspended_student, setup_warned_student, student_version, submit_appeal,
    validate_error, validate_paginated, validate_success,
)


def test_clock_set_backwards_rejected(api):
    """PRD section 2.7: "At server startup the logical clock reads exactly
    `2026-08-01T00:00:00Z`."
    PRD section 2.7: "The clock moves only forward: a target earlier than the current
    logical time is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/clock_set_backwards_rejected
    """
    res = api.set_clock({"to_iso8601": "2026-07-01T00:00:00Z"}, AID_ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")

    forward = validate_success(
        api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, AID_ADMIN), 200)
    assert forward["current_utc"].startswith("2026-09-01T00:00:00")


def test_reminder_cadence_schedule_send_and_cancel(api):
    """PRD section 3.8: "When an evaluation assigns `SUSPENSION` and that differs from
    the prior standing — and also, as the lone exception, when a continued `SUSPENSION`
    is re-affirmed — the office queues a `STANDING_CHANGE` notice at `evaluated_at` and
    one `APPEAL_DEADLINE_REMINDER` per entry in the program's `reminder_offset_days`,
    each scheduled at `evaluated_at` plus its offset in days."
    PRD section 3.8: "Every `QUEUED` row whose scheduled time has arrived —
    `scheduled_at` on or before the current logical time — is sent: its status becomes
    `SENT`, `sent_at` is set to the current time, and `NOTIFICATION_SENT` is audited.
    The same sweep cancels obviated deadline reminders: any `QUEUED`
    `APPEAL_DEADLINE_REMINDER` whose student now holds an appeal in `SUBMITTED`,
    `UNDER_REVIEW`, `MORE_INFO_REQUESTED`, or `APPROVED`, or whose standing is no
    longer `SUSPENSION`, becomes `CANCELLED` with `NOTIFICATION_CANCELLED` audited."

    Design: Corner/calculations/reminder_cadence_schedule_send_and_cancel
    """
    world = setup_suspended_student()
    student_id = world["student"]["id"]

    # At the startup clock (2026-08-01) only the two standing-change notices are due;
    # the reminders are scheduled for +7d (08-08) and +13d (08-14).
    first = dispatch_notifications()
    assert first["sent_count"] == 2
    assert first["cancelled_count"] == 0

    set_clock("2026-08-08T00:00:00Z")
    second = dispatch_notifications()
    assert second["sent_count"] == 1, "the +7d reminder is now due"
    assert second["cancelled_count"] == 0

    submit_appeal(student_id, world["evaluation"]["id"], student_version(student_id))

    set_clock("2026-08-14T00:00:00Z")
    third = dispatch_notifications()
    assert third["sent_count"] == 0
    assert third["cancelled_count"] == 1, (
        "the +13d reminder is obviated by the student's SUBMITTED appeal")

    cancelled = list_notifications(
        {"student_id": student_id, "kind": "APPEAL_DEADLINE_REMINDER",
         "status": "CANCELLED"})
    assert len(cancelled) == 1
    sent = list_notifications(
        {"student_id": student_id, "kind": "APPEAL_DEADLINE_REMINDER",
         "status": "SENT"})
    assert len(sent) == 1
    assert sent[0]["sent_at"].startswith("2026-08-08T00:00:00")


def test_dispatch_idempotent_second_run(api):
    """PRD section 3.8: "Every `QUEUED` row whose scheduled time has arrived —
    `scheduled_at` on or before the current logical time — is sent: its status becomes
    `SENT`, `sent_at` is set to the current time, and `NOTIFICATION_SENT` is audited."
    PRD section 3.8: "The sweep responds with the two tallies `sent_count` and
    `cancelled_count`."

    Design: Corner/endpoints/dispatch_idempotent_second_run
    """
    world = setup_warned_student()
    student_id = world["student"]["id"]

    first = dispatch_notifications()
    assert first["sent_count"] == 1
    assert first["cancelled_count"] == 0

    queued_before = list_notifications({"student_id": student_id})
    assert len(queued_before) == 1 and queued_before[0]["status"] == "SENT"
    sent_at = queued_before[0]["sent_at"]

    second = dispatch_notifications()
    assert second["sent_count"] == 0
    assert second["cancelled_count"] == 0

    after = list_notifications({"student_id": student_id})
    assert len(after) == 1
    assert after[0]["status"] == "SENT"
    assert after[0]["sent_at"] == sent_at, "a no-op sweep must not re-send"


def test_notifications_filter_by_student_and_status(api):
    """PRD section 3.8: "each queueing appends a `NOTIFICATION_QUEUED` audit, and the
    notification list accepts `student_id`, `kind`, and `status` filters."
    PRD section 3.8: "the office queues a `STANDING_CHANGE` notice at `evaluated_at`
    and one `APPEAL_DEADLINE_REMINDER` per entry in the program's
    `reminder_offset_days`, each scheduled at `evaluated_at` plus its offset in days."

    Design: Corner/complexity_layers/notifications_filter_by_student_and_status
    """
    world = setup_suspended_student()
    student_id = world["student"]["id"]

    _rows, meta = validate_paginated(api.list_notifications(
        AID_OFFICER, params={"student_id": student_id, "status": "QUEUED",
                             "limit": 100}))
    assert meta["total_count"] == 4, (
        "T1 standing change + T2 standing change + two appeal-deadline reminders")

    reminders = list_notifications(
        {"student_id": student_id, "kind": "APPEAL_DEADLINE_REMINDER"})
    assert len(reminders) == 2
    assert {r["scheduled_at"][:19] for r in reminders} == {
        "2026-08-08T00:00:00", "2026-08-14T00:00:00"}

    reinstatements = list_notifications(
        {"student_id": student_id, "kind": "REINSTATEMENT"})
    assert reinstatements == []


def test_audit_events_filter_by_entity_type(api):
    """PRD section 2.10: "Read access to the trail is restricted to the `Auditor` and
    `AidAdministrator` roles; the audit-event list accepts `student_id`,
    `entity_type`, `entity_id`, and `action` filters alongside the standard pagination
    parameters."
    PRD section 2.10: "the affected `student_id` for federal-review scoping (null on
    `Program` and `Term` rows)"

    Design: Corner/endpoints/audit_events_filter_by_entity_type
    """
    world = setup_warned_student()
    student_id = world["student"]["id"]

    evaluation_events = list_audit_events(
        {"student_id": student_id, "entity_type": "SapEvaluation"})
    assert len(evaluation_events) == 1
    assert evaluation_events[0]["action"] == "EVALUATION_POSTED"

    term_events = list_audit_events({"entity_type": "Term"})
    assert {e["action"] for e in term_events} == {
        "TERM_CREATED", "TERM_GRADING_CLOSED", "TERM_EVALUATED"}
    assert all(e["student_id"] is None for e in term_events)

    student_events = list_audit_events({"student_id": student_id})
    assert {e["action"] for e in student_events} == {
        "STUDENT_CREATED", "ENROLLMENT_CREATED", "ENROLLMENT_POSTED",
        "EVALUATION_POSTED", "STANDING_CHANGED", "NOTIFICATION_QUEUED"}
    assert len(student_events) == 6


def test_error_envelope_shape_on_not_found(api):
    """PRD section 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD section 2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD section 2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/error_envelope_shape_on_not_found
    """
    from test_helpers import NON_EXISTENT_UUID

    res = api.get_appeal(NON_EXISTENT_UUID, AID_OFFICER)
    error = validate_error(res, "ERR_NOT_FOUND")
    assert res.status_code == 404
    assert isinstance(error["message"], str) and error["message"].strip()
    body = res.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD section 2.1: "A request missing either header, or carrying a role the
    system does not declare, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_students(NO_AUTH_HEADERS)
    validate_error(res, "ERR_UNAUTHENTICATED")
    assert res.json()["response_type"] == "error"


def test_auditor_is_read_only(api):
    """PRD section 2.1: "`Auditor` is a read-only federal reviewer with access to
    every resource including the audit trail."
    PRD section 2.1: "When the role is recognized but not permitted for the target
    endpoint, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/auditor_is_read_only
    """
    res = api.create_program(
        program_payload(code="BS-AU", name="AuditorWrite", required_credits=120),
        AUDITOR)
    validate_error(res, "ERR_UNAUTHORIZED")

    read = api.list_audit_events(AUDITOR)
    rows, meta = validate_paginated(read)
    assert read.json()["response_type"] == "array"
    assert meta["total_count"] == 0
    assert rows == []


def test_student_cannot_read_other_student_record(api):
    """PRD section 2.1: "A student may therefore read only their own student record,
    their own advising preview, and their own appeals, plans, checkpoints,
    evaluations, notifications, and enrollments; list endpoints force the caller's
    `student_id` as a filter when the caller's role is `Student`, and any single-row
    read, appeal submission, or resubmission that targets another student's row is
    rejected with `ERR_OWNERSHIP_VIOLATION`."

    Design: Corner/rbac/student_cannot_read_other_student_record
    """
    program = create_program(code="BS-OWN", name="Ownership", required_credits=120)
    mine = create_student(program["id"], student_number="S-5003", full_name="Mine")
    other = create_student(program["id"], student_number="S-5004",
                           full_name="Not Mine")

    res = api.get_student(other["id"], make_student_headers(mine["id"]))
    validate_error(res, "ERR_OWNERSHIP_VIOLATION")

    own = validate_success(
        api.get_student(mine["id"], make_student_headers(mine["id"])), 200)
    assert own["full_name"] == "Mine"
