"""Sponsor registration, applicant onboarding, and application creation rules."""
from test_helpers import (
    BO,
    NON_EXISTENT_UUID,
    SM,
    ApiErrorId,
    api_client,
    assert_application,
    assert_sponsor,
    create_applicant,
    create_applicant_payload,
    create_application_payload,
    create_sponsor,
    create_sponsor_payload,
    is_valid_uuid,
    make_sponsor_signatory_headers,
    open_application,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSponsorCreation:

    def test_sponsor_created_with_defaults(self):
        """PRD section 3.1: "A `SecurityManager` registers a sponsor by
        supplying its legal `name`, a globally unique `sponsor_code`, and the
        `active_badge_quota` that caps how many credentials the organization
        may hold in circulation; the new sponsor starts in `ACTIVE` status
        with an `active_badge_count` of zero and a null `suspended_at`."

        Design: Corner/entities/sponsor_created_with_defaults
        """
        resp = api_client.create_sponsor(
            create_sponsor_payload(name="AeroFuel", sponsor_code="AF",
                                   active_badge_quota=5),
            SM,
        )
        data = validate_success(resp, expected_status=201)
        assert_sponsor(data)
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1
        assert data["status"] == "ACTIVE"
        assert data["active_badge_count"] == 0
        assert data["suspended_at"] is None

    def test_request_missing_auth_headers_unauthenticated(self):
        """PRD section 2.6: "The `X-User-ID` and `X-User-Role` headers must
        both be present and non-empty; otherwise the request fails with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/request_missing_auth_headers_unauthenticated
        """
        resp = api_client.create_sponsor(
            create_sponsor_payload(name="AeroFuel", sponsor_code="AF",
                                   active_badge_quota=5),
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_sponsor_signatory_cannot_create_sponsor(self, sponsor_signatory_headers):
        """PRD section 4: the `POST /badging/sponsors` row lists only
        `SecurityManager` under Authorized Role(s).
        PRD section 2.6: "The caller's role must be one of the endpoint's
        allowed roles; otherwise `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/sponsor_signatory_cannot_create_sponsor
        """
        sponsor = create_sponsor()
        resp = api_client.create_sponsor(
            create_sponsor_payload(name="SkyChefs", sponsor_code="SC",
                                   active_badge_quota=5),
            make_sponsor_signatory_headers(sponsor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestApplicantOnboarding:

    def test_applicant_create_missing_required_field_returns_invalid_request(self):
        """PRD section 3.1: "Each applicant record carries a `sponsor_id`
        (which must equal the signatory's `X-User-ID`), the person's
        `full_name`, their `date_of_birth` as an ISO 8601 calendar date in
        year-month-day form, and the `government_id_number` that will anchor
        the fingerprint-based criminal history records check."
        PRD section 2.6: "missing required fields, unknown enum values,
        malformed datetimes, an `escortee_count` that is negative, a
        `max_escortees` outside the permitted range, or an audit window whose
        end is not after its start are rejected here as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/applicant_create_missing_required_field_returns_invalid_request
        """
        sponsor = create_sponsor()
        payload = create_applicant_payload(sponsor["id"])
        del payload["government_id_number"]
        resp = api_client.create_applicant(
            payload, make_sponsor_signatory_headers(sponsor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        lst, meta = validate_paginated(
            api_client.list_sponsor_applicants(sponsor["id"], BO))
        assert lst == [], f"no applicant may be persisted, got {lst}"
        assert meta["total_count"] == 0

    def test_sponsor_applicants_list_pagination(self):
        """PRD section 3.1: "The roster of a sponsor's applicants is available
        as a paginated listing to every role."
        PRD section 2.3: "Paginated and non-paginated list-based responses
        include the following fields in the `meta` object of the response
        envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/sponsor_applicants_list_pagination
        """
        sponsor = create_sponsor()
        a1 = create_applicant(sponsor["id"], full_name="Ana Rios",
                              government_id_number="G1001")
        a2 = create_applicant(sponsor["id"], full_name="Ben Okafor",
                              date_of_birth="1988-05-02",
                              government_id_number="G1002")

        page1, meta1 = validate_paginated(
            api_client.list_sponsor_applicants(
                sponsor["id"], BO, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert page1[0]["id"] == a1["id"], "created_at ascending: a1 first"

        page2, meta2 = validate_paginated(
            api_client.list_sponsor_applicants(
                sponsor["id"], BO, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert page2[0]["id"] == a2["id"]

    def test_suspend_sponsor_not_found_returns_404(self):
        """PRD section 2.6: "Path identifiers are validated left to right and
        body references must exist — each unknown resource yields its specific
        not-found error (`ERR_SPONSOR_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_BADGE_NOT_FOUND`,
        `ERR_ESCORT_PRIVILEGE_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, or
        `ERR_AUDIT_CYCLE_NOT_FOUND`)".

        Design: Corner/entities/suspend_sponsor_not_found_returns_404
        """
        resp = api_client.suspend_sponsor(NON_EXISTENT_UUID,
                                          {"reason": "x"}, SM)
        validate_error(resp, ApiErrorId.ERR_SPONSOR_NOT_FOUND)


class TestApplicationCreation:

    def test_application_created_in_submitted_state(self):
        """PRD section 3.1: "The new application enters `SUBMITTED` status
        with `submitted_at` set to the current logical clock and
        `application_expires_at` set ninety days later".
        PRD section 3.1: "Until the corresponding adjudication steps occur,
        the application's `chrc_outcome`, `sta_outcome`, and `denial_reason`
        remain null, and `issued_badge_id` stays null until a badge is
        actually issued."
        PRD section 2.5: "At server startup the logical clock is exactly
        `2026-08-01T00:00:00Z`, and the server never falls back to wall-clock
        time at any point afterward."

        Design: Corner/state_machines/application_created_in_submitted_state
        """
        sponsor = create_sponsor()
        applicant = create_applicant(sponsor["id"])
        resp = api_client.create_application(
            create_application_payload(applicant["id"], badge_class="SIDA"),
            make_sponsor_signatory_headers(sponsor["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_application(data)
        assert data["status"] == "SUBMITTED"
        assert data["submitted_at"] == "2026-08-01T00:00:00Z"
        assert data["application_expires_at"] == "2026-10-30T00:00:00Z", \
            "submitted_at + 90 days at the default clock"
        assert data["chrc_outcome"] is None
        assert data["sta_outcome"] is None
        assert data["sponsor_id"] == sponsor["id"], \
            "sponsor_id is denormalized from the applicant at creation"

    def test_second_open_application_rejected(self):
        """PRD section 3.1: "An applicant may hold at most one non-terminal
        application — one in `SUBMITTED`, `STA_PENDING`,
        `PENDING_REQUIREMENTS`, or `READY` — and a second attempt is rejected
        with `ERR_OPEN_APPLICATION_EXISTS`."

        Design: Corner/validations/second_open_application_rejected
        """
        sponsor = create_sponsor()
        applicant = create_applicant(sponsor["id"])
        open_application(applicant["id"], sponsor["id"], badge_class="SIDA")
        resp = api_client.create_application(
            create_application_payload(applicant["id"], badge_class="STERILE"),
            make_sponsor_signatory_headers(sponsor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_APPLICATION_EXISTS)

    def test_create_application_with_unknown_applicant_returns_404(self):
        """PRD section 2.6: "Path identifiers are validated left to right and
        body references must exist — each unknown resource yields its specific
        not-found error (`ERR_SPONSOR_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_BADGE_NOT_FOUND`,
        `ERR_ESCORT_PRIVILEGE_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, or
        `ERR_AUDIT_CYCLE_NOT_FOUND`)".

        Design: Corner/entities/create_application_with_unknown_applicant_returns_404
        """
        sponsor = create_sponsor()
        resp = api_client.create_application(
            create_application_payload(NON_EXISTENT_UUID, badge_class="SIDA"),
            make_sponsor_signatory_headers(sponsor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_FOUND)

    def test_withdraw_other_sponsors_application_forbidden(self):
        """PRD section 3.2: "a signatory acting on another sponsor's
        application is refused with `ERR_SPONSOR_OWNERSHIP_MISMATCH`."

        Design: Corner/validations/withdraw_other_sponsors_application_forbidden
        """
        s1 = create_sponsor(name="AeroFuel", sponsor_code="AF")
        s2 = create_sponsor(name="SkyChefs", sponsor_code="SC")
        a2 = create_applicant(s2["id"], full_name="Ben Okafor",
                              date_of_birth="1988-05-02",
                              government_id_number="G1002")
        ap2 = open_application(a2["id"], s2["id"], badge_class="SIDA")

        resp = api_client.withdraw_application(
            ap2["id"], make_sponsor_signatory_headers(s1["id"]))
        validate_error(resp, ApiErrorId.ERR_SPONSOR_OWNERSHIP_MISMATCH)

        after = api_client.get_application(ap2["id"], BO)
        assert validate_success(after)["status"] == "SUBMITTED", \
            "a refused withdrawal must leave the application unchanged"
