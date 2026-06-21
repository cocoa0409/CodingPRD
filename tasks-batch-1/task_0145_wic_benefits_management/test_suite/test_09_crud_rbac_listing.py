"""Resource creation/shape, required fields, defaults, not-found and FK integrity,
authentication, RBAC, and filtered list pagination (PRD §2.1, §2.3, §2.6, §3.1-3.2).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_agency,
    assert_income_record,
    create_agency,
    create_household,
    create_participant,
    create_draft_application,
    make_participant_headers,
    setup_risk_assessed_application,
    CLERK,
)


class TestCreationAndShape:
    def test_create_agency_returns_201_with_system_fields(self, api):
        """PRD §3.1: "A freshly created agency begins with an active_caseload_count
        of 0 and its current_utc clock at the epoch default."
        PRD §2.4: "version — an integer that begins at 1 on creation".

        Design: Corner/entities/create_agency_returns_201_with_system_fields
        """
        agency = validate_success(api.create_agency(
            {"name": "Agency Z", "state_code": "CA", "caseload_cap": 25}, CLERK
        ), 201)
        assert_agency(agency)
        assert agency["version"] == 1
        assert agency["active_caseload_count"] == 0

    def test_income_record_is_append_only_no_version(self, api):
        """PRD §2.4: "An IncomeRecord (a single pay stub attached to an
        application) and a Redemption (a single EBT draw-down event) carry only id
        and created_at; they have neither updated_at nor version".
        PRD §3.2: "The server assigns each income record a sequence_index in
        creation order within the application, starting at 0."

        Design: Corner/entities/income_record_immutable_no_version
        """
        agency = create_agency()
        hh = create_household(agency["id"], household_size=2, adjunctive_program="SNAP")
        p = create_participant(hh["id"], full_name="Inc Rec", ssn_last4="6661",
                               category="CHILD")
        app = create_draft_application(p["id"])
        ir = validate_success(api.create_income_record(
            {"application_id": app["id"], "gross_amount_cents": 100000,
             "pay_frequency": "MONTHLY"},
            CLERK,
        ), 201)
        assert_income_record(ir)
        assert ir["sequence_index"] == 0
        assert "version" not in ir
        assert "updated_at" not in ir


class TestRequiredAndDefaults:
    def test_create_participant_missing_category_rejected(self, api):
        """PRD §2.9: "then well-formedness of the request body — required fields
        present, enum values legal, integer fields non-negative
        (ERR_INVALID_REQUEST)".
        PRD §3.2: "their WIC category (one of PREGNANT, POSTPARTUM, BREASTFEEDING,
        INFANT, or CHILD)".

        Design: Corner/entities/create_participant_missing_required_field
        """
        agency = create_agency()
        hh = create_household(agency["id"], household_size=2, adjunctive_program="SNAP")
        resp = api.create_participant(
            {"household_id": hh["id"], "full_name": "No Category", "ssn_last4": "8888"},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_participant_breastfeeding_opt_in_defaults_false(self, api):
        """PRD §3.2: "an optional breastfeeding_opt_in flag (defaulting to false)".
        PRD §3.2: "the participant starts in APPLICANT status".

        Design: Corner/entities/participant_default_breastfeeding_opt_in_false
        """
        agency = create_agency()
        hh = create_household(agency["id"], household_size=2, adjunctive_program="SNAP")
        p = validate_success(api.create_participant(
            {"household_id": hh["id"], "full_name": "Default BF",
             "ssn_last4": "8887", "category": "CHILD"},
            CLERK,
        ), 201)
        assert p["breastfeeding_opt_in"] is False
        assert p["status"] == "APPLICANT"


class TestNotFoundAndFkIntegrity:
    def test_get_agency_not_found(self, api):
        """PRD §2.6: "the first identifier that does not resolve to an existing
        resource produces ERR_NOT_FOUND before any business rule is evaluated."

        Design: Corner/entities/get_agency_not_found
        """
        resp = api.get_agency(NON_EXISTENT_UUID, CLERK)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_participant_bad_household_fk_not_found(self, api):
        """PRD §2.6: "the server validates existence left to right: the path
        identifier is resolved first, then each foreign-key identifier in the body,
        and the first identifier that does not resolve to an existing resource
        produces ERR_NOT_FOUND before any business rule is evaluated."

        Design: Corner/entities/participant_bad_household_fk_not_found
        """
        create_agency()  # ensure an agency exists; the household FK is the missing one
        resp = api.create_participant(
            {"household_id": NON_EXISTENT_UUID, "full_name": "Orphan",
             "ssn_last4": "7777", "category": "CHILD"},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestAuthAndRbac:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or that carries a role
        string the system does not recognize, is rejected with
        ERR_UNAUTHENTICATED."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.create_agency(
            {"name": "NoAuth", "state_code": "CA", "caseload_cap": 10}, {}
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_participant_cannot_create_agency(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for the
        requested operation is rejected with ERR_FORBIDDEN."
        PRD §2.1: "The EligibilityClerk is front-desk staff: they create agencies,
        clinics, vendors, households, participants, and applications".

        Design: Corner/rbac/participant_cannot_create_agency
        """
        headers = make_participant_headers("00000000-0000-0000-0000-000000000001")
        resp = api.create_agency(
            {"name": "Forbidden", "state_code": "CA", "caseload_cap": 10}, headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_clerk_cannot_approve_application(self, api):
        """PRD §2.1: "The CompetentProfessionalAuthority — abbreviated CPA
        throughout this document — is a credentialed nutrition professional who
        performs the risk assessment, approves or denies and thereby certifies
        applications".

        Design: Corner/rbac/clerk_cannot_approve_application
        """
        ctx = setup_risk_assessed_application(
            category="CHILD", adjunctive_program="SNAP", household_size=3,
            income_records=[(100000, "MONTHLY")], risk_factor_codes=["ANEMIA"],
            ssn_last4="1313",
        )
        resp = api.approve_application(ctx["application"]["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestListingPagination:
    def test_list_participants_filtered_by_household_paginated(self, api):
        """PRD §3.2: "Participants can be listed and filtered by household_id."
        PRD §2.3: "Paginated list responses include the following fields in the
        meta object of the response envelope: limit, offset, total_count, and
        has_more."

        Design: Corner/endpoints/list_participants_filtered_by_household_paginated
        """
        agency = create_agency()
        hh = create_household(agency["id"], household_size=4, adjunctive_program="SNAP")
        create_participant(hh["id"], full_name="Kid A", ssn_last4="3331", category="CHILD")
        create_participant(hh["id"], full_name="Kid B", ssn_last4="3332", category="CHILD")
        data, meta = validate_paginated(
            api.list_participants(CLERK, params={"household_id": hh["id"]})
        )
        assert meta["total_count"] == 2, f"expected 2 participants, got {meta['total_count']}"
        assert all(p["household_id"] == hh["id"] for p in data)
