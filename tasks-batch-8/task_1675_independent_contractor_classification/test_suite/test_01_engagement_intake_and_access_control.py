"""Engagement intake, contractor registration, listing/pagination, and access control."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_contractor,
    assert_engagement,
    assert_version_incremented,
    build_user_headers,
    create_contractor,
    create_engagement,
    create_jurisdiction,
    get_engagement,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_answers,
    setup_engagement_at_state,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestContractorRegistration:
    def test_contractor_creation_applies_system_defaults(self, api, engagement_manager_headers):
        """PRD §3.2: "A new contractor begins with `verification_status` of `UNVERIFIED`,
        `standing_status` of `GOOD_STANDING`, and `lifetime_reported_cents` of 0."

        Design: Corner/entities/entity_contractor_creation_defaults_and_system_fields
        """
        res = api.create_contractor(
            {
                "legal_name": "Defaults LLC",
                "entity_type": "SOLE_PROPRIETOR",
                "ein": "12-1001675",
                "insurance_coverage_cents": 250000,
            },
            engagement_manager_headers,
        )
        contractor = validate_success(res, 201)
        assert_contractor(contractor)
        assert contractor["verification_status"] == "UNVERIFIED"
        assert contractor["standing_status"] == "GOOD_STANDING"
        assert contractor["lifetime_reported_cents"] == 0


class TestEngagementIntakeValidation:
    def test_engagement_missing_contractor_id_returns_400(self, api, engagement_manager_headers):
        """PRD §2.9: "**Request shape** — required fields are present, enum values fall
        within their declared sets, and dates are parseable (`ERR_INVALID_REQUEST`, HTTP 400)."

        Design: Corner/entities/entity_engagement_missing_required_returns_invalid_request
        """
        jurisdiction = create_jurisdiction()
        payload = {
            "jurisdiction_id": jurisdiction["id"],
            "title": "Missing contractor",
            "scope_description": "x",
            "agreed_rate_cents": 10000,
            "rate_unit": "HOURLY",
            "start_date": "2026-02-01",
            "end_date": "2026-12-31",
        }
        res = api.create_engagement(payload, engagement_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_engagement_invalid_rate_unit_returns_400(self, api, engagement_manager_headers):
        """PRD §3.3: an engagement carries "a `rate_unit` of `HOURLY`, `DAILY`, or `PROJECT`".
        PRD §2.9: "**Request shape** — required fields are present, enum values fall within
        their declared sets, and dates are parseable (`ERR_INVALID_REQUEST`, HTTP 400)."

        Design: Corner/entities/entity_engagement_invalid_enum_returns_invalid_request
        """
        jurisdiction = create_jurisdiction()
        contractor = create_contractor()
        payload = {
            "contractor_id": contractor["id"],
            "jurisdiction_id": jurisdiction["id"],
            "title": "Bad enum",
            "scope_description": "x",
            "agreed_rate_cents": 10000,
            "rate_unit": "WEEKLY",
            "start_date": "2026-02-01",
            "end_date": "2026-12-31",
        }
        res = api.create_engagement(payload, engagement_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_engagement_create_with_ghost_contractor_returns_404(self, api, engagement_manager_headers):
        """PRD §2.7: "A contractor identifier that does not exist yields
        `ERR_CONTRACTOR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/entity_contractor_not_found_returns_404
        """
        jurisdiction = create_jurisdiction()
        payload = {
            "contractor_id": NON_EXISTENT_UUID,
            "jurisdiction_id": jurisdiction["id"],
            "title": "Ghost",
            "scope_description": "x",
            "agreed_rate_cents": 10000,
            "rate_unit": "HOURLY",
            "start_date": "2026-02-01",
            "end_date": "2026-12-31",
        }
        res = api.create_engagement(payload, engagement_manager_headers)
        validate_error(res, ApiErrorId.ERR_CONTRACTOR_NOT_FOUND.value)

    def test_engagement_creation_computed_fields(self, api, engagement_manager_headers):
        """PRD §3.3: "A new engagement begins in `DRAFT` with a `scope_creep_index` of 0
        and a `scope_creep_tier` of `LOW`; its `risk_tier` stays null until a
        classification determination exists."

        Design: Corner/entities/entity_computed_field_input_ignored
        """
        jurisdiction = create_jurisdiction()
        contractor = create_contractor()
        engagement = create_engagement(contractor["id"], jurisdiction["id"])
        assert_engagement(engagement)
        assert engagement["status"] == "DRAFT"
        assert engagement["scope_creep_index"] == 0
        assert engagement["scope_creep_tier"] == "LOW"
        assert engagement["risk_tier"] is None


class TestQuestionnaireConsistency:
    def test_questionnaire_submission_immediately_visible(self, api, platform_admin_headers):
        """PRD §3.3: "The first submission moves the engagement `DRAFT → INTAKE_SUBMITTED`;
        the transition occurs even when the answers are incomplete, though an incomplete
        questionnaire will block the later review-submission step."
        PRD §3.3: "The `revision` counter starts at 1 on the first submission and
        increments by one on every subsequent submission for the same engagement".
        PRD §3.3: "Every accepted submission increments the engagement's `version` by one."

        Design: Corner/consistency_model/consistency_immediate_read_after_write
        """
        jurisdiction = create_jurisdiction()
        contractor = create_contractor()
        engagement = create_engagement(contractor["id"], jurisdiction["id"])
        created_version = engagement["version"]

        q = validate_success(
            api.submit_questionnaire(
                engagement["id"], {"answers": make_answers()}, TEST_USERS["engagement_manager_headers"]
            ),
            200,
        )
        assert q["revision"] == 1
        assert q["complete"] is True

        fresh = validate_success(api.get_engagement(engagement["id"], platform_admin_headers), 200)
        assert fresh["status"] == "INTAKE_SUBMITTED"
        assert_version_incremented(fresh["version"], created_version)


class TestEngagementListing:
    def test_engagement_list_pagination_and_status_filter(self, api, platform_admin_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults
        to 10, accepts a minimum of 1, and is capped at a maximum of 100. The `offset`
        parameter specifies how many items to skip and defaults to 0." and "The `meta`
        object of a list response carries four pagination fields: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §3.3: "Engagements may be listed filtered by `contractor_id`, `jurisdiction_id`,
        or `status`."

        Design: Corner/endpoints/ep_engagement_list_pagination_and_status_filter
        """
        jurisdiction = create_jurisdiction()
        contractor = create_contractor()
        eng1 = create_engagement(contractor["id"], jurisdiction["id"], title="Page one")
        eng2 = create_engagement(contractor["id"], jurisdiction["id"], title="Page two")

        page1, meta1 = validate_paginated(
            api.list_engagements(
                platform_admin_headers,
                params={"contractor_id": contractor["id"], "limit": 1, "offset": 0},
            )
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_engagements(
                platform_admin_headers,
                params={"contractor_id": contractor["id"], "limit": 1, "offset": 1},
            )
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page2[0]["id"] != page1[0]["id"]
        assert {page1[0]["id"], page2[0]["id"]} == {eng1["id"], eng2["id"]}

        drafts, meta_drafts = validate_paginated(
            api.list_engagements(
                platform_admin_headers,
                params={"contractor_id": contractor["id"], "status": "DRAFT"},
            )
        )
        assert len(drafts) == 2 and meta_drafts["total_count"] == 2

        active, meta_active = validate_paginated(
            api.list_engagements(
                platform_admin_headers,
                params={"contractor_id": contractor["id"], "status": "ACTIVE"},
            )
        )
        assert active == [] and meta_active["total_count"] == 0


class TestExistenceAndAccessControl:
    def test_engagement_get_not_found_returns_404(self, api, platform_admin_headers):
        """PRD §2.7: "an engagement identifier that does not exist yields
        `ERR_ENGAGEMENT_NOT_FOUND` (HTTP 404)".

        Design: Corner/errors/err_engagement_get_not_found_returns_404
        """
        res = api.get_engagement(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(res, ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND.value)

    def test_analyst_cannot_create_engagement_returns_403(self, api, classification_analyst_headers,
                                                          platform_admin_headers):
        """PRD §2.1: "An authenticated principal attempting an operation outside their
        role's grant is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_analyst_cannot_create_engagement_returns_403
        """
        jurisdiction = create_jurisdiction()
        contractor = create_contractor()
        payload = {
            "contractor_id": contractor["id"],
            "jurisdiction_id": jurisdiction["id"],
            "title": "Forbidden",
            "scope_description": "x",
            "agreed_rate_cents": 10000,
            "rate_unit": "HOURLY",
            "start_date": "2026-02-01",
            "end_date": "2026-12-31",
        }
        res = api.create_engagement(payload, classification_analyst_headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

        data, meta = validate_paginated(
            api.list_engagements(platform_admin_headers, params={"contractor_id": contractor["id"]})
        )
        assert data == [] and meta["total_count"] == 0, "denied create must not persist an engagement"

    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or whose role header does not name
        a declared role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/rbac_missing_auth_headers_returns_unauthenticated
        """
        res = api.list_jurisdictions(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_tax_specialist_cannot_suspend_engagement(self, api, tax_reporting_specialist_headers):
        """PRD §2.1: "An authenticated principal attempting an operation outside their
        role's grant is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: the suspend operation is granted to ComplianceOfficer.

        Design: Corner/rbac/rbac_tax_specialist_cannot_suspend_engagement
        """
        setup = setup_engagement_at_state("DRAFT")
        res = api.suspend_engagement(setup["engagement"]["id"], tax_reporting_specialist_headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
