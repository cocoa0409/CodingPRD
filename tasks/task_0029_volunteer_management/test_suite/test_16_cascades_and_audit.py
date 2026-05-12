"""Cascading side effects on time-gated transitions, NO_SHOW cascade,
and AuditLog / PartnerSyncEvent ledgers (PRD §2.8, §2.10, §3.3, §3.5).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    advance_clock,
    advance_to_completed,
    advance_to_running,
    api_client,
    apply_to_activity,
    approve_application,
    assert_audit_log,
    assert_partner_sync_event,
    check_in_via_site_code,
    create_verified_volunteer,
    find_audit_logs,
    find_partner_sync_events,
    get_activity,
    get_application,
    get_volunteer,
    list_audit_logs,
    list_partner_sync_events,
    make_skilladmin_headers,
    make_volunteer_headers,
    setup_organizer,
    setup_recruiting_activity,
    setup_running_activity_with_approved_volunteer,
    validate_success,
)


class TestRunningToCompletedCascade:
    def test_checked_in_no_check_out_at_end_auto_completes(self, api):
        """PRD §3.3 / §2.8: 'an Activity automatically transitioning to
        COMPLETED simultaneously stamps check_out_at = Activity.end_at
        on every Application still in CHECKED_IN, transitions those
        applications to COMPLETED, runs the service-hour and
        point-earning calculations against each, increments
        Volunteer.total_completed_activities and
        Volunteer.total_service_hours and Volunteer.points_balance
        accordingly.'"""
        scenario = setup_running_activity_with_approved_volunteer(
            difficulty="MEDIUM", role_label="LEAD",
        )
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        application = check_in_via_site_code(
            application=application, volunteer=volunteer, activity=activity
        )
        # DON'T check out — let clock drive the cascade.
        advance_to_completed(activity)
        # Refetch.
        new_app = get_application(application["id"])
        new_v = get_volunteer(volunteer["id"])
        assert new_app["status"] == "COMPLETED"
        assert new_app.get("check_out_at") == activity["end_at"]
        # 2.00 hours * MEDIUM 1.50 * LEAD 1.20 = 36 points.
        assert int(new_app["points_awarded"]) == 36
        assert int(new_v["total_completed_activities"]) == 1
        assert float(new_v["total_service_hours"]) == pytest.approx(2.00, abs=0.005)
        assert int(new_v["points_balance"]) == 36

    def test_approved_no_check_in_at_end_becomes_no_show(self, api):
        """PRD §3.3 / §2.8: 'and at the same time transitions every
        Application still in APPROVED (with no check_in_at) to
        NO_SHOW.'"""
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v = create_verified_volunteer()
        app = apply_to_activity(volunteer=v, activity=activity)
        approve_application(application=app, organizer=organizer)
        # No check-in. Drive activity to COMPLETED.
        advance_to_running(activity)
        advance_to_completed(activity)
        new_app = get_application(app["id"])
        assert new_app["status"] == "NO_SHOW"


class TestAuditLogActionTypes:
    def test_audit_log_action_types_constrained_to_six_values(self, api):
        """PRD §2.10: 'The recognized action_type values are exactly
        HOUR_ADJUST_REQUEST, HOUR_ADJUST_APPROVE, HOUR_ADJUST_REJECT,
        CERTIFICATE_ISSUE, CERTIFICATE_REISSUE, and CERTIFICATE_REVOKE;
        no other action types are written.'"""
        allowed = {
            "HOUR_ADJUST_REQUEST", "HOUR_ADJUST_APPROVE", "HOUR_ADJUST_REJECT",
            "CERTIFICATE_ISSUE", "CERTIFICATE_REISSUE", "CERTIFICATE_REVOKE",
        }
        logs = list_audit_logs(limit=100)
        for log in logs:
            assert_audit_log(log)
            assert log["action_type"] in allowed, (
                f"Saw audit_log with action_type={log['action_type']!r}, "
                f"which is not in PRD §2.10's allowed set {allowed}"
            )


class TestPartnerSyncEventChannels:
    def test_sync_event_channels_constrained_to_three(self, api):
        """PRD §2.10: 'each carrying a channel of IM, IDENTITY_PROVIDER,
        or PARTNER_ORG.'"""
        allowed = {"IM", "IDENTITY_PROVIDER", "PARTNER_ORG"}
        events = list_partner_sync_events(limit=100)
        for ev in events:
            assert_partner_sync_event(ev)
            assert ev["channel"] in allowed, (
                f"Saw partner_sync_event with channel={ev['channel']!r}, "
                f"which is not in PRD §2.10's allowed set {allowed}"
            )
