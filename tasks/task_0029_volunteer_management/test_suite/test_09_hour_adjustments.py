"""HourAdjustment workflow, audit trail, and cross-entity cascade
(PRD §3.7).

Covers difficulty-design rule 4 instance 2 (HourAdjustment APPROVE ->
Application -> Volunteer -> certificate eligibility) and rule 9 instance
2 (compensating-action invariant on Volunteer.total_service_hours +
points_balance).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    approve_hour_adjustment,
    assert_audit_log,
    assert_hour_adjustment,
    assert_volunteer_totals,
    create_certificate_template,
    file_hour_adjustment,
    file_hour_adjustment_payload,
    find_audit_logs,
    get_application,
    get_volunteer,
    issue_certificate,
    list_audit_logs,
    make_organizer_headers,
    make_skilladmin_headers,
    setup_completed_application,
    validate_error,
    validate_success,
)


class TestFiling:
    def test_file_adjustment_creates_pending(self, api):
        """PRD §3.7: 'The Organizer files an adjustment with the target
        application_id, a signed delta_hours between -8.00 and +8.00
        hours (two decimals, non-zero), and a reason string of 10 to
        500 characters. ... The new HourAdjustment row begins in
        status of PENDING and writes the acting organizer's id into
        requested_by_id.'"""
        scenario = setup_completed_application(role_label="LEAD")
        application = scenario["application"]
        organizer = scenario["organizer"]
        res = api.file_hour_adjustment(
            file_hour_adjustment_payload(
                application_id=application["id"],
                delta_hours=0.50,
                reason="Volunteer assisted with extra cleanup duties.",
            ),
            make_organizer_headers(organizer["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_hour_adjustment(data)
        assert data["status"] == "PENDING"
        assert data["application_id"] == application["id"]

    def test_file_adjustment_appends_audit_log_request(self, api):
        """PRD §3.7: 'Filing also appends an AuditLog with action_type
        of HOUR_ADJUST_REQUEST.'"""
        scenario = setup_completed_application(role_label="LEAD")
        application = scenario["application"]
        organizer = scenario["organizer"]
        adj = file_hour_adjustment(
            application=application, organizer=organizer, delta_hours=0.50
        )
        logs = list_audit_logs(action_type="HOUR_ADJUST_REQUEST", limit=100)
        for log in logs:
            assert_audit_log(log)
        target_logs = find_audit_logs(
            logs, action_type="HOUR_ADJUST_REQUEST", target_id=adj["id"]
        )
        assert len(target_logs) >= 1, (
            f"Expected at least one HOUR_ADJUST_REQUEST AuditLog with "
            f"target_id={adj['id']}; saw {len(target_logs)}"
        )

    def test_file_adjustment_with_negative_sum_rejected(self, api):
        """PRD §3.7: 'Filing requires the parent Application to currently
        be in COMPLETED and the resulting Application.adjusted_hours +
        delta_hours to be greater than or equal to zero — a delta that
        would drive adjusted hours negative is rejected with
        ERR_NEGATIVE_HOURS.'

        Setup: COMPLETED with adjusted_hours=2.00 -> delta -3.00
        produces -1.00.
        """
        scenario = setup_completed_application(role_label="LEAD", duration_hours=2)
        application = scenario["application"]
        organizer = scenario["organizer"]
        res = api.file_hour_adjustment(
            file_hour_adjustment_payload(
                application_id=application["id"],
                delta_hours=-3.00,
                reason="Drives adjusted hours below zero for negative-hours test.",
            ),
            make_organizer_headers(organizer["id"]),
        )
        validate_error(res, "ERR_NEGATIVE_HOURS")


class TestApproval:
    def test_approve_advances_to_approved_and_appends_audit(self, api):
        """PRD §3.7: 'on success it advances HourAdjustment.status from
        PENDING to APPROVED, stamps approver_id and decided_at,
        captures the application's old adjusted_hours, sets the new
        Application.adjusted_hours to the old value plus delta_hours
        ... The AuditLog row appended on approval has action_type of
        HOUR_ADJUST_APPROVE and a payload that includes both old and
        new values for adjusted_hours and points_awarded.'"""
        scenario = setup_completed_application(role_label="LEAD")
        application = scenario["application"]
        organizer = scenario["organizer"]
        adj = file_hour_adjustment(
            application=application, organizer=organizer, delta_hours=0.50
        )
        res = api.approve_hour_adjustment(adj["id"], make_skilladmin_headers())
        data = validate_success(res, expected_status=200)
        assert data["status"] == "APPROVED"
        assert data.get("approver_id") is not None
        assert data.get("decided_at") is not None

        approve_logs = list_audit_logs(action_type="HOUR_ADJUST_APPROVE", limit=100)
        target_logs = find_audit_logs(
            approve_logs, action_type="HOUR_ADJUST_APPROVE", target_id=adj["id"]
        )
        assert len(target_logs) >= 1
        log = target_logs[0]
        # Payload must include old + new for both adjusted_hours and points_awarded.
        payload = log["payload"]
        assert "adjusted_hours" in str(payload), (
            f"Expected old/new adjusted_hours in AuditLog payload: {payload}"
        )
        assert "points_awarded" in str(payload), (
            f"Expected old/new points_awarded in AuditLog payload: {payload}"
        )

    def test_reject_advances_to_rejected_and_appends_audit(self, api):
        """PRD §3.7: 'Rejection advances HourAdjustment.status from
        PENDING to REJECTED, stamps approver_id and decided_at, and
        appends an AuditLog with action_type of HOUR_ADJUST_REJECT.
        Both APPROVED and REJECTED are terminal.'"""
        scenario = setup_completed_application(role_label="LEAD")
        application = scenario["application"]
        organizer = scenario["organizer"]
        adj = file_hour_adjustment(
            application=application, organizer=organizer, delta_hours=0.50
        )
        res = api.reject_hour_adjustment(adj["id"], make_skilladmin_headers())
        data = validate_success(res, expected_status=200)
        assert data["status"] == "REJECTED"

        reject_logs = list_audit_logs(action_type="HOUR_ADJUST_REJECT", limit=100)
        target_logs = find_audit_logs(
            reject_logs, action_type="HOUR_ADJUST_REJECT", target_id=adj["id"]
        )
        assert len(target_logs) >= 1


class TestApprovalCascadeToCertificateEligibility:
    """difficulty: transitive_cascade/hour_adjust_approve_to_application_to_volunteer_to_certificate_eligibility"""

    def test_cascade_makes_volunteer_eligible_for_certificate(self, api):
        """PRD §3.7: 'on success it ... increases
        Volunteer.total_service_hours by the hours delta, and increases
        Volunteer.points_balance by the points delta.'

        PRD §3.9: 'Eligibility is satisfied when both predicates hold
        simultaneously: the volunteer's total_service_hours is greater
        than or equal to the template's min_hours, and the volunteer's
        total_completed_activities is greater than or equal to the
        template's min_completed_activities. Both comparisons are
        inclusive — a volunteer with exactly min_hours and exactly
        min_completed_activities is eligible.'

        # difficulty: transitive_cascade/hour_adjust_approve_to_application_to_volunteer_to_certificate_eligibility
        """
        # Setup: COMPLETED Application with adjusted_hours=2.00,
        # MEDIUM/LEAD => points_awarded=36, Volunteer total_service_hours=2.00,
        # total_completed_activities=1.
        scenario = setup_completed_application(
            difficulty="MEDIUM", role_label="LEAD", duration_hours=2,
        )
        application = scenario["application"]
        organizer = scenario["organizer"]
        volunteer = scenario["volunteer"]

        # Template requires 2.50 hours and 1 activity.
        template = create_certificate_template(
            min_hours=2.50, min_completed_activities=1,
        )
        # Before the cascade, volunteer has only 2.00 hours -> NOT eligible.
        from test_helpers import issue_certificate_payload
        not_yet = api.issue_certificate(
            issue_certificate_payload(
                template_id=template["id"], volunteer_id=volunteer["id"]
            ),
            make_skilladmin_headers(),
        )
        validate_error(not_yet, "ERR_NOT_ELIGIBLE")

        # File and approve +0.50 adjustment -> total_service_hours == 2.50.
        adj = file_hour_adjustment(
            application=application, organizer=organizer, delta_hours=0.50
        )
        approve_hour_adjustment(adj["id"])

        new_app = get_application(application["id"])
        new_v = get_volunteer(volunteer["id"])
        assert new_app["adjusted_hours"] == pytest.approx(2.50, abs=0.005)
        assert int(new_app["points_awarded"]) == 45
        assert_volunteer_totals(
            new_v,
            expected_total_service_hours=2.50,
            expected_points_balance=45,
            expected_total_completed_activities=1,
        )

        # Now eligibility should pass — issue the certificate.
        cert_res = api.issue_certificate(
            issue_certificate_payload(
                template_id=template["id"], volunteer_id=volunteer["id"]
            ),
            make_skilladmin_headers(),
        )
        cert = validate_success(cert_res, expected_status=201)
        assert cert["status"] == "ISSUED"
        assert cert["hours_at_issuance"] == pytest.approx(2.50, abs=0.005)


class TestCompensatingInvariant:
    """difficulty: compensating_invariant/hour_adjust_approve_then_compensating_adjust_restores_balances"""

    def test_compensating_adjustment_restores_volunteer_balances(self, api):
        """PRD §3.7: approving HourAdjustment 'increases
        Volunteer.total_service_hours by the hours delta, and
        increases Volunteer.points_balance by the points delta.'

        Forward: delta=+0.50 -> hours +0.50, points +9 (MEDIUM/LEAD).
        Compensating: delta=-0.50 -> hours -0.50, points -9. Both
        Volunteer fields return to 2.00 / 36 exactly.

        # difficulty: compensating_invariant/hour_adjust_approve_then_compensating_adjust_restores_balances
        """
        scenario = setup_completed_application(
            difficulty="MEDIUM", role_label="LEAD", duration_hours=2,
        )
        application = scenario["application"]
        organizer = scenario["organizer"]
        volunteer = scenario["volunteer"]
        # Baseline: 2.00 hours, 36 points.
        assert_volunteer_totals(
            volunteer,
            expected_total_service_hours=2.00,
            expected_points_balance=36,
        )

        # Forward: +0.50.
        adj1 = file_hour_adjustment(
            application=application, organizer=organizer, delta_hours=0.50
        )
        approve_hour_adjustment(adj1["id"])

        # Compensating: -0.50 on the same Application.
        application = get_application(application["id"])
        adj2 = file_hour_adjustment(
            application=application, organizer=organizer, delta_hours=-0.50
        )
        approve_hour_adjustment(adj2["id"])

        # Final: back to 2.00 / 36.
        new_app = get_application(application["id"])
        new_v = get_volunteer(volunteer["id"])
        assert new_app["adjusted_hours"] == pytest.approx(2.00, abs=0.005)
        assert int(new_app["points_awarded"]) == 36
        assert_volunteer_totals(
            new_v,
            expected_total_service_hours=2.00,
            expected_points_balance=36,
        )
