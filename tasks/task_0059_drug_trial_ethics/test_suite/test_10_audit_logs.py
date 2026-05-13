"""Audit log filtering, read access by RegulatoryWatcher.

PRD §3.8, §2.11.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    SEC,
    WATCHER,
    assert_audit_log,
    list_audit_logs,
    make_applicant_headers,
    setup_resolved_initial_review,
    validate_error,
    validate_paginated,
)


# ===========================================================================
# Audit-log filtering (PRD §3.8)
# ===========================================================================
class TestAuditLogFiltering:
    """PRD §3.8: 'Every audited event is recoverable through the audit-
    log listing, filterable on event_type, subject_entity, and
    subject_id.'"""

    def test_filter_by_event_type_returns_only_matching_rows(self, api):
        """PRD §3.8: 'filterable on event_type'."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        rows = list_audit_logs(SEC, event_type="REGULATORY_SYNC")
        for r in rows:
            assert_audit_log(r)
            assert r["event_type"] == "REGULATORY_SYNC", (
                f"PRD §3.8: event_type filter must restrict; got "
                f"{r['event_type']!r}"
            )

    def test_filter_by_subject_id_returns_only_matching_rows(self, api):
        """PRD §3.8: 'filterable on ... subject_id'."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app_id = bundle["application"]["id"]
        rows = list_audit_logs(SEC, subject_id=app_id)
        for r in rows:
            assert r["subject_id"] == app_id


# ===========================================================================
# Regulatory watcher access (PRD §3.8)
# ===========================================================================
class TestRegulatoryWatcherAccess:
    """PRD §3.8: 'Resolutions, audit logs, applications, and annual
    reports are the four resources the RegulatoryWatcher may read; this
    role has no write authority anywhere in the system and is excluded
    from member-management, meeting-management, and submission
    listings.'"""

    def test_watcher_can_read_audit_logs(self, api):
        """PRD §3.8: '...audit logs ... are the four resources the
        RegulatoryWatcher may read'."""
        res = api.list_audit_logs(WATCHER)
        assert res.status_code == 200

    def test_watcher_cannot_create_application(self, api):
        """PRD §3.8: 'this role has no write authority anywhere in the
        system'."""
        from test_helpers import create_application_payload
        res = api.create_application(create_application_payload(), WATCHER)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_watcher_cannot_list_members(self, api):
        """PRD §3.8: 'excluded from member-management, meeting-
        management, and submission listings.'"""
        res = api.list_members(WATCHER)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
