"""Authentication, RBAC, and ownership checks (PRD §2.1)."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    apply_to_activity_payload,
    api_client,
    build_user_headers,
    create_activity_payload,
    create_skill_payload,
    create_verified_volunteer,
    create_volunteer_payload,
    file_hour_adjustment_payload,
    issue_certificate_payload,
    make_organizer_headers,
    make_skilladmin_headers,
    make_volunteer_headers,
    setup_completed_application,
    setup_recruiting_activity,
    validate_error,
    validate_success,
)


class TestAuthHeaderPresence:
    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'A request that is missing either header, or whose
        X-User-Role value is not one of the three valid role names, is
        rejected with ERR_UNAUTHENTICATED.'"""
        bad = {"X-User-Role": "SkillAdmin"}
        res = api.create_volunteer(create_volunteer_payload(), bad)
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: 'A request that is missing either header, or whose
        X-User-Role value is not one of the three valid role names, is
        rejected with ERR_UNAUTHENTICATED.'"""
        bad = {"X-User-ID": "skilladmin-001"}
        res = api.create_volunteer(create_volunteer_payload(), bad)
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_unrecognized_role_value_rejected(self, api):
        """PRD §2.1: 'A request that is missing either header, or whose
        X-User-Role value is not one of the three valid role names, is
        rejected with ERR_UNAUTHENTICATED.'"""
        bad = build_user_headers("op-1", "PlatformOverlord")
        res = api.create_volunteer(create_volunteer_payload(), bad)
        validate_error(res, "ERR_UNAUTHENTICATED")


