"""Related service lifecycle — PRD §3.3, §3.6.

Covers: propose, activate (with all gates), suspend, resume, complete
(via supersession), at-most-one-active-per-(iep, service_type),
service-minutes cap.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    activate_related_service,
    activate_related_service_payload,
    assert_related_service,
    create_related_service_consent_approved,
    propose_related_service,
    resume_related_service,
    setup_active_iep,
    setup_active_iep_with_active_service,
    suspend_related_service,
    validate_error,
    validate_success,
)


class TestProposeRelatedService:

    def test_propose_service_starts_in_proposed(self, api):
        """PRD §3.3: "Related services are proposed in the same DRAFT
        window through a separate path described in §3.4; only their
        proposal happens here ... [PRD §3.6:] After a service is
        proposed in PROPOSED state".

        Claim: a newly proposed service is in PROPOSED.
        """
        district, student, _eval, iep, _goal = setup_active_iep()
        service = propose_related_service(
            district["id"], student["id"], iep["id"],
            service_type="OT", minutes_per_week=60,
            location_setting="PULL_OUT",
        )
        assert_related_service(service)
        assert service["status"] == "PROPOSED"
        assert service["service_type"] == "OT"
        assert service["minutes_per_week"] == 60
        assert service["location_setting"] == "PULL_OUT"


class TestServiceActivationPreconditions:

    def test_activate_without_approved_consent_rejected(self, api):
        """PRD §3.6: "the consent_id resolve to a ParentalConsent in
        APPROVED with scope=RELATED_SERVICE (else
        ERR_SERVICE_CONSENT_NOT_APPROVED)".

        Claim: activating with a consent_id whose status is PENDING
        → ERR_SERVICE_CONSENT_NOT_APPROVED.
        """
        from test_helpers import (
            TEST_USERS,
            create_consent_payload,
        )
        district, student, _eval, iep, _goal = setup_active_iep()
        service = propose_related_service(
            district["id"], student["id"], iep["id"],
        )
        # Create the RELATED_SERVICE consent but do NOT approve it.
        consent_resp = api.create_parental_consent(
            district["id"], student["id"],
            create_consent_payload(
                scope="RELATED_SERVICE",
                target_resource_type="RelatedService",
                target_resource_id=service["id"],
            ),
            TEST_USERS["provider_headers"],
        )
        consent = consent_resp.json()["data"]
        res = api.activate_related_service(
            district["id"], student["id"], iep["id"], service["id"],
            activate_related_service_payload(consent_id=consent["id"]),
            TEST_USERS["provider_headers"],
        )
        validate_error(res, "ERR_SERVICE_CONSENT_NOT_APPROVED")

    def test_activate_non_proposed_service_rejected(self, api):
        """PRD §3.6: "the service be in PROPOSED (else
        ERR_SERVICE_NOT_PROPOSED)".

        Claim: re-activating an already-ACTIVE service →
        ERR_SERVICE_NOT_PROPOSED.
        """
        from test_helpers import TEST_USERS
        district, student, iep, service, consent = (
            setup_active_iep_with_active_service()
        )
        res = api.activate_related_service(
            district["id"], student["id"], iep["id"], service["id"],
            activate_related_service_payload(consent_id=consent["id"]),
            TEST_USERS["provider_headers"],
        )
        validate_error(res, "ERR_SERVICE_NOT_PROPOSED")


class TestServiceTypeUniqueness:

    def test_second_active_same_service_type_rejected(self, api):
        """PRD §3.6: "no other RelatedService on the same iep_id with
        the same service_type be in ACTIVE (else
        ERR_SERVICE_TYPE_ALREADY_ACTIVE)".

        Claim: with one OT service already ACTIVE, proposing AND
        activating a second OT service is rejected.
        """
        district, student, iep, _service_a, _consent_a = (
            setup_active_iep_with_active_service(service_type="OT")
        )
        # Propose a second OT service and try to activate it.
        service_b = propose_related_service(
            district["id"], student["id"], iep["id"],
            service_type="OT", minutes_per_week=30,
        )
        consent_b = create_related_service_consent_approved(
            district["id"], student["id"], service_b["id"],
            parent_user_id=student["parent_user_id"],
        )
        from test_helpers import TEST_USERS
        res = api.activate_related_service(
            district["id"], student["id"], iep["id"], service_b["id"],
            activate_related_service_payload(consent_id=consent_b["id"]),
            TEST_USERS["provider_headers"],
        )
        validate_error(res, "ERR_SERVICE_TYPE_ALREADY_ACTIVE")

    def test_different_service_types_coexist(self, api):
        """PRD §3.6: at-most-one-ACTIVE is per (iep_id, service_type),
        so different service_type values may all be ACTIVE on the same
        IEP. PRD §3.6 says only "no other RelatedService on the same
        iep_id with the same service_type be in ACTIVE".

        Claim: OT and SPEECH may both be ACTIVE on the same IEP.
        """
        district, student, iep, _service_a, _consent_a = (
            setup_active_iep_with_active_service(service_type="OT")
        )
        service_b = propose_related_service(
            district["id"], student["id"], iep["id"],
            service_type="SPEECH", minutes_per_week=30,
        )
        consent_b = create_related_service_consent_approved(
            district["id"], student["id"], service_b["id"],
            parent_user_id=student["parent_user_id"],
        )
        from test_helpers import TEST_USERS
        res = api.activate_related_service(
            district["id"], student["id"], iep["id"], service_b["id"],
            activate_related_service_payload(consent_id=consent_b["id"]),
            TEST_USERS["provider_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "ACTIVE"


class TestServiceMinutesCap:

    def test_service_minutes_exceeding_instructional_cap_rejected(
        self, api,
    ):
        """PRD §3.6: "the resulting special_education_minutes_per_week
        after activation be at most total_instructional_minutes_per_week
        (else ERR_SERVICE_MINUTES_EXCEED_INSTRUCTIONAL_TIME)".

        Claim: with total_instructional_minutes_per_week=1500,
        activating a service with minutes_per_week=2000 →
        ERR_SERVICE_MINUTES_EXCEED_INSTRUCTIONAL_TIME (422).
        """
        district, student, _eval, iep, _goal = setup_active_iep(
            total_instructional_minutes_per_week=1500,
            total_school_day_minutes_per_week=1875,
        )
        service = propose_related_service(
            district["id"], student["id"], iep["id"],
            service_type="OT", minutes_per_week=2000,
        )
        consent = create_related_service_consent_approved(
            district["id"], student["id"], service["id"],
            parent_user_id=student["parent_user_id"],
        )
        from test_helpers import TEST_USERS
        res = api.activate_related_service(
            district["id"], student["id"], iep["id"], service["id"],
            activate_related_service_payload(consent_id=consent["id"]),
            TEST_USERS["provider_headers"],
        )
        validate_error(
            res, "ERR_SERVICE_MINUTES_EXCEED_INSTRUCTIONAL_TIME",
        )


class TestSuspendResumeCycle:

    def test_suspend_active_service_succeeds(self, api):
        """PRD §3.6: "A service may be moved from ACTIVE to SUSPENDED
        in two ways: a RelatedServiceProvider may explicitly suspend
        it".

        Claim: explicit suspend on an ACTIVE service moves it to
        SUSPENDED.
        """
        district, student, iep, service, _consent = (
            setup_active_iep_with_active_service()
        )
        result = suspend_related_service(
            district["id"], student["id"], iep["id"], service["id"],
        )
        assert result["status"] == "SUSPENDED"

    def test_resume_suspended_service_moves_to_active(self, api):
        """PRD §3.6: "A SUSPENDED service can be resumed back to
        ACTIVE by the RelatedServiceProvider by supplying a
        consent_id in the request body."

        Claim: resume after suspend returns the service to ACTIVE
        with the same consent.
        """
        district, student, iep, service, consent = (
            setup_active_iep_with_active_service()
        )
        suspend_related_service(
            district["id"], student["id"], iep["id"], service["id"],
        )
        result = resume_related_service(
            district["id"], student["id"], iep["id"], service["id"],
            consent_id=consent["id"],
        )
        assert result["status"] == "ACTIVE"

    def test_suspend_non_active_service_rejected(self, api):
        """PRD §3.6: "the service must be in ACTIVE (else
        ERR_SERVICE_NOT_ACTIVE)".

        Claim: suspending a PROPOSED service fails.
        """
        from test_helpers import TEST_USERS
        district, student, _eval, iep, _goal = setup_active_iep()
        service = propose_related_service(
            district["id"], student["id"], iep["id"],
        )
        res = api.suspend_related_service(
            district["id"], student["id"], iep["id"], service["id"],
            TEST_USERS["provider_headers"],
        )
        validate_error(res, "ERR_SERVICE_NOT_ACTIVE")

    def test_resume_non_suspended_service_rejected(self, api):
        """PRD §3.6: "Resume requires the service to be in SUSPENDED
        (else ERR_SERVICE_NOT_SUSPENDED)".

        Claim: resuming an ACTIVE service fails.
        """
        from test_helpers import TEST_USERS
        district, student, iep, service, consent = (
            setup_active_iep_with_active_service()
        )
        res = api.resume_related_service(
            district["id"], student["id"], iep["id"], service["id"],
            {"consent_id": consent["id"]},
            TEST_USERS["provider_headers"],
        )
        validate_error(res, "ERR_SERVICE_NOT_SUSPENDED")
