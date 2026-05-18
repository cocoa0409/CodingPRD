"""Voluntary abandon cascades and OA deadline sweep cascades.

Covers PRD §3.3 (deadline sweep) and §3.3 (voluntary abandon).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BASE_CLOCK,
    abandon_application,
    advance_clock_to,
    get_application,
    get_office_action,
    list_audit_events,
    list_maintenance_fees,
    list_office_actions,
    make_applicant_headers,
    setup_filed_application,
    setup_office_action_at_clock,
    setup_office_action_pending,
    validate_error,
    validate_success,
)


# ===========================================================================
# Voluntary abandon (PRD §3.3)
# ===========================================================================
class TestVoluntaryAbandon:

    def test_abandon_from_filed_succeeds(self, api):
        """PRD §3.3: "An applicant may also voluntarily abandon their
        filing at any time while it is in FILED, UNDER_EXAMINATION,
        OFFICE_ACTION_PENDING, or ALLOWED".
        """
        a, app = setup_filed_application()
        out = abandon_application(a, app)
        assert out["status"] == "ABANDONED"
        # Audit row written.
        events = list_audit_events(app["id"])
        actions = [e["action"] for e in events]
        assert "APPLICATION_ABANDONED_VOLUNTARY" in actions, (
            "PRD §3.3: voluntary abandon must write APPLICATION_ABANDONED_VOLUNTARY"
        )

    def test_abandon_from_office_action_pending_cascades_oa(self, api):
        """PRD §3.3: "the abandonment cascades every PENDING Office
        Action for that application into ABANDONED_BY_DEFAULT".
        """
        a, app, oa = setup_office_action_pending()
        abandon_application(a, app)
        # OA is now ABANDONED_BY_DEFAULT.
        oa_after = get_office_action(oa["id"])
        assert oa_after["status"] == "ABANDONED_BY_DEFAULT", (
            "PRD §3.3: voluntary abandon must cascade PENDING OA to ABANDONED_BY_DEFAULT"
        )

    def test_abandon_from_draft_rejected_invalid_state(self, api):
        """PRD §3.3: "An applicant may also voluntarily abandon their
        filing at any time while it is in FILED, UNDER_EXAMINATION,
        OFFICE_ACTION_PENDING, or ALLOWED".

        Claim: DRAFT is not in the abandon-permitted set, so /abandon
        on a DRAFT returns ERR_INVALID_STATE.
        """
        from test_helpers import create_applicant, create_draft_application
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(a)
        res = api.abandon_application(app["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Deadline sweep cascade — OA past extended_deadline (PRD §3.3 + §2.8)
# ===========================================================================
class TestOADeadlineCascade:

    def test_oa_past_extended_deadline_cascades_to_abandoned(self, api):
        """PRD §3.3: "If the clock advances past an Office Action's
        extended_deadline_at while that Office Action is still PENDING,
        the deadline sweep described in §2.8 deterministically
        transitions the Office Action's status to ABANDONED_BY_DEFAULT,
        cascades the application to ABANDONED, and writes an
        APPLICATION_ABANDONED_DEADLINE audit row."
        """
        a, app, oa = setup_office_action_at_clock(issued_at_dt=DEFAULT_BASE_CLOCK)
        ed = datetime.fromisoformat(oa["extended_deadline_at"].replace("Z", "+00:00"))
        # 1 second past.
        advance_clock_to(ed + timedelta(seconds=1))
        oa_after = get_office_action(oa["id"])
        assert oa_after["status"] == "ABANDONED_BY_DEFAULT", (
            "PRD §3.3: OA past extended_deadline_at must flip to ABANDONED_BY_DEFAULT"
        )
        app_after = get_application(app["id"])
        assert app_after["status"] == "ABANDONED", (
            "PRD §3.3: deadline sweep must cascade application to ABANDONED"
        )
        events = list_audit_events(app["id"])
        actions = [e["action"] for e in events]
        assert "APPLICATION_ABANDONED_DEADLINE" in actions, (
            "PRD §3.3: deadline-driven abandon must write APPLICATION_ABANDONED_DEADLINE"
        )


# ===========================================================================
# Audit events (PRD §2.9 + §3.7)
# ===========================================================================
class TestAudit:

    def test_audit_event_for_application_drafted(self, api):
        """PRD §3.2: "the system also writes an audit record with the
        symbolic action APPLICATION_DRAFTED."
        """
        from test_helpers import create_applicant, create_draft_application
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(a)
        events = list_audit_events(app["id"])
        actions = [e["action"] for e in events]
        assert "APPLICATION_DRAFTED" in actions, (
            "PRD §3.2: APPLICATION_DRAFTED must appear in audit"
        )

    def test_audit_event_for_application_filed(self, api):
        """PRD §3.2: "writes an APPLICATION_FILED audit record"."""
        a, app = setup_filed_application()
        events = list_audit_events(app["id"])
        actions = [e["action"] for e in events]
        assert "APPLICATION_FILED" in actions, (
            "PRD §3.2: APPLICATION_FILED must appear in audit"
        )

    def test_audit_event_for_examination_begun(self, api):
        """PRD §3.3: "The transition writes an EXAMINATION_BEGUN audit row."

        Claim: the EXAMINATION_BEGUN action appears in the audit
        stream of an application that has reached UNDER_EXAMINATION.
        """
        from test_helpers import setup_under_examination
        a, app = setup_under_examination()
        events = list_audit_events(app["id"])
        actions = [e["action"] for e in events]
        assert "EXAMINATION_BEGUN" in actions