class TestRBAC:
    """Endpoint-role mismatches surface as ERR_FORBIDDEN per PRD §2.1.

    PRD §2.1: 'A request whose role is recognized but is not in the
    endpoint's authorized list is rejected with ERR_FORBIDDEN.'
    """

    def test_create_volunteer_requires_skilladmin(self, api):
        """PRD §4: 'POST /volunteers ... Authorized Role(s): SkillAdmin.'
        PRD §2.1: 'A request whose role is recognized but is not in the
        endpoint's authorized list is rejected with ERR_FORBIDDEN.'"""
        headers = build_user_headers("v-1", "Volunteer")
        res = api.create_volunteer(create_volunteer_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_create_skill_requires_skilladmin(self, api):
        """PRD §4: 'POST /skills ... Authorized Role(s): SkillAdmin.'"""
        headers = build_user_headers("o-1", "Organizer")
        res = api.create_skill(create_skill_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_create_activity_requires_organizer(self, api, skilladmin_headers):
        """PRD §4: 'POST /activities ... Authorized Role(s): Organizer.'"""
        res = api.create_activity(create_activity_payload(), skilladmin_headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_apply_requires_volunteer(self, api, skilladmin_headers):
        """PRD §4: 'POST /applications ... Authorized Role(s): Volunteer.'"""
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=NON_EXISTENT_UUID),
            skilladmin_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_approve_application_requires_organizer(self, api, skilladmin_headers):
        """PRD §4: 'POST /applications/{id}/approve ... Authorized Role(s): Organizer.'"""
        res = api.approve_application(NON_EXISTENT_UUID, skilladmin_headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_file_hour_adjustment_requires_organizer(self, api, skilladmin_headers):
        """PRD §4: 'POST /hour-adjustments ... Authorized Role(s): Organizer.'"""
        res = api.file_hour_adjustment(
            file_hour_adjustment_payload(application_id=NON_EXISTENT_UUID),
            skilladmin_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_approve_hour_adjustment_requires_skilladmin(self, api):
        """PRD §4: 'POST /hour-adjustments/{id}/approve ... Authorized Role(s): SkillAdmin.'"""
        headers = build_user_headers("o-1", "Organizer")
        res = api.approve_hour_adjustment(NON_EXISTENT_UUID, headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_issue_certificate_requires_skilladmin(self, api):
        """PRD §4: 'POST /certificates ... Authorized Role(s): SkillAdmin.'"""
        headers = build_user_headers("o-1", "Organizer")
        res = api.issue_certificate(
            issue_certificate_payload(
                template_id=NON_EXISTENT_UUID, volunteer_id=NON_EXISTENT_UUID
            ),
            headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_advance_clock_requires_skilladmin(self, api):
        """PRD §4: 'POST /_clock/advance ... Authorized Role(s): SkillAdmin.'"""
        headers = build_user_headers("v-1", "Volunteer")
        res = api.advance_clock("2030-03-01T08:00:00.000Z", headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_audit_logs_listing_requires_skilladmin(self, api):
        """PRD §4: 'GET /audit-logs ... Authorized Role(s): SkillAdmin.'"""
        headers = build_user_headers("v-1", "Volunteer")
        res = api.list_audit_logs(headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_partner_sync_events_listing_requires_skilladmin(self, api):
        """PRD §4: 'GET /partner-sync-events ... Authorized Role(s): SkillAdmin.'"""
        headers = build_user_headers("v-1", "Volunteer")
        res = api.list_partner_sync_events(headers)
        validate_error(res, "ERR_FORBIDDEN")


class TestPathExistence:
    """PRD §2.6: 'each segment is validated left to right against the
    underlying row's existence; the first segment that does not resolve
    causes the request to be rejected with ERR_NOT_FOUND.'
    """

    def test_get_volunteer_unknown_id_404(self, api, skilladmin_headers):
        """PRD §2.6: 'each segment is validated left to right against the
        underlying row's existence; the first segment that does not
        resolve causes the request to be rejected with ERR_NOT_FOUND.'"""
        res = api.get_volunteer(NON_EXISTENT_UUID, skilladmin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_activity_unknown_id_404(self, api, skilladmin_headers):
        """PRD §2.6: 'each segment is validated left to right against the
        underlying row's existence; the first segment that does not
        resolve causes the request to be rejected with ERR_NOT_FOUND.'"""
        res = api.get_activity(NON_EXISTENT_UUID, skilladmin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_apply_to_unknown_activity_404(self, api):
        """PRD §2.6: 'The same ERR_NOT_FOUND is returned when a request
        body references a foreign key — a Skill.id, an Activity.id, an
        ActivityRole.id, a PointMallItem.id, a CertificateTemplate.id,
        or a Volunteer.id — that does not resolve to a stored row.'"""
        v = create_verified_volunteer()
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=NON_EXISTENT_UUID),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_NOT_FOUND")


class TestOwnershipChecks:
    """PRD §2.1 entity-backed ownership rules.

    Volunteer: 'ownership checks on any resource that references a
    Volunteer ... compare the resource's foreign-key field to X-User-ID
    and reject mismatches with ERR_FORBIDDEN.'

    Organizer: 'ownership checks on activities compare
    Activity.organizer_id to X-User-ID.'
    """

    def test_volunteer_cannot_withdraw_someone_elses_application(self, api):
        """PRD §2.1: 'When X-User-Role is Volunteer, X-User-ID is the id
        of the acting Volunteer; ownership checks on any resource that
        references a Volunteer (for example Application.volunteer_id,
        RedemptionOrder.volunteer_id, or VolunteerSkill.volunteer_id)
        compare the resource's foreign-key field to X-User-ID and reject
        mismatches with ERR_FORBIDDEN.'"""
        # Build: Volunteer A owns the Application; Volunteer B tries to withdraw.
        organizer, activity, _ = setup_recruiting_activity()
        owner = create_verified_volunteer()
        impostor = create_verified_volunteer()
        application = api_client.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(owner["id"]),
        )
        body = application.json()
        app = body["data"]
        res = api.withdraw_application(app["id"], make_volunteer_headers(impostor["id"]))
        validate_error(res, "ERR_FORBIDDEN")

    def test_organizer_cannot_submit_another_organizers_activity(self, api):
        """PRD §2.1: 'When X-User-Role is Organizer, ... ownership checks
        on activities compare Activity.organizer_id to X-User-ID.'"""
        # Build: Organizer A creates DRAFT Activity; Organizer B tries to /submit.
        from test_helpers import create_draft_activity, setup_organizer
        owner = setup_organizer()
        impostor = setup_organizer()
        activity = create_draft_activity(organizer=owner)
        res = api.submit_activity(activity["id"], make_organizer_headers(impostor["id"]))
        validate_error(res, "ERR_FORBIDDEN")
