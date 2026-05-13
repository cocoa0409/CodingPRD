"""Prescreen decisions and the rework loop.

PRD §3.1.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    SEC,
    create_application_with_submission,
    create_submission,
    find_audit_entries,
    get_application,
    list_audit_logs,
    make_applicant_headers,
    prescreen_application,
    setup_application_pending_prescreen,
    submit_application,
    validate_error,
    validate_success,
)


# ===========================================================================
# Prescreen PASS (PRD §3.1)
# ===========================================================================
class TestPrescreenPass:
    """PRD §3.1: 'A PASS decision requires the current submission's
    checklist_complete to be true; on success the application advances
    from PENDING_PRESCREEN to PENDING_REVIEW, the current submission's
    prescreen_status is set to PASSED, and an audit row of event_type
    REVIEW_DECISION is written.'"""

    def test_prescreen_pass_advances_to_pending_review(self, api):
        """PRD §3.1: 'on success the application advances from
        PENDING_PRESCREEN to PENDING_REVIEW'."""
        app, _ = setup_application_pending_prescreen()
        updated = prescreen_application(app["id"], "PASS")
        assert updated["status"] == "PENDING_REVIEW", (
            f"PRD §3.1: PASS moves to PENDING_REVIEW; got "
            f"{updated['status']!r}"
        )

    def test_prescreen_pass_writes_review_decision_audit(self, api):
        """PRD §3.1: 'an audit row of event_type REVIEW_DECISION is
        written.'"""
        app, _ = setup_application_pending_prescreen()
        prescreen_application(app["id"], "PASS")
        rows = list_audit_logs(SEC, event_type="REVIEW_DECISION",
                               subject_entity="Application",
                               subject_id=app["id"])
        assert len(rows) >= 1, (
            f"PRD §3.1: 'an audit row of event_type REVIEW_DECISION is "
            f"written'; got {rows!r}"
        )


# ===========================================================================
# Prescreen REJECT (PRD §3.1)
# ===========================================================================
class TestPrescreenReject:
    """PRD §3.1: 'A REJECT decision moves the application from
    PENDING_PRESCREEN to REWORK_REQUIRED, sets the current submission's
    prescreen_status to REJECTED, and likewise writes a REVIEW_DECISION
    audit row.'"""

    def test_prescreen_reject_moves_to_rework_required(self, api):
        """PRD §3.1: 'A REJECT decision moves the application from
        PENDING_PRESCREEN to REWORK_REQUIRED'."""
        app, _ = setup_application_pending_prescreen()
        updated = prescreen_application(app["id"], "REJECT",
                                        prescreen_notes="needs power calc")
        assert updated["status"] == "REWORK_REQUIRED", (
            f"PRD §3.1: REJECT moves to REWORK_REQUIRED; got "
            f"{updated['status']!r}"
        )


# ===========================================================================
# Rework cycle (PRD §3.1, §3.4 cycle)
# ===========================================================================
class TestReworkCycle:
    """PRD §3.1: 'After REWORK_REQUIRED, the applicant uploads a new
    submission version (which auto-becomes the new current submission
    and resets its prescreen_status to PENDING) and re-submits, returning
    the application to PENDING_PRESCREEN.'"""

    def test_rework_cycle_returns_to_pending_prescreen(self, api):
        """PRD §3.1: 'After REWORK_REQUIRED, the applicant uploads a new
        submission version ... and re-submits, returning the
        application to PENDING_PRESCREEN.'"""
        app, _ = setup_application_pending_prescreen()
        # REJECT -> REWORK_REQUIRED
        prescreen_application(app["id"], "REJECT")
        # Upload v2
        app_obj = get_application(app["id"])
        new_sub = create_submission(app_obj)
        assert new_sub["version_number"] == 2, (
            f"PRD §3.1: 'one greater than the maximum existing "
            f"version_number'; got {new_sub['version_number']!r}"
        )
        # New submission's prescreen_status resets to PENDING.
        assert new_sub["prescreen_status"] == "PENDING", (
            f"PRD §3.1: 'resets its prescreen_status to PENDING'; got "
            f"{new_sub.get('prescreen_status')!r}"
        )
        # Re-submit -> back to PENDING_PRESCREEN
        app_after = submit_application(app_obj)
        assert app_after["status"] == "PENDING_PRESCREEN", (
            f"PRD §3.1: 'returning the application to PENDING_PRESCREEN'; "
            f"got {app_after['status']!r}"
        )
