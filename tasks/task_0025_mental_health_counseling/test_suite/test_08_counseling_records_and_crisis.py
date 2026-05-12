"""Counseling records (encrypted) and the crisis incident workflow
(PRD §3.6, §3.7)."""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    assert_counseling_record,
    assert_crisis_incident,
    bring_counselor_to_active,
    confirm_appointment,
    create_appointment_in_hold,
    create_client,
    create_counseling_record,
    create_counseling_record_payload,
    create_crisis_incident_payload,
    create_slot,
    DEFAULT_T0,
    export_counseling_record_payload,
    get_appointment,
    handover_crisis,
    list_audit_log,
    make_admin_headers,
    make_client_headers,
    make_counselor_headers,
    make_crisis_responder_headers,
    notify_emergency,
    setup_confirmed_appointment,
    shift,
    start_appointment,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def _walk_appointment_to_completed(*, base_t0: str = DEFAULT_T0):
    """Tiny helper: build a completed appointment and return
    (counselor, client, completed_appt).
    """
    advance_clock(base_t0)
    counselor = bring_counselor_to_active()
    client = create_client()
    intake_start = shift(base_t0, hours=200)
    slot = create_slot(counselor=counselor, start_at=intake_start)
    appt = create_appointment_in_hold(
        counselor=counselor, client=client, slot=slot,
        appointment_type="INTAKE", payment_mode="PAY_PER_SESSION",
    )
    confirmed = confirm_appointment(client, appt)
    advance_clock(shift(intake_start, minutes=-4))
    started = start_appointment(counselor, confirmed)
    return counselor, client, started


def _walk_to_completed_with_record(*, base_t0: str = DEFAULT_T0):
    """Helper: walk to COMPLETED appointment with a counseling record."""
    counselor, client, started = _walk_appointment_to_completed(base_t0=base_t0)
    record = create_counseling_record(
        counselor=counselor, appointment=started,
        encrypted_note_blob="aW50YWtlLW5vdGUtY2lwaGVydGV4dA==",
    )
    res = api_client.complete_appointment(
        started["id"], make_counselor_headers(counselor["id"]),
    )
    completed = validate_success(res, expected_status=200)
    return counselor, client, completed, record


