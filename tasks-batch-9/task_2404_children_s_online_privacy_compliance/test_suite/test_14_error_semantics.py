"""Error semantics: authentication, the two 403 flavours, ownership and the 404 codes."""

from test_helpers import (
    ENGINEER_HEADERS,
    NON_EXISTENT_UUID,
    OFFICER_HEADERS,
    api_client,
    consent_request_payload,
    create_age_screen,
    create_notice,
    create_service,
    child_data_record_payload,
    granted_consent,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    make_assessor_headers,
    make_parent_headers,
    mixed_audience_service,
    parental_rights_request_payload,
    published_notice,
    read_age_screen,
    read_notice,
    read_service,
    safe_harbor_assessment_payload,
    service_version,
    set_screen_status,
    validate_error,
    validate_paginated,
    validate_success,
)

# A second unresolvable identifier, so that one body can carry two unknown keys.
ANOTHER_MISSING_UUID = "00000000-0000-4000-8000-000000000415"


class TestAuthenticationPrecedesEverything:
    """A malformed principal is reported before any resolution or payload check."""

    def test_01_missing_or_unrecognised_identity_is_always_401(self):
        """Three malformed principals, and neither a 404 nor a 422 can pre-empt them.

        "Every request must carry two mandatory headers: `X-User-ID`, identifying the acting
        principal, and `X-User-Role`, declaring the capacity in which it acts. The system
        recognises exactly five roles ... If either header is absent, or if `X-User-Role` is
        not one of those five exact strings, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)." Checks run in strict order beginning "1.
        **Authentication.** Headers present and the role recognised, else
        `ERR_UNAUTHENTICATED` (401)", and "A later check never masks an earlier one."

        Design: Corner/errors/request_missing_x_user_role_header_returns_401_unauthenticated
        """
        service = create_service(name="Auth Gate Kids")
        service_id = service["id"]

        validate_error(
            api_client.get_online_service(service_id, headers_without_role()),
            "ERR_UNAUTHENTICATED",
            401,
        )
        validate_error(
            api_client.get_online_service(service_id, headers_without_user_id()),
            "ERR_UNAUTHENTICATED",
            401,
        )
        validate_error(
            api_client.get_online_service(service_id, headers_with_undeclared_role()),
            "ERR_UNAUTHENTICATED",
            401,
        )

        validate_error(
            api_client.get_online_service(NON_EXISTENT_UUID, headers_without_role()),
            "ERR_UNAUTHENTICATED",
            401,
        )
        validate_error(
            api_client.create_online_service(
                {"name": "Should Never Exist"}, headers_without_role()
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )

        _, meta = validate_paginated(
            api_client.list_online_services(OFFICER_HEADERS, {"limit": 100, "offset": 0})
        )
        assert meta["total_count"] == 1, (
            f"none of the refused calls created anything, got {meta['total_count']}"
        )


class TestEndpointRoleVersusTransitionRole:
    """Two 403 codes separate endpoint authority from per-transition authority."""

    def test_02_the_publish_endpoint_and_the_screen_edges_report_different_codes(self):
        """An absent role is one code; a listed-but-wrong role is another.

        "If both headers are well-formed but the acting role is not listed among the
        authorised roles for the endpoint in §4, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." "Where the acting role is authorised for the
        endpoint but not for the specific transition requested, the rejection is
        `ERR_TRANSITION_ROLE_NOT_PERMITTED` (HTTP 403)." Submission "is reserved to the
        `PrivacyEngineer`", while "A `ComplianceOfficer` moves the screen
        `IN_REVIEW → ACTIVE`, and no other role may".

        Design: Corner/errors/notice_publish_by_privacy_engineer_returns_403_role_not_permitted
        """
        service = mixed_audience_service(name="Role Split Kids")
        service_id = service["id"]
        notice = create_notice(service_id)
        screen = create_age_screen(service_id)
        assert notice["status"] == "DRAFT"
        assert screen["neutrality_violation_codes"] == []

        validate_error(
            api_client.publish_parental_notice(notice["id"], ENGINEER_HEADERS),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )
        validate_error(
            api_client.set_age_screen_status(
                screen["id"], {"to_status": "IN_REVIEW"}, OFFICER_HEADERS
            ),
            "ERR_TRANSITION_ROLE_NOT_PERMITTED",
            403,
        )

        in_review = set_screen_status(screen["id"], "IN_REVIEW", ENGINEER_HEADERS)
        assert in_review["status"] == "IN_REVIEW", (
            f"the declared actor performs the edge, got {in_review['status']}"
        )

        validate_error(
            api_client.set_age_screen_status(
                screen["id"], {"to_status": "ACTIVE"}, ENGINEER_HEADERS
            ),
            "ERR_TRANSITION_ROLE_NOT_PERMITTED",
            403,
        )
        activated = set_screen_status(screen["id"], "ACTIVE", OFFICER_HEADERS)
        assert activated["status"] == "ACTIVE", (
            "the roles swap on the next edge, got " f"{activated['status']}"
        )
        assert read_age_screen(service_id, screen["id"])["status"] == "ACTIVE"
        assert read_notice(service_id, notice["id"])["status"] == "DRAFT", (
            "the refused publish changed nothing"
        )


class TestParentOwnershipIsKeyedOnTheConsentId:
    """A parent's `X-User-ID` is a consent identifier, and nothing else will do."""

    def test_03_addressing_another_parents_consent_or_rights_request_is_refused(self):
        """Reading one's own consent works; everything else about the neighbour does not.

        "When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting
        `ConsentRequest` ... a `Parent` may read or act on a `ConsentRequest` only when that
        request's own `id` equals `X-User-ID`, and may read or act on a
        `ParentalRightsRequest` only when that request's `consent_request_id` equals
        `X-User-ID`. A `Parent` who addresses somebody else's consent record or rights request
        is rejected with `ERR_NOT_CONSENT_HOLDER` (HTTP 403)."

        Design: Corner/errors/parent_addressing_another_parents_consent_reports_not_consent_holder
        """
        service = mixed_audience_service(name="Ownership Kids")
        service_id = service["id"]
        notice = published_notice(service_id)
        holder = granted_consent(
            service_id,
            notice["id"],
            "guardian.ff@x.test",
            "child-618",
            consent_method="KNOWLEDGE_BASED_AUTH",
        )
        neighbour = granted_consent(
            service_id,
            notice["id"],
            "guardian.gg@x.test",
            "child-619",
            consent_method="KNOWLEDGE_BASED_AUTH",
        )
        holder_headers = make_parent_headers(holder["id"])
        neighbour_headers = make_parent_headers(neighbour["id"])

        own = validate_success(
            api_client.get_consent_request(holder["id"], holder_headers)
        )
        assert own["parent_email"] == "guardian.ff@x.test"
        assert own["status"] == "GRANTED"

        validate_error(
            api_client.get_consent_request(neighbour["id"], holder_headers),
            "ERR_NOT_CONSENT_HOLDER",
            403,
        )
        validate_error(
            api_client.create_parental_rights_request(
                parental_rights_request_payload(
                    service_id, neighbour["id"], "DELETE", "guardian.gg@x.test"
                ),
                holder_headers,
            ),
            "ERR_NOT_CONSENT_HOLDER",
            403,
        )

        own_request = validate_success(
            api_client.create_parental_rights_request(
                parental_rights_request_payload(
                    service_id, holder["id"], "REVIEW", "guardian.ff@x.test"
                ),
                holder_headers,
            ),
            201,
        )
        assert own_request["status"] == "SUBMITTED"

        validate_error(
            api_client.get_parental_rights_request(own_request["id"], neighbour_headers),
            "ERR_NOT_CONSENT_HOLDER",
            403,
        )


class TestEveryIdentifierHasItsOwnNotFoundCode:
    """Path identifiers and body foreign keys each report their own 404."""

    def test_04_path_and_body_identifiers_report_their_own_codes_in_declaration_order(self):
        """Eight path codes, then the body order that decides between two unknowns.

        "Where a path contains more than one identifier, identifiers are resolved strictly
        left to right and the request fails on the **first** one that does not resolve, with
        the 404 error belonging to that identifier: `ERR_SERVICE_NOT_FOUND`,
        `ERR_AGE_SCREEN_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
        `ERR_RECORD_NOT_FOUND`, `ERR_RIGHTS_REQUEST_NOT_FOUND`, `ERR_INTEGRATION_NOT_FOUND` or
        `ERR_ASSESSMENT_NOT_FOUND`. Body foreign keys are resolved in a fixed declaration
        order — `service_id` first, then `notice_id`, then `consent_request_id`, then
        `activity_id`, then `program_id` — and the first unresolvable one determines the
        error".

        Design: Corner/errors/unknown_path_and_body_identifiers_report_their_own_not_found_codes
        """
        service = create_service(name="Not Found Kids")
        service_id = service["id"]

        validate_error(
            api_client.get_online_service(NON_EXISTENT_UUID, OFFICER_HEADERS),
            "ERR_SERVICE_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.set_age_screen_status(
                NON_EXISTENT_UUID, {"to_status": "IN_REVIEW"}, ENGINEER_HEADERS
            ),
            "ERR_AGE_SCREEN_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.publish_parental_notice(NON_EXISTENT_UUID, OFFICER_HEADERS),
            "ERR_NOTICE_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_consent_request(NON_EXISTENT_UUID, OFFICER_HEADERS),
            "ERR_CONSENT_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_child_data_record(NON_EXISTENT_UUID, ENGINEER_HEADERS),
            "ERR_RECORD_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_parental_rights_request(NON_EXISTENT_UUID, OFFICER_HEADERS),
            "ERR_RIGHTS_REQUEST_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.set_third_party_integration_status(
                NON_EXISTENT_UUID, {"to_status": "AUDIT_PENDING"}, OFFICER_HEADERS
            ),
            "ERR_INTEGRATION_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_safe_harbor_assessment(NON_EXISTENT_UUID, OFFICER_HEADERS),
            "ERR_ASSESSMENT_NOT_FOUND",
            404,
        )

        validate_error(
            api_client.create_activity(
                {
                    "service_id": NON_EXISTENT_UUID,
                    "activity_code": "CLUB",
                    "participation_required_elements": ["SCREEN_NAME"],
                },
                OFFICER_HEADERS,
            ),
            "ERR_SERVICE_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.create_consent_request(
                consent_request_payload(
                    service_id,
                    NON_EXISTENT_UUID,
                    "guardian.hh@x.test",
                    "child-620",
                    service_version(service_id),
                    intended_uses=["PARTICIPATION_CORE"],
                    consent_method="EMAIL_PLUS",
                ),
                OFFICER_HEADERS,
            ),
            "ERR_NOTICE_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.create_child_data_record(
                child_data_record_payload(
                    service_id, NON_EXISTENT_UUID, ANOTHER_MISSING_UUID
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_CONSENT_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.create_safe_harbor_assessment(
                safe_harbor_assessment_payload(service_id, NON_EXISTENT_UUID, 2026),
                make_assessor_headers("assessor-6"),
            ),
            "ERR_PROGRAM_NOT_FOUND",
            404,
        )

        assert read_service(service_id)["safe_harbor_status"] == "NOT_ENROLLED", (
            "no assessment row was created, so the service is still unenrolled"
        )
