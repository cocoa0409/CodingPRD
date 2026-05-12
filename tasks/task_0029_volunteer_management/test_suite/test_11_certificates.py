"""Certificate templates, issuance, batch, reissue, revoke, verify
(PRD §3.9). Covers difficulty-design rule 6 instance 1 (certificate
min_hours inclusive boundary).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    assert_certificate,
    assert_certificate_template,
    create_certificate_template,
    create_certificate_template_payload,
    create_verified_volunteer,
    file_hour_adjustment,
    approve_hour_adjustment,
    find_audit_logs,
    find_partner_sync_events,
    issue_certificate,
    issue_certificate_payload,
    issue_certificates_batch_payload,
    list_audit_logs,
    list_partner_sync_events,
    make_skilladmin_headers,
    reissue_certificate,
    revoke_certificate,
    setup_completed_application,
    validate_error,
    validate_success,
)


class TestCertificateTemplates:
    def test_create_template_starts_active(self, api, skilladmin_headers):
        """PRD §3.9: 'Templates begin in status of ACTIVE and may move
        to ARCHIVED.'"""
        res = api.create_certificate_template(
            create_certificate_template_payload(
                min_hours=5.00, min_completed_activities=2
            ),
            skilladmin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_certificate_template(data)
        assert data["status"] == "ACTIVE"


class TestSingleIssuance:
    """difficulty: boundary_precision_check/certificate_min_hours_inclusive_boundary_on_certificates_endpoint"""

    def test_issuance_at_exact_min_hours_boundary_succeeds(self, api):
        """PRD §3.9: 'Both comparisons are inclusive — a volunteer with
        exactly min_hours and exactly min_completed_activities is
        eligible.'

        Setup: Volunteer with total_service_hours == 2.50 (via base
        2.00 + +0.50 adjustment), total_completed_activities == 1.
        Template min_hours == 2.50, min_completed_activities == 1.

        # difficulty: boundary_precision_check/certificate_min_hours_inclusive_boundary_on_certificates_endpoint
        """
        scenario = setup_completed_application(
            difficulty="MEDIUM", role_label="LEAD", duration_hours=2,
        )
        application = scenario["application"]
        organizer = scenario["organizer"]
        volunteer = scenario["volunteer"]
        # Bring volunteer to exactly 2.50 hours.
        adj = file_hour_adjustment(
            application=application, organizer=organizer, delta_hours=0.50
        )
        approve_hour_adjustment(adj["id"])

        template = create_certificate_template(
            min_hours=2.50, min_completed_activities=1,
        )
        res = api.issue_certificate(
            issue_certificate_payload(
                template_id=template["id"], volunteer_id=volunteer["id"]
            ),
            make_skilladmin_headers(),
        )
        data = validate_success(res, expected_status=201)
        assert_certificate(data)
        assert data["status"] == "ISSUED"
        assert data["hours_at_issuance"] == pytest.approx(2.50, abs=0.005)

    def test_issuance_with_hours_below_threshold_rejected(self, api):
        """PRD §3.9: 'a volunteer 0.01 hours below min_hours is not,
        and the issuance is rejected with ERR_NOT_ELIGIBLE.'

        # difficulty: boundary_precision_check/certificate_min_hours_inclusive_boundary_on_certificates_endpoint
        """
        scenario = setup_completed_application(
            difficulty="MEDIUM", role_label="LEAD", duration_hours=2,
        )
        # Volunteer.total_service_hours == 2.00 (no adjustment).
        volunteer = scenario["volunteer"]
        template = create_certificate_template(
            min_hours=2.50, min_completed_activities=1,
        )
        res = api.issue_certificate(
            issue_certificate_payload(
                template_id=template["id"], volunteer_id=volunteer["id"]
            ),
            make_skilladmin_headers(),
        )
        validate_error(res, "ERR_NOT_ELIGIBLE")

    def test_duplicate_issuance_rejected(self, api):
        """PRD §3.9: 'Additionally, no certificate of the same
        (volunteer_id, template_id) may already exist in a state other
        than REISSUED or REVOKED; an attempted re-issuance into a slot
        that is already occupied is rejected with
        ERR_CERTIFICATE_ALREADY_ISSUED.'"""
        scenario = setup_completed_application(role_label="LEAD")
        volunteer = scenario["volunteer"]
        template = create_certificate_template(
            min_hours=1.00, min_completed_activities=1,
        )
        first = api.issue_certificate(
            issue_certificate_payload(
                template_id=template["id"], volunteer_id=volunteer["id"]
            ),
            make_skilladmin_headers(),
        )
        validate_success(first, expected_status=201)
        res = api.issue_certificate(
            issue_certificate_payload(
                template_id=template["id"], volunteer_id=volunteer["id"]
            ),
            make_skilladmin_headers(),
        )
        validate_error(res, "ERR_CERTIFICATE_ALREADY_ISSUED")

    def test_issuance_appends_audit_and_partner_sync(self, api):
        """PRD §3.9: 'Issuance also appends an AuditLog with action_type
        of CERTIFICATE_ISSUE and emits a PartnerSyncEvent on channel
        PARTNER_ORG with event_type of CERTIFICATE_ISSUED.'"""
        scenario = setup_completed_application(role_label="LEAD")
        volunteer = scenario["volunteer"]
        template = create_certificate_template(
            min_hours=1.00, min_completed_activities=1,
        )
        cert = issue_certificate(template=template, volunteer=volunteer)
        # Audit
        logs = list_audit_logs(action_type="CERTIFICATE_ISSUE", limit=100)
        assert len(find_audit_logs(logs, target_id=cert["id"])) >= 1
        # Sync
        events = list_partner_sync_events(
            event_type="CERTIFICATE_ISSUED", limit=100
        )
        assert len(find_partner_sync_events(events, channel="PARTNER_ORG")) >= 1


class TestBatchIssuance:
    def test_batch_partial_success(self, api):
        """PRD §3.9: 'Batch issuance accepts a single template_id plus
        a volunteer_ids list. The server performs the eligibility check
        independently per volunteer in the list; eligible volunteers
        are issued exactly as in the single-issue flow ...; ineligible
        volunteers are skipped and reported with a reason. The batch
        response is a partial-success object listing the issued and
        the skipped subsets — the request as a whole succeeds at HTTP
        200 even when some volunteers were skipped.'"""
        # Eligible volunteer.
        s_eligible = setup_completed_application(role_label="LEAD")
        v_eligible = s_eligible["volunteer"]
        # Ineligible volunteer (no completed activity).
        v_ineligible = create_verified_volunteer()

        template = create_certificate_template(
            min_hours=1.00, min_completed_activities=1,
        )
        res = api.issue_certificates_batch(
            issue_certificates_batch_payload(
                template_id=template["id"],
                volunteer_ids=[v_eligible["id"], v_ineligible["id"]],
            ),
            make_skilladmin_headers(),
        )
        data = validate_success(res, expected_status=200)
        # PRD says response lists issued + skipped subsets. We don't
        # assert exact key names beyond what PRD names verbatim:
        # 'issued and the skipped subsets'. Accept either 'issued' or
        # 'skipped' wording variants but at least one of each must be
        # present in the response data.
        as_str = str(data)
        assert "issued" in as_str.lower()
        assert "skipped" in as_str.lower()


class TestReissueAndRevoke:
    def test_reissue_creates_new_marks_old_reissued(self, api):
        """PRD §3.9: 'Reissuance creates a new Certificate row carrying
        the same template_id and volunteer_id, a fresh serial_number,
        and refreshed hours_at_issuance and activities_at_issuance
        snapshots taken from the volunteer's current totals, with the
        new row in status of ISSUED. The original certificate's status
        is moved from ISSUED to REISSUED, and its
        replacement_serial_number is set to point at the new row's
        serial_number.'"""
        scenario = setup_completed_application(role_label="LEAD")
        volunteer = scenario["volunteer"]
        template = create_certificate_template(
            min_hours=1.00, min_completed_activities=1,
        )
        original = issue_certificate(template=template, volunteer=volunteer)
        # The reissue endpoint returns the new Certificate row.
        res = api.reissue_certificate(original["id"], make_skilladmin_headers())
        new_cert = validate_success(res, expected_status=201)
        assert_certificate(new_cert)
        assert new_cert["status"] == "ISSUED"
        assert new_cert["serial_number"] != original["serial_number"]
        # Verify the old row via /certificates/verify/{serial}.
        verify_res = api.verify_certificate(
            original["serial_number"], make_skilladmin_headers()
        )
        old = validate_success(verify_res, expected_status=200)
        assert old["status"] == "REISSUED"
        assert old.get("replacement_serial_number") == new_cert["serial_number"]

    def test_revoke_advances_to_revoked_terminal(self, api, skilladmin_headers):
        """PRD §3.9: 'A SkillAdmin may also revoke an ISSUED
        certificate, advancing status to REVOKED (terminal) and
        appending an AuditLog row with action_type of
        CERTIFICATE_REVOKE.'"""
        scenario = setup_completed_application(role_label="LEAD")
        volunteer = scenario["volunteer"]
        template = create_certificate_template(
            min_hours=1.00, min_completed_activities=1,
        )
        cert = issue_certificate(template=template, volunteer=volunteer)
        res = api.revoke_certificate(cert["id"], skilladmin_headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "REVOKED"
        # Audit log appended.
        logs = list_audit_logs(action_type="CERTIFICATE_REVOKE", limit=100)
        assert len(find_audit_logs(logs, target_id=cert["id"])) >= 1


class TestVerifyEndpoint:
    def test_verify_returns_certificate_with_status(self, api):
        """PRD §3.9: 'A public-verification capability — accessible to
        all three roles — looks up a certificate by its serial_number
        (taken as a path parameter) and returns the row, including its
        current status.'"""
        scenario = setup_completed_application(role_label="LEAD")
        volunteer = scenario["volunteer"]
        template = create_certificate_template(
            min_hours=1.00, min_completed_activities=1,
        )
        cert = issue_certificate(template=template, volunteer=volunteer)
        res = api.verify_certificate(cert["serial_number"], make_skilladmin_headers())
        data = validate_success(res, expected_status=200)
        assert data["status"] == "ISSUED"
        assert data["serial_number"] == cert["serial_number"]
