"""Reference-data CRUD, computed-field derivations, duplicate constraints,
malformed-request rejection, role-based access control, list pagination envelope,
and the version-increment-on-mutation contract.

Sources: Corner/entities, Corner/rbac, Corner/endpoints,
Corner/cross_cutting_complexity_layers.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    setup_base_parties,
    setup_examined_application,
    create_draft_application,
    add_item,
    set_clock,
    examiner_headers,
    make_attorney_headers,
    make_applicant_headers,
)
from test_helpers.factories import (
    create_applicant_payload,
    create_attorney_payload,
    create_nice_class_payload,
    create_application_payload,
)


class TestApplicantCreation:
    """POST /applicants derives is_foreign_domiciled from country_code and starts
    open_application_count at 0."""

    def test_foreign_applicant_flag_true(self, api):
        """PRD §3.1: "the server derives is_foreign_domiciled, which is true exactly
        when the country_code is not US"
        PRD §3.1: "A new applicant's open_application_count ... begins at 0."

        Design: Corner/entities/create_applicant_returns_201_with_computed_foreign_flag
        """
        attorney = validate_success(api.create_attorney(
            create_attorney_payload(bar_number="BAR-FF1"),
            make_attorney_headers("creator")), 201)
        att_headers = make_attorney_headers(attorney["id"])
        res = api.create_applicant(
            create_applicant_payload(legal_name="Foreign Ltd", country_code="GB"), att_headers)
        data = validate_success(res, 201)
        assert data["is_foreign_domiciled"] is True
        assert data["open_application_count"] == 0


class TestApplicationNotFound:
    """GET /applications/{id} for a non-existent id returns ERR_NOT_FOUND."""

    def test_get_nonexistent_application_404(self, api):
        """PRD §3.8: "every resource id in the path, then every body foreign key,
        must resolve, validated in that left-to-right order, else ERR_NOT_FOUND."

        Design: Corner/entities/get_application_not_found_returns_404
        """
        res = api.get_application(
            "00000000-0000-4000-8000-000000000000", examiner_headers())
        validate_error(res, "ERR_NOT_FOUND")


class TestApplicationMalformedRequests:
    """Missing/invalid body fields on POST /applications yield ERR_VALIDATION."""

    def _parties(self):
        attorney = validate_success(api_client.create_attorney(
            create_attorney_payload(bar_number="BAR-MAL1"),
            make_attorney_headers("creator")), 201)
        att_headers = make_attorney_headers(attorney["id"])
        applicant = validate_success(api_client.create_applicant(
            create_applicant_payload(), att_headers), 201)
        return attorney, applicant, att_headers

    def test_missing_filing_basis_returns_validation(self, api):
        """PRD §3.8: "A request whose body is malformed in a basic way — a missing
        required field, an unrecognized enum value, or a type mismatch — is rejected
        with ERR_VALIDATION."

        Design: Corner/entities/create_application_missing_filing_basis_returns_validation
        """
        attorney, applicant, att_headers = self._parties()
        payload = {
            "applicant_id": applicant["id"], "attorney_id": attorney["id"],
            "mark_text": "NOBASIS", "filing_tier": "TEAS_STANDARD",
        }
        res = api.create_application(payload, att_headers)
        validate_error(res, "ERR_VALIDATION")

    def test_invalid_filing_basis_enum_returns_validation(self, api):
        """PRD §3.8: "A request whose body is malformed in a basic way — a missing
        required field, an unrecognized enum value, or a type mismatch — is rejected
        with ERR_VALIDATION."

        Design: Corner/entities/create_application_invalid_filing_basis_enum_returns_validation
        """
        attorney, applicant, att_headers = self._parties()
        payload = create_application_payload(
            applicant_id=applicant["id"], attorney_id=attorney["id"],
            mark_text="BADENUM", filing_basis="SECTION_44", filing_tier="TEAS_STANDARD")
        res = api.create_application(payload, att_headers)
        validate_error(res, "ERR_VALIDATION")


class TestClassCountComputation:
    """Two GoodsServicesItem rows under the SAME nice_class_id yield class_count
    == 1 (distinct count), not 2."""

    def test_duplicate_nice_class_yields_class_count_one(self, api):
        """PRD §3.1: "Whenever an item is added, the application's class_count is
        recomputed as the number of distinct nice_class_id values across its items."

        Design: Corner/entities/computed_class_count_ignores_duplicate_nice_class
        """
        base = setup_base_parties(class_numbers=(9,))
        att_headers = base["att_headers"]
        app = create_draft_application(
            base["applicant"]["id"], att_headers, attorney_id=base["attorney"]["id"],
            mark_text="DISTINCT", filing_basis="USE", filing_tier="TEAS_STANDARD")
        nc_id = base["nice_classes"][0]["id"]
        add_item(app["id"], nc_id, att_headers, description="downloadable software")
        add_item(app["id"], nc_id, att_headers, description="mobile apps")
        app_after = validate_success(api.get_application(app["id"], att_headers), 200)
        assert app_after["class_count"] == 1, (
            f"two items in the same class should give class_count 1, got {app_after['class_count']}")


class TestNiceClassImmutableServiceFlag:
    """Seeding class 42 returns is_service_class == true (42 in 35..45)."""

    def test_service_class_flag_true_for_42(self, api):
        """PRD §3.1: "The server derives is_service_class, true exactly when the
        class_number is between 35 and 45 inclusive and false for the goods classes
        numbered 1 through 34."

        Design: Corner/entities/nice_class_immutable_computed_service_flag
        """
        set_clock("2026-01-01T00:00:00Z")
        res = api.create_nice_class(
            create_nice_class_payload(42, "Tech services"), examiner_headers())
        data = validate_success(res, 201)
        assert data["is_service_class"] is True


class TestDuplicateConstraints:
    """Duplicate class_number / bar_number are refused with their conflict errors."""

    def test_duplicate_nice_class_number_conflict(self, api):
        """PRD §3.1: "a class_number (an integer from 1 to 45, unique across all
        classes — a duplicate is refused with ERR_DUPLICATE_NICE_CLASS)"

        Design: Corner/entities/duplicate_nice_class_number_returns_conflict
        """
        validate_success(api.create_nice_class(
            create_nice_class_payload(9, "Software"), examiner_headers()), 201)
        res = api.create_nice_class(
            create_nice_class_payload(9, "Software dup"), examiner_headers())
        validate_error(res, "ERR_DUPLICATE_NICE_CLASS")

    def test_duplicate_attorney_bar_number_conflict(self, api):
        """PRD §3.1: "The bar_number must be unique across all attorneys; a second
        registration of the same number is refused with ERR_DUPLICATE_BAR_NUMBER."

        Design: Corner/entities/duplicate_attorney_bar_number_returns_conflict
        """
        validate_success(api.create_attorney(
            create_attorney_payload(full_name="First Counsel", bar_number="BAR-300"),
            make_attorney_headers("creator")), 201)
        res = api.create_attorney(
            create_attorney_payload(full_name="Second Counsel", bar_number="BAR-300", bar_state="CA"),
            make_attorney_headers("creator"))
        validate_error(res, "ERR_DUPLICATE_BAR_NUMBER")


class TestRoleBasedAccessControl:
    """Role gates: an Applicant cannot issue office actions; missing headers are
    unauthenticated."""

    def test_applicant_cannot_issue_office_action(self, api):
        """PRD §2.1: "When the headers are well-formed but the named role is not
        permitted to perform the requested operation, the request is rejected with
        ERR_UNAUTHORIZED."

        Design: Corner/rbac/applicant_cannot_issue_office_action
        """
        base = setup_examined_application(class_numbers=(9,), filing_basis="USE", mark_text="RBAC")
        applicant_headers = make_applicant_headers(base["applicant"]["id"])
        res = api.create_office_action(
            {"application_id": base["application"]["id"], "ground": "MERELY_DESCRIPTIVE"},
            applicant_headers)
        validate_error(res, "ERR_UNAUTHORIZED")

    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed value,
        is rejected with ERR_UNAUTHENTICATED."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        res = api.create_nice_class(
            create_nice_class_payload(9, "Software"), headers={})
        validate_error(res, "ERR_UNAUTHENTICATED")


class TestListApplicationsPaginationEnvelope:
    """GET /applications filtered by applicant_id returns an array response_type
    carrying total_count and has_more pagination fields."""

    def test_list_applications_filter_pagination(self, api):
        """PRD §2.3: "Every list response includes the following fields inside the
        meta object of the envelope: limit, offset, total_count, and has_more."

        Design: Corner/endpoints/list_applications_filter_pagination_envelope
        """
        base = setup_base_parties(class_numbers=())
        att_headers = base["att_headers"]
        create_draft_application(
            base["applicant"]["id"], att_headers, attorney_id=base["attorney"]["id"],
            mark_text="PAGED", filing_basis="USE", filing_tier="TEAS_STANDARD")
        res = api.list_applications(
            examiner_headers(),
            params={"applicant_id": base["applicant"]["id"], "limit": 10, "offset": 0})
        data, meta = validate_paginated(res)
        assert res.json()["response_type"] == "array"
        assert meta["total_count"] >= 1
        assert "has_more" in meta


class TestVersionIncrementOnMutation:
    """An application created at version 1 has version incremented (>= 2) after
    the DRAFT->FILED mutation."""

    def test_file_increments_application_version(self, api):
        """PRD §2.4: "version — an integer that begins at its initial value and
        increments by one on every mutation."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_application_mutation
        """
        base = setup_base_parties(class_numbers=(9,))
        att_headers = base["att_headers"]
        app = create_draft_application(
            base["applicant"]["id"], att_headers, attorney_id=base["attorney"]["id"],
            mark_text="VERSIONED", filing_basis="USE", filing_tier="TEAS_STANDARD")
        assert app["version"] == 1
        add_item(app["id"], base["nice_classes"][0]["id"], att_headers)
        filed = validate_success(api.file_application(app["id"], att_headers), 200)
        assert filed["version"] >= 2, (
            f"DRAFT->FILED should increment version above 1, got {filed['version']}")
