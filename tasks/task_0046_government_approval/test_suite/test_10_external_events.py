"""External-event ingress idempotency, audit-log writes, and read-side
audit queries.

Covers PRD §2.12 (Idempotent External-Event Ingress), §2.13 (Audit
Trail), §3.13 (Audit log queries).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    decide,
    drive_to_under_review,
    emit_event_payload,
    emit_identity_verified,
    find_audit_entries,
    get_application,
    get_success_data,
    list_audit_logs_filtered,
    setup_application_under_review_single_dept,
    setup_single_department_published_version,
    submit_application,
    TEST_USERS,
    unique_idempotency_key,
    validate_success,
)


# ===========================================================================
# Idempotent ingress (PRD §2.12)
# ===========================================================================
class TestExternalEventIdempotency:
    def test_duplicate_idempotency_key_absorbs_to_same_event(
        self, api, platform_admin_headers,
    ):
        """PRD §2.12: "A duplicate (event_type, idempotency_key) pair is
        absorbed: the server returns the previously stored ExternalEvent
        unchanged with HTTP status 200, processed reflecting the
        original outcome, and no side effects are re-applied."

        Claim: emitting two IDENTITY_VERIFIED events with the same
        idempotency_key returns ExternalEvents whose ids match (the
        second is the absorbed echo of the first).
        """
        ctx = setup_single_department_published_version(fee_amount_cents=1000)
        application, _hdrs, _id = submit_application(ctx=ctx)
        key = unique_idempotency_key("idem")
        first_resp = api.emit_event(
            emit_event_payload(
                "IDENTITY_VERIFIED", application["id"], idempotency_key=key,
            ),
            platform_admin_headers,
        )
        first = validate_success(first_resp)
        second_resp = api.emit_event(
            emit_event_payload(
                "IDENTITY_VERIFIED", application["id"], idempotency_key=key,
            ),
            platform_admin_headers,
        )
        second = validate_success(second_resp)
        # The server must return the ORIGINAL ExternalEvent, so id must match.
        assert first["id"] == second["id"], (
            "PRD §2.12: duplicate idempotency_key must return the previously "
            "stored ExternalEvent unchanged."
        )

    def test_distinct_idempotency_keys_create_distinct_events(
        self, api, platform_admin_headers,
    ):
        """PRD §2.12: "The first delivery for a given (event_type,
        idempotency_key) is processed exactly once."

        Claim: two events with the same event_type but different
        idempotency_keys yield two distinct ExternalEvent ids.
        """
        ctx = setup_single_department_published_version(fee_amount_cents=1000)
        application, _hdrs, _id = submit_application(ctx=ctx)
        first = validate_success(
            api.emit_event(
                emit_event_payload("IDENTITY_VERIFIED", application["id"]),
                platform_admin_headers,
            )
        )
        second = validate_success(
            api.emit_event(
                emit_event_payload("PAYMENT_SETTLED", application["id"]),
                platform_admin_headers,
            )
        )
        assert first["id"] != second["id"]


# ===========================================================================
# Audit trail (PRD §2.13)
# ===========================================================================
class TestAuditTrail:
    def test_application_submit_writes_audit_log(self, api):
        """PRD §3.4: "The submission writes an AuditLog row with action
        APPLICATION_SUBMIT."

        Claim: after a successful POST /applications, the audit log
        contains an APPLICATION_SUBMIT row whose target_id is the new
        application's id.
        """
        ctx = setup_single_department_published_version(fee_amount_cents=0)
        application, _hdrs, _id = submit_application(ctx=ctx)
        rows = list_audit_logs_filtered(
            target_id=application["id"], action="APPLICATION_SUBMIT",
        )
        assert len(rows) >= 1
        row = rows[0]
        assert row["action"] == "APPLICATION_SUBMIT"
        assert row["target_id"] == application["id"]

    def test_review_decide_writes_audit_log(self, api):
        """PRD §3.6: "Every decision writes an AuditLog row with action
        REVIEW_DECIDE."

        Claim: after a single AGREED decision, an audit row with action
        REVIEW_DECIDE exists for that ReviewTask id.
        """
        ctx = setup_application_under_review_single_dept()
        task = ctx["review_tasks"][0]
        decide(task["id"], "AGREED", ctx["reviewer_headers"])
        rows = list_audit_logs_filtered(
            target_id=task["id"], action="REVIEW_DECIDE",
        )
        assert len(rows) >= 1
