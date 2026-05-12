"""Audit log read endpoint: filters and pagination.

PRD §2.12, §3.10, §4.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_audit_log,
    bring_evidence_to_confirmed,
    bring_evidence_to_failed,
    list_audit_logs,
    validate_error,
    validate_paginated,
)


# ===========================================================================
# AuditLog read (PRD §3.10)
# ===========================================================================
class TestAuditLogRead:
    """PRD §3.10: 'A PlatformAdmin may also list audit events with
    optional filters for event_type, target_entity, and target_id,
    paginated through limit and offset.'"""

    def test_filter_by_event_type(self, api, admin_headers):
        """PRD §3.10: 'optional filters for event_type'."""
        # Generate an EVIDENCE_CONFIRMED event.
        customer, ev = bring_evidence_to_confirmed()
        rows, _meta = validate_paginated(api.list_audit_logs(
            admin_headers,
            params={"event_type": "EVIDENCE_CONFIRMED"},
        ))
        assert len(rows) >= 1
        for r in rows:
            assert_audit_log(r)
            assert r["event_type"] == "EVIDENCE_CONFIRMED"

    def test_filter_by_target_entity_and_id(self, api, admin_headers):
        """PRD §3.10: 'optional filters for event_type, target_entity,
        and target_id'."""
        customer, ev = bring_evidence_to_confirmed()
        rows, _meta = validate_paginated(api.list_audit_logs(
            admin_headers,
            params={"target_entity": "Evidence", "target_id": ev["id"]},
        ))
        assert len(rows) >= 1
        for r in rows:
            assert r["target_entity"] == "Evidence"
            assert r["target_id"] == ev["id"]


# ===========================================================================
# AuditLog actor capture (PRD §2.12)
# ===========================================================================
class TestAuditActor:
    """PRD §2.12: 'Each AuditLog row records the actor_role (one of
    Customer, JudicialOfficer, NotaryOfficer, PlatformAdmin, or system
    for cascades the platform performs autonomously), the actor_id
    (the value of X-User-ID at request time, or null for system
    events)'."""

    def test_evidence_submitted_actor_is_customer(self, api,
                                                   admin_headers):
        """PRD §2.12: 'actor_role ... Customer' for customer-initiated
        events."""
        customer, _ev, _ = (
            None, None, None,
        )
        from test_helpers import bring_evidence_to_submitting
        customer, ev, _ = bring_evidence_to_submitting()
        rows = list_audit_logs(
            event_type="EVIDENCE_SUBMITTED",
            target_entity="Evidence",
            target_id=ev["id"],
        )
        assert len(rows) >= 1
        assert rows[-1]["actor_role"] == "Customer"
        assert rows[-1]["actor_id"] == customer["id"]


# ===========================================================================
# Audit log append-only (PRD §2.12)
# ===========================================================================
class TestAuditAppendOnly:
    """PRD §2.12: 'The audit log is append-only; entries are never
    updated or deleted.'"""

    def test_audit_rows_are_append_only_shape(self, api):
        """PRD §2.4 / §2.12: AuditLog is one of the append-only
        entities (id + created_at only)."""
        customer, _ev = bring_evidence_to_confirmed()
        rows = list_audit_logs()
        for r in rows[:5]:
            assert_audit_log(r)
            # PRD §2.4: append-only entities must not carry version /
            # updated_at — they are not in the contract for these rows.
            assert "version" not in r
            assert "updated_at" not in r