class TestCounselingRecordCreate:
    def test_create_record_after_completion(self, api):
        """PRD §3.6: "After a session completes, the counselor writes a
        single counseling record for that session. ... On success the
        record is persisted with `redaction_status` of `ACTIVE`,
        `retention_expires_at` of `created_at` plus seven years, and
        `last_accessed_at` of null."
        """
        counselor, client, started = _walk_appointment_to_completed()
        record = create_counseling_record(
            counselor=counselor, appointment=started,
            encrypted_note_blob="bm90ZS10ZXh0LWNpcGhlcg==",
        )
        assert_counseling_record(record)
        assert record["redaction_status"] == "ACTIVE"
        assert record["last_accessed_at"] is None

    def test_duplicate_record_rejected(self, api):
        """PRD §3.6: "the unique constraint surfaces a duplicate as
        `ERR_RECORD_ALREADY_EXISTS`."
        """
        counselor, client, started = _walk_appointment_to_completed()
        create_counseling_record(
            counselor=counselor, appointment=started,
            encrypted_note_blob="Zmlyc3QtY2lwaGVy",
        )
        res = api.create_counseling_record(
            create_counseling_record_payload(
                appointment_id=started["id"],
                encrypted_note_blob="c2Vjb25kLWNpcGhlcg==",
            ),
            make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_RECORD_ALREADY_EXISTS", expected_status=409)


class TestRiskKeywordAutoRaise:
    def test_keyword_match_auto_creates_crisis_and_returns_422(self, api):
        """PRD §3.6: "When any keyword matches and `crisis_acknowledged` is
        not `true`, the platform refuses the write: it auto-creates a
        CrisisIncident with `detection_source` set to `KEYWORD_DETECTOR`,
        `status` set to `DETECTED`, `appointment_id` and `client_id`
        mirrored from the appointment, and surfaces the new incident's `id`
        in the rejection response, returning HTTP 422 with `error_id` of
        `ERR_CRISIS_AUTO_RAISED`."
        """
        counselor, client, started = _walk_appointment_to_completed()
        # Encrypt-blob naming notwithstanding, PRD §3.6 says "a risk-keyword
        # scan over the supplied note." Tests pass a base64-encoded keyword
        # string so the implementer's keyword scan can hit it.
        # The keyword set is case-insensitive {suicide, self-harm, kill
        # myself, end it}.
        import base64
        note_with_keyword = base64.b64encode(
            b"Client mentioned suicide ideation"
        ).decode("ascii")
        res = api.create_counseling_record(
            create_counseling_record_payload(
                appointment_id=started["id"],
                encrypted_note_blob=note_with_keyword,
            ),
            make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_CRISIS_AUTO_RAISED", expected_status=422)

    def test_with_crisis_acknowledged_true_succeeds(self, api):
        """PRD §3.6: "The counselor must then re-submit the same record
        with `crisis_acknowledged` set to `true` to commit the note."
        """
        counselor, client, started = _walk_appointment_to_completed()
        import base64
        note_with_keyword = base64.b64encode(
            b"Client mentioned end it; counselor escalated"
        ).decode("ascii")
        res = api.create_counseling_record(
            create_counseling_record_payload(
                appointment_id=started["id"],
                encrypted_note_blob=note_with_keyword,
                crisis_acknowledged=True,
            ),
            make_counselor_headers(counselor["id"]),
        )
        record = validate_success(res, expected_status=201)
        assert record["redaction_status"] == "ACTIVE"


class TestCounselingRecordRead:
    def test_read_refreshes_last_accessed_at_and_audit_log(self, api):
        """PRD §3.6: "Each authorised read refreshes `last_accessed_at` to
        current time and appends an `AuditLogEntry` with action `RECORD_READ`."
        """
        counselor, client, completed, record = _walk_to_completed_with_record()
        res = api.get_counseling_record(
            record["id"], make_counselor_headers(counselor["id"]),
        )
        body = validate_success(res, expected_status=200)
        assert body["last_accessed_at"] is not None
        # Audit log entry must exist.
        entries = list_audit_log(action="RECORD_READ", target_id=record["id"])
        assert any(e["action"] == "RECORD_READ"
                   and e["target_id"] == record["id"] for e in entries)


class TestCounselingRecordExport:
    def test_export_without_consent_rejected(self, api):
        """PRD §3.6: "The export request body MUST carry `export_consent`
        set to `true`; absence of the field, or a value of `false`, is
        rejected with `ERR_EXPORT_CONSENT_MISSING`."
        """
        counselor, client, completed, record = _walk_to_completed_with_record()
        res = api.export_counseling_record(
            record["id"], {"export_consent": False},
            make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_EXPORT_CONSENT_MISSING", expected_status=422)

    def test_export_with_consent_appends_audit_log(self, api):
        """PRD §3.6: "A successful export appends an `AuditLogEntry` with
        action `RECORD_EXPORT`."
        """
        counselor, client, completed, record = _walk_to_completed_with_record()
        res = api.export_counseling_record(
            record["id"], export_counseling_record_payload(export_consent=True),
            make_counselor_headers(counselor["id"]),
        )
        validate_success(res, expected_status=200)
        entries = list_audit_log(action="RECORD_EXPORT", target_id=record["id"])
        assert any(e["action"] == "RECORD_EXPORT"
                   and e["target_id"] == record["id"] for e in entries)


class TestCrisisIncidentLifecycle:
    def test_counselor_triggered_creates_detected(self, api):
        """PRD §3.7: "On creation the incident's `status` is `DETECTED`,
        `severity` defaults to `MEDIUM`, and `client_id` is mirrored from
        the appointment; an `AuditLogEntry` with action `CRISIS_DETECTED`
        is appended."
        """
        counselor, client, started = _walk_appointment_to_completed()
        # Create incident on an IN_SESSION appointment (PRD §3.7 requires
        # appointment_id to be a session).
        res = api.create_crisis_incident(
            create_crisis_incident_payload(
                appointment_id=started["id"],
                detection_source="COUNSELOR_TRIGGERED",
            ),
            make_counselor_headers(counselor["id"]),
        )
        incident = validate_success(res, expected_status=201)
        assert_crisis_incident(incident)
        assert incident["status"] == "DETECTED"
        assert incident["severity"] == "MEDIUM"
        assert incident["client_id"] == client["id"]

    def test_keyword_source_without_keyword_rejected(self, api):
        """PRD §3.7: "the optional `trigger_keyword` (which is required when
        `detection_source` is `KEYWORD_DETECTOR` — absence rejects with
        `ERR_TRIGGER_KEYWORD_MISSING`)..."
        """
        counselor, client, started = _walk_appointment_to_completed()
        res = api.create_crisis_incident(
            create_crisis_incident_payload(
                appointment_id=started["id"],
                detection_source="KEYWORD_DETECTOR",
                trigger_keyword=None,    # missing
            ),
            make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_TRIGGER_KEYWORD_MISSING", expected_status=422)


class TestCrisisHandoverCascade:
    def test_handover_cancels_in_session_appointment(self, api):
        """PRD §3.7: "and — if the incident's appointment is currently
        `IN_SESSION` — cascades to that appointment, transitioning it from
        `IN_SESSION` to `CANCELLED` with `cancellation_reason` of
        `CRISIS_HANDOVER`, setting `refund_state` to `FULL_REFUNDED`,
        writing the REFUND row to `SettlementLedger`..."
        """
        counselor, client, started = _walk_appointment_to_completed()
        # Create incident.
        res = api_client.create_crisis_incident(
            create_crisis_incident_payload(
                appointment_id=started["id"],
                detection_source="COUNSELOR_TRIGGERED",
            ),
            make_counselor_headers(counselor["id"]),
        )
        incident = validate_success(res, expected_status=201)
        # Handover by responder with severity=HIGH.
        handed_over = handover_crisis(incident, severity="HIGH")
        assert handed_over["status"] == "HANDED_OVER"
        # Appointment should now be CANCELLED with CRISIS_HANDOVER reason.
        appt_after = get_appointment(started["id"])
        assert appt_after["status"] == "CANCELLED"
        assert appt_after["cancellation_reason"] == "CRISIS_HANDOVER"
        assert appt_after["refund_state"] == "FULL_REFUNDED"


class TestNotifyEmergency:
    def test_low_severity_notify_rejected(self, api):
        """PRD §3.7: "Attempting the same notification when `severity` is
        `LOW` is rejected with `ERR_NOTIFY_NOT_REQUIRED` because the
        protocol skips emergency notification at low severity."
        """
        counselor, client, started = _walk_appointment_to_completed()
        res = api.create_crisis_incident(
            create_crisis_incident_payload(
                appointment_id=started["id"],
                detection_source="COUNSELOR_TRIGGERED",
            ),
            make_counselor_headers(counselor["id"]),
        )
        incident = validate_success(res, expected_status=201)
        handed_over = handover_crisis(incident, severity="LOW")
        # notify-emergency at LOW severity: rejected.
        res2 = api.notify_emergency(
            handed_over["id"], make_crisis_responder_headers("crisis-001"),
        )
        validate_error(res2, "ERR_NOTIFY_NOT_REQUIRED", expected_status=422)

    def test_medium_severity_notify_appends_audit_log(self, api):
        """PRD §3.7: "the action transitions the incident from
        `HANDED_OVER` to `EMERGENCY_NOTIFIED`, sets `emergency_notified_at`
        to current time, requires that the linked client's
        `emergency_contact_phone` be present (otherwise
        `ERR_NO_EMERGENCY_CONTACT`), appends an `AuditLogEntry` with action
        `CRISIS_NOTIFY`, and emits an external `emergency_contact_notify`
        event."
        """
        counselor, client, started = _walk_appointment_to_completed()
        res = api_client.create_crisis_incident(
            create_crisis_incident_payload(
                appointment_id=started["id"],
                detection_source="COUNSELOR_TRIGGERED",
            ),
            make_counselor_headers(counselor["id"]),
        )
        incident = validate_success(res, expected_status=201)
        handed_over = handover_crisis(incident, severity="MEDIUM")
        notified = notify_emergency(handed_over)
        assert notified["status"] == "EMERGENCY_NOTIFIED"
        assert notified["emergency_notified_at"] is not None
        entries = list_audit_log(action="CRISIS_NOTIFY", target_id=handed_over["id"])
        assert any(e["action"] == "CRISIS_NOTIFY"
                   and e["target_id"] == handed_over["id"] for e in entries)
