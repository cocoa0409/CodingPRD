"""Firm setup: jurisdiction/reviewer registry, request validation pipeline,
envelope shape, and basic RBAC denials (PRD §2.1-§2.5, §3.1-§3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_engagement,
    assert_jurisdiction,
    assert_reviewer,
    create_engagement_payload,
    create_jurisdiction_payload,
    make_engagement,
    make_jurisdiction,
    make_reviewer,
    setup_registered_engagement,
    validate_error,
    validate_success,
)


class TestJurisdictionRegistry:
    def test_jurisdiction_creation_applies_defaults(self, api, admin_headers):
        """PRD §3.1: "Three optional knobs carry defaults when omitted:
        `free_resubmittal_cycles` defaults to 2, `requires_se_seal` defaults to
        false, and `allows_deferred_submittals` defaults to true."

        Design: Corner/entities/jurisdiction_creation_applies_defaults
        """
        resp = api.create_jurisdiction(create_jurisdiction_payload(), admin_headers)
        jur = validate_success(resp, 201)
        assert_jurisdiction(jur)
        assert jur["free_resubmittal_cycles"] == 2
        assert jur["requires_se_seal"] is False
        assert jur["allows_deferred_submittals"] is True

    def test_reviewer_creation_initializes_computed_load(self, api, admin_headers):
        """PRD §3.1: "A reviewer's `active_assignment_count` starts at 0 on
        registration and is thereafter a computed figure: the count of that
        reviewer's assignments currently in `ACTIVE` status."
        PRD §3.1: "an optional `max_concurrent_assignments` defaulting to 3."

        Design: Corner/entities/reviewer_creation_initializes_computed_load
        """
        resp = api.create_reviewer(
            {"full_name": "Fresh Reviewer",
             "licenses": [{"state_code": "CA", "license_type": "PE",
                           "license_number": "PX", "expires_on": "2030-01-01"}]},
            admin_headers)
        rev = validate_success(resp, 201)
        assert_reviewer(rev)
        assert rev["active_assignment_count"] == 0
        assert rev["max_concurrent_assignments"] == 3

    def test_duplicate_jurisdiction_state_rejected(self, api, admin_headers):
        """PRD §3.1: "its two-letter `state_code` (uppercase, and unique across
        all jurisdictions — a duplicate registration is rejected with
        `ERR_DUPLICATE_JURISDICTION_STATE`)."

        Design: Corner/validations/duplicate_jurisdiction_state_rejected
        """
        make_jurisdiction(state_code="CA")
        resp = api.create_jurisdiction(
            create_jurisdiction_payload(state_code="CA", ibc_edition="IBC_2024",
                                        fee_method="SQUARE_FOOTAGE",
                                        turnaround_days=10, sla_mode="CALENDAR"),
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_JURISDICTION_STATE)


class TestEngagementRegistration:
    def test_engagement_creation_pins_jurisdiction_snapshot(self, api):
        """PRD §2.6: "At engagement creation the server therefore copies a
        snapshot of the governing jurisdiction onto the engagement:
        `pinned_state_code`, `pinned_ibc_edition`, `pinned_asce7_edition`,
        `pinned_fee_method`, `pinned_turnaround_days`, `pinned_sla_mode`,
        `pinned_free_resubmittal_cycles`, `pinned_requires_se_seal`, and
        `pinned_allows_deferred_submittals`."
        PRD §3.2: "Under the `SQUARE_FOOTAGE` method, the base fee is the gross
        floor area multiplied by the per-square-foot rate for the building type
        — 40 cents for `RESIDENTIAL`, 55 for `COMMERCIAL`, 45 for `INDUSTRIAL`,
        and 70 for `ESSENTIAL_FACILITY`."

        Design: Corner/entities/engagement_creation_pins_jurisdiction_snapshot
        """
        jur = make_jurisdiction(
            state_code="CA", ibc_edition="IBC_2018", asce7_edition="ASCE7_16",
            fee_method="SQUARE_FOOTAGE", turnaround_days=20, sla_mode="CALENDAR",
            free_resubmittal_cycles=1, requires_se_seal=True,
            allows_deferred_submittals=False)
        rev = make_reviewer(state_code="CA", license_type="SE")
        resp = api.create_engagement(
            create_engagement_payload(
                jur["id"], rev["id"], project_name="Snapshot",
                building_type="COMMERCIAL", risk_category="III",
                scope="FULL_REVIEW", declared_valuation_cents=5_000_000,
                floor_area_sqft=10_000, requested_expedite=False),
            TEST_USERS_COORDINATOR)
        eng = validate_success(resp, 201)
        assert_engagement(eng)
        assert eng["pinned_state_code"] == "CA"
        assert eng["pinned_ibc_edition"] == "IBC_2018"
        assert eng["pinned_asce7_edition"] == "ASCE7_16"
        assert eng["pinned_fee_method"] == "SQUARE_FOOTAGE"
        assert eng["pinned_turnaround_days"] == 20
        assert eng["pinned_sla_mode"] == "CALENDAR"
        assert eng["pinned_free_resubmittal_cycles"] == 1
        assert eng["pinned_requires_se_seal"] is True
        assert eng["pinned_allows_deferred_submittals"] is False
        # 10000 sqft x 55 cents, scope factor 1.0, no expedite
        assert eng["estimated_fee_cents"] == 550_000
        assert eng["status"] == "REGISTERED"
        assert eng["cycle_count"] == 0

    def test_engagement_get_not_found_returns_404(self, api, coordinator_headers):
        """PRD §2.4: "The not-found error matches the resource type:
        `ERR_JURISDICTION_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`,
        `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`,
        `ERR_DEFERRED_SUBMITTAL_NOT_FOUND`, or `ERR_RECORD_NOT_FOUND`."

        Design: Corner/entities/engagement_get_not_found_returns_404
        """
        resp = api.get_engagement(NON_EXISTENT_UUID, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND, 404)

    def test_engagement_create_missing_required_field_returns_400(self, api, coordinator_headers):
        """PRD §2.4: "Request body shape** — required fields present, enum
        values valid, types correct (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/engagement_create_missing_required_field_returns_400
        """
        payload = create_engagement_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID)
        del payload["jurisdiction_id"]
        resp = api.create_engagement(payload, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_engagement_create_invalid_enum_returns_400(self, api, coordinator_headers):
        """PRD §2.4: "Request body shape** — required fields present, enum
        values valid, types correct (`ERR_INVALID_REQUEST`)."
        PRD §3.2: "the review `scope` (`FULL_REVIEW`, `LATERAL_ONLY`, or
        `PEER_REVIEW`)."

        Design: Corner/entities/engagement_create_invalid_enum_returns_400
        """
        bundle = setup_registered_engagement()
        payload = create_engagement_payload(
            bundle["jurisdiction"]["id"], bundle["reviewer"]["id"], scope="BOGUS")
        resp = api.create_engagement(payload, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_engagement_create_bogus_jurisdiction_returns_not_found(self, api, coordinator_headers):
        """PRD §2.4: "identifier fields in the body (`jurisdiction_id`,
        `reviewer_of_record_id`, `engagement_id`, `cycle_id`, `reviewer_id`)
        must each resolve to an existing resource."

        Design: Corner/validations/engagement_create_bogus_jurisdiction_returns_not_found
        """
        rev = make_reviewer(state_code="CA")
        payload = create_engagement_payload(NON_EXISTENT_UUID, rev["id"])
        resp = api.create_engagement(payload, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_JURISDICTION_NOT_FOUND, 404)


class TestValidationPipelineEdge:
    def test_jurisdiction_create_missing_auth_header(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty
        value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/jurisdiction_create_missing_auth_header
        """
        resp = api.create_jurisdiction(create_jurisdiction_payload(), headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

    def test_jurisdiction_create_forbidden_for_applicant(self, api, applicant_headers):
        """PRD §2.1: "If the role is valid but not among the roles authorized
        for the targeted endpoint, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /plan-review/jurisdictions is authorized for
        PlatformAdmin only.

        Design: Corner/validations/jurisdiction_create_forbidden_for_applicant
        """
        resp = api.create_jurisdiction(create_jurisdiction_payload(), applicant_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    def test_reviewer_cannot_create_engagement(self, api):
        """PRD §2.1: "If the role is valid but not among the roles authorized
        for the targeted endpoint, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /plan-review/engagements is authorized for
        ReviewCoordinator only.

        Design: Corner/rbac/reviewer_cannot_create_engagement
        """
        bundle = setup_registered_engagement()
        rev = bundle["reviewer"]
        from test_helpers import make_reviewer_headers
        resp = api.create_engagement(
            create_engagement_payload(bundle["jurisdiction"]["id"], rev["id"]),
            make_reviewer_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


class TestNotFoundCatalog:
    def test_remaining_not_found_resources_return_404(self, api, admin_headers, coordinator_headers):
        """PRD §2.4: "The not-found error matches the resource type:
        `ERR_JURISDICTION_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`,
        `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`,
        `ERR_DEFERRED_SUBMITTAL_NOT_FOUND`, or `ERR_RECORD_NOT_FOUND`."

        Design: Corner/errors/remaining_not_found_resources_return_404
        """
        cases = [
            (api.get_reviewer(NON_EXISTENT_UUID, admin_headers),
             ApiErrorId.ERR_REVIEWER_NOT_FOUND),
            (api.get_cycle(NON_EXISTENT_UUID, coordinator_headers),
             ApiErrorId.ERR_CYCLE_NOT_FOUND),
            (api.get_assignment(NON_EXISTENT_UUID, coordinator_headers),
             ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
            (api.get_comment(NON_EXISTENT_UUID, coordinator_headers),
             ApiErrorId.ERR_COMMENT_NOT_FOUND),
            (api.get_deferred(NON_EXISTENT_UUID, coordinator_headers),
             ApiErrorId.ERR_DEFERRED_SUBMITTAL_NOT_FOUND),
            (api.get_record(NON_EXISTENT_UUID, coordinator_headers),
             ApiErrorId.ERR_RECORD_NOT_FOUND),
        ]
        for resp, err_id in cases:
            validate_error(resp, err_id, 404)


class TestSingleGetEnvelope:
    def test_single_get_returns_stored_data_with_envelope(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §3.2: "The scoped base is the base multiplied by the scope factor —
        full rate for `FULL_REVIEW`, sixty percent for `LATERAL_ONLY`, eighty
        percent for `PEER_REVIEW` — rounded half up to whole cents."

        Design: Corner/endpoints/single_get_returns_stored_data_with_envelope
        """
        bundle = setup_registered_engagement(
            eng_overrides={"project_name": "Gettable",
                           "building_type": "INDUSTRIAL",
                           "risk_category": "III",
                           "scope": "LATERAL_ONLY",
                           "floor_area_sqft": 12_000})
        eng_id = bundle["engagement"]["id"]
        from test_helpers import make_applicant_headers
        resp = api.get_engagement(eng_id, make_applicant_headers("app-1"))
        body = resp.json()
        assert resp.status_code == 200
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["response_type"] == "object"
        eng = body["data"]
        assert_engagement(eng)
        assert eng["project_name"] == "Gettable"
        assert eng["scope"] == "LATERAL_ONLY"
        # valuation base 250000 x 0.6 scope factor
        assert eng["estimated_fee_cents"] == 150_000


from test_helpers import TEST_USERS as _TU  # noqa: E402  (module alias for brevity)
TEST_USERS_COORDINATOR = _TU["coordinator_headers"]
