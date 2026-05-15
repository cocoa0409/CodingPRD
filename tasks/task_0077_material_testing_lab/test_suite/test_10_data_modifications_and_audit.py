"""Data-modification log and audit trail (PRD §3.8).

Covers PATCH /records/{id} (reason required, immutable log entry on each
change, recompute of calculated_result / abnormal_flag), GET
/records/{id}/modifications, /_audit/respond-external, and audit-event
emission on report issuance.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_audit_event,
    make_tester_headers,
    respond_external_payload,
    setup_completed_task,
    setup_in_progress_task,
    setup_issued_report,
    submit_record,
    TEST_USERS,
    update_record_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDataModificationReasonRequired:
    def test_patch_record_without_reason_rejected(self, api):
        """PRD §3.8: 'The reason MUST be non-empty; an empty or absent
        reason rejects the modification with
        ERR_DATA_MODIFICATION_REASON_REQUIRED.'

        Claim: PATCH /records/{id} without a reason field is
        ERR_DATA_MODIFICATION_REASON_REQUIRED.
        """
        env = setup_in_progress_task()
        record = submit_record(
            task_id=env["task"]["id"], tester_id=env["tester"]["id"],
            peak_load_kn=600.0,
        )
        resp = api.update_record(
            record["id"],
            {"version": record["version"],
             "raw_data": {"peak_load_kn": 700.0}},
            make_tester_headers(env["tester"]["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_DATA_MODIFICATION_REASON_REQUIRED.value,
        )

    def test_patch_record_with_empty_reason_rejected(self, api):
        """PRD §3.8: 'The reason MUST be non-empty.'

        Claim: an empty-string reason is treated as missing.
        """
        env = setup_in_progress_task()
        record = submit_record(
            task_id=env["task"]["id"], tester_id=env["tester"]["id"],
            peak_load_kn=600.0,
        )
        resp = api.update_record(
            record["id"],
            update_record_payload(
                version=record["version"], reason="",
                raw_data={"peak_load_kn": 700.0},
            ),
            make_tester_headers(env["tester"]["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_DATA_MODIFICATION_REASON_REQUIRED.value,
        )


class TestDataModificationAppendsLogAndRecomputes:
    def test_modification_appends_log_entries_for_each_changed_field(
        self, api, lab_manager_headers,
    ):
        """PRD §3.8: 'For each field actually changed, the server
        appends an immutable DataModification row recording the
        record_id, the modifying user's role (actor_role) and
        identifier (actor_id) ... the field_path of the modified key
        in dot notation (for instance raw_data.peak_load_kn ...).'

        Claim: PATCH that changes raw_data.peak_load_kn appends a
        DataModification with field_path == "raw_data.peak_load_kn"
        and the supplied reason.
        """
        env = setup_in_progress_task()
        record = submit_record(
            task_id=env["task"]["id"], tester_id=env["tester"]["id"],
            peak_load_kn=600.0,
        )
        api.update_record(
            record["id"],
            update_record_payload(
                version=record["version"], reason="transcription error",
                raw_data={"peak_load_kn": 700.0},
            ),
            make_tester_headers(env["tester"]["id"]),
        )
        list_resp = api.list_record_modifications(
            record["id"], lab_manager_headers,
        )
        data, _ = validate_paginated(list_resp)
        assert any(
            m["field_path"] == "raw_data.peak_load_kn"
            and m["reason"] == "transcription error"
            for m in data
        ), f"expected a peak_load_kn modification entry; got {data}"

    def test_modification_recomputes_calculated_result_and_abnormal_flag(
        self, api, lab_manager_headers,
    ):
        """PRD §3.8: 'The calculated_result and abnormal_flag are
        recomputed against the new raw_data and the original
        specification.'

        Claim: changing peak_load_kn from 600 (26.7 MPa) to 400
        (17.8 MPa) recomputes calculated_result and flips
        abnormal_flag to true.
        """
        env = setup_in_progress_task()
        record = submit_record(
            task_id=env["task"]["id"], tester_id=env["tester"]["id"],
            peak_load_kn=600.0,
        )
        assert record["abnormal_flag"] is False
        patch_resp = api.update_record(
            record["id"],
            update_record_payload(
                version=record["version"], reason="recompute",
                raw_data={"peak_load_kn": 400.0},
            ),
            make_tester_headers(env["tester"]["id"]),
        )
        data = validate_success(patch_resp)
        assert data["calculated_result"] == pytest.approx(17.8, abs=0.05)
        assert data["abnormal_flag"] is True


class TestExternalInspectionResponse:
    def test_respond_external_emits_audit_event(
        self, api, lab_manager_headers,
    ):
        """PRD §3.8: 'A LabManager may also record an external-inspection
        response by supplying an inspection_id and a response_note,
        which emits an EXTERNAL_INSPECTION_RESPONDED event.'

        Claim: POST /_audit/respond-external emits an audit event of
        type EXTERNAL_INSPECTION_RESPONDED.
        """
        body = respond_external_payload(
            inspection_id="INS-001", response_note="Findings acknowledged.",
        )
        resp = api.respond_external_inspection(body, lab_manager_headers)
        validate_success(resp)

        # Read back via audit-events
        list_resp = api.list_audit_events(
            lab_manager_headers,
            params={"event_type": "EXTERNAL_INSPECTION_RESPONDED"},
        )
        data, _ = validate_paginated(list_resp)
        assert any(
            e["event_type"] == "EXTERNAL_INSPECTION_RESPONDED"
            for e in data
        ), "expected at least one EXTERNAL_INSPECTION_RESPONDED event"


class TestInternalAuditIdempotent:
    def test_internal_audit_run_idempotent_within_utc_date(
        self, api, lab_manager_headers,
    ):
        """PRD §3.8: 'A LabManager may run an internal-audit sweep that
        emits a single INTERNAL_AUDIT_RUN event carrying a snapshot of
        stats in its payload; this operation is idempotent within the
        same UTC date, meaning a second call on the same date does not
        emit a duplicate event.'

        Claim: two POST /_audit/run-internal calls on the same UTC
        date yield only one new INTERNAL_AUDIT_RUN event.
        """
        # Count existing events of this type.
        existing = api.list_audit_events(
            lab_manager_headers,
            params={"event_type": "INTERNAL_AUDIT_RUN", "limit": 100},
        )
        before_data, _ = validate_paginated(existing)
        before_count = len(before_data)

        api.run_internal_audit(lab_manager_headers)
        api.run_internal_audit(lab_manager_headers)

        after = api.list_audit_events(
            lab_manager_headers,
            params={"event_type": "INTERNAL_AUDIT_RUN", "limit": 100},
        )
        after_data, _ = validate_paginated(after)
        # Exactly one new event.
        assert len(after_data) == before_count + 1, (
            f"expected exactly one new INTERNAL_AUDIT_RUN event; "
            f"before={before_count}, after={len(after_data)}"
        )


class TestReportIssuedAuditEvent:
    def test_issuance_emits_report_issued_audit_event(
        self, api, lab_manager_headers,
    ):
        """PRD §3.9: 'Issuing the report moves it from SIGNED to ISSUED,
        sets issued_at to the current instant, and emits a
        REPORT_ISSUED AuditEvent whose payload carries the report's
        version.'

        Claim: after issuing a report, an AuditEvent with event_type ==
        REPORT_ISSUED exists with subject_id == report.id.
        """
        env = setup_issued_report()
        resp = api.list_audit_events(
            lab_manager_headers,
            params={
                "event_type": "REPORT_ISSUED",
                "subject_id": env["report"]["id"],
            },
        )
        data, _ = validate_paginated(resp)
        assert len(data) >= 1, "expected at least one REPORT_ISSUED event"
        evt = data[0]
        assert_audit_event(evt)
        assert evt["subject_id"] == env["report"]["id"]
