"""Role permissions: the write each role owns, and every crossing that is refused."""

from test_helpers import (
    ENGINEER_HEADERS,
    OFFICER_HEADERS,
    STARTUP_CLOCK,
    add_design_factor,
    age_screen_payload,
    api_client,
    assert_instant,
    child_data_record_payload,
    create_activity,
    create_age_screen,
    create_consent,
    create_program,
    create_rights_request,
    create_service,
    granted_consent,
    make_assessor_headers,
    make_certifier_headers,
    make_parent_headers,
    mixed_audience_service,
    online_service_payload,
    parental_notice_payload,
    published_notice,
    read_service,
    run_determination,
    safe_harbor_assessment_payload,
    service_version,
    set_assessment_status,
    validate_error,
    validate_paginated,
    validate_success,
)

# A `Parent` identity that names no consent record at all.
UNBOUND_PARENT_ID = "00000000-0000-4000-8000-000000000420"


class TestEachRoleOwnsOneWrite:
    """Five roles, five writes, and none of them is interchangeable."""

    def test_01_officer_engineer_parent_assessor_and_certifier_each_do_their_own(self):
        """The whole segregation of duties exercised once, end to end.

        "A `ComplianceOfficer` owns determination, evidence, notices, activities, the consent
        lifecycle, integration audit decisions, retention policy, the posture override, the
        logical clock and safe harbor program registration — but may never record collected
        child data and may never author an age screen. A `PrivacyEngineer` builds the age
        screen and performs the actual collection ... A `Parent` exercises parental rights
        only. A `SafeHarborAssessor` prepares assessments; a `SafeHarborCertifier` reviews and
        certifies them".

        Design: Corner/rbac/each_role_performs_the_write_that_only_it_may_perform
        """
        service = create_service(name="Five Roles Kids")
        service_id = service["id"]
        assert service["version"] == 1, (
            f"only a ComplianceOfficer could have registered it, got {service['version']}"
        )
        add_design_factor(service_id, "SUBJECT_MATTER", "MODERATE")
        determined = run_determination(service_id)
        assert determined["determination_status"] == "MIXED_AUDIENCE"

        notice = published_notice(service_id)
        consent = granted_consent(
            service_id,
            notice["id"],
            "guardian.ii@x.test",
            "child-621",
            consent_method="EMAIL_PLUS",
            grant_body={"secondary_confirmation_code": "SEC-II-1"},
        )
        assert consent["status"] == "GRANTED"
        program = create_program(program_name="Five Roles Seal", regulator_approved=True)
        assert program["annual_assessment_required"] is True
        assert program["assessment_validity_days"] == 365

        screen = create_age_screen(service_id)
        assert screen["status"] == "DRAFT", (
            f"the PrivacyEngineer alone may declare a screen, got {screen['status']}"
        )

        rights_request = create_rights_request(
            service_id, consent["id"], "REVIEW", "guardian.ii@x.test"
        )
        assert rights_request["status"] == "SUBMITTED", (
            "the Parent alone may open a rights request against its own consent, got "
            f"{rights_request['status']}"
        )

        assessor = make_assessor_headers("assessor-7")
        assessment = validate_success(
            api_client.create_safe_harbor_assessment(
                safe_harbor_assessment_payload(service_id, program["id"], 2026), assessor
            ),
            201,
        )
        assert assessment["status"] == "DRAFT"
        assert assessment["preparer_user_id"] == "assessor-7", (
            "the acting assessor becomes the preparer, got "
            f"{assessment['preparer_user_id']}"
        )
        submitted = set_assessment_status(
            assessment["id"], "SUBMITTED", assessor, findings_open_count=0
        )
        assert submitted["status"] == "SUBMITTED"

        certifier = make_certifier_headers("certifier-7")
        certified = validate_success(
            api_client.certify_safe_harbor_assessment(assessment["id"], certifier)
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["certifier_user_id"] == "certifier-7", (
            f"the certifier is recorded separately, got {certified['certifier_user_id']}"
        )
        assert certified["certifier_user_id"] != certified["preparer_user_id"]
        assert_instant(certified["certified_at"], STARTUP_CLOCK, "certified_at")
        assert_instant(certified["expires_at"], "2027-08-01T00:00:00Z", "expires_at")

        seen_by_certifier = validate_success(
            api_client.get_online_service(service_id, certifier)
        )
        assert seen_by_certifier["safe_harbor_status"] == "CERTIFIED", (
            "the certifier may read the service it just certified, got "
            f"{seen_by_certifier['safe_harbor_status']}"
        )
        assert_instant(
            seen_by_certifier["safe_harbor_expires_at"],
            "2027-08-01T00:00:00Z",
            "safe_harbor_expires_at",
        )


class TestOperatorRolesDoNotOverlapOnWrites:
    """The officer may not screen or collect; the engineer may not register or consent."""

    def test_02_every_crossing_of_the_collection_duty_boundary_is_refused(self):
        """Five refusals, and not one row left behind.

        The officer "may never record collected child data and may never author an age
        screen", while the engineer "may not approve its own screen and may not touch consent,
        notices or audits". Endpoint authorisation is check "2. **Endpoint authorisation.** The
        acting role appears in the endpoint's authorised-role list in §4, else
        `ERR_ROLE_NOT_PERMITTED` (403)", which precedes the optimistic-concurrency check.

        Design: Corner/rbac/officer_and_engineer_cannot_cross_the_collection_duty_boundary_403
        """
        service = mixed_audience_service(name="Duty Boundary Kids")
        service_id = service["id"]
        notice = published_notice(service_id)
        activity = create_activity(service_id, participation_required_elements=["SCREEN_NAME"])
        consent = create_consent(
            service_id, notice["id"], "guardian.jj@x.test", "child-622"
        )
        assert consent["status"] == "INITIATED"

        validate_error(
            api_client.create_age_screen(age_screen_payload(service_id), OFFICER_HEADERS),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )
        validate_error(
            api_client.create_child_data_record(
                child_data_record_payload(service_id, consent["id"], activity["id"]),
                OFFICER_HEADERS,
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )
        validate_error(
            api_client.create_online_service(
                online_service_payload(
                    name="Engineer Service", operator_organization="Boundary Media"
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )
        validate_error(
            api_client.create_parental_notice(
                parental_notice_payload(
                    service_id,
                    service_version(service_id),
                    notice_label="Engineer notice",
                    delivery_channel="EMAIL",
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )
        validate_error(
            api_client.set_consent_request_status(
                consent["id"], {"to_status": "NOTICE_DELIVERED"}, ENGINEER_HEADERS
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )

        _, screen_meta = validate_paginated(
            api_client.list_service_age_screens(
                service_id, ENGINEER_HEADERS, {"limit": 100, "offset": 0}
            )
        )
        assert screen_meta["total_count"] == 0, (
            f"the refused screen was never created, got {screen_meta['total_count']}"
        )
        _, record_meta = validate_paginated(
            api_client.list_child_data_records(
                ENGINEER_HEADERS, {"service_id": service_id, "limit": 100, "offset": 0}
            )
        )
        assert record_meta["total_count"] == 0, (
            f"the refused collection was never recorded, got {record_meta['total_count']}"
        )
        still_initiated = validate_success(
            api_client.get_consent_request(consent["id"], OFFICER_HEADERS)
        )
        assert still_initiated["status"] == "INITIATED", (
            "the engineer's refused transition did not advance the consent, got "
            f"{still_initiated['status']}"
        )


class TestOutsiderRolesCannotReachOperatorEndpoints:
    """The endpoint role gate answers before any identity binding is consulted."""

    def test_03_a_parent_and_the_two_safe_harbor_roles_are_refused_at_the_door(self):
        """A 403 arrives even when the parent identity names no consent at all.

        Checks run "2. **Endpoint authorisation.** The acting role appears in the endpoint's
        authorised-role list in §4, else `ERR_ROLE_NOT_PERMITTED` (403). 3. **Parent
        ownership.** A `Parent` addresses only its own consent record and its own rights
        requests, else `ERR_NOT_CONSENT_HOLDER` (403)", in that order, and "A later check never
        masks an earlier one." "A `Parent` exercises parental rights only."

        Design: Corner/rbac/parent_and_safe_harbor_roles_cannot_reach_operator_endpoints_403
        """
        service = create_service(name="Outsider Kids")
        service_id = service["id"]
        program = create_program(program_name="Outsider Seal", regulator_approved=True)
        parent = make_parent_headers(UNBOUND_PARENT_ID)
        assessor = make_assessor_headers("assessor-8")
        certifier = make_certifier_headers("certifier-8")

        validate_error(
            api_client.get_online_service(service_id, parent),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )
        validate_error(
            api_client.set_posture(service_id, {"posture_override": "OPEN"}, parent),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )
        validate_error(
            api_client.create_online_service(
                online_service_payload(
                    name="Assessor Service", operator_organization="Outsider Media"
                ),
                assessor,
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )
        validate_error(
            api_client.create_safe_harbor_assessment(
                safe_harbor_assessment_payload(service_id, program["id"], 2026), certifier
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )

        _, service_meta = validate_paginated(
            api_client.list_online_services(assessor, {"limit": 100, "offset": 0})
        )
        assert service_meta["total_count"] == 1, (
            "the assessor may list services, and nothing was created, got "
            f"{service_meta['total_count']}"
        )
        _, assessment_meta = validate_paginated(
            api_client.list_safe_harbor_assessments(
                certifier, {"service_id": service_id, "limit": 100, "offset": 0}
            )
        )
        assert assessment_meta["total_count"] == 0, (
            f"the refused assessment was never opened, got {assessment_meta['total_count']}"
        )

        after = read_service(service_id)
        assert after["safe_harbor_status"] == "NOT_ENROLLED"
        assert after["compliance_posture"] == "OPEN"
