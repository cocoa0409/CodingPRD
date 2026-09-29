"""Entity-level behaviour of the HERS Rating & Code Compliance API.

Creation defaults, computed fields, retrieval, listing/pagination, request-shape
rejection and foreign-key coherence, all driven through the PRD's endpoints.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_PLAN_MODEL_MISMATCH,
    ERR_RATING_NOT_FOUND,
    ERR_SUBDIVISION_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_append_only_evidence,
    assert_cents,
    assert_common_fields,
    assert_count,
    assert_coverage_ledger,
    assert_error_envelope,
    assert_fresh_rating,
    assert_home_sampling_state,
    assert_index,
    assert_normalized_value,
    assert_object_envelope,
)
from test_helpers.fixtures import (
    build_rating_world,
    create_builder,
    create_home,
    create_rater,
    create_subdivision,
    get_subdivision,
    list_diagnostic_tests,
    schedule_inspection,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_builder_rep_headers,
    make_certified_rater_headers,
    make_field_inspector_headers,
)

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


class TestCreationDefaults:
    def test_builder_creation_returns_system_fields_and_computed_defaults(self, api):
        """PRD §3.1: "A newly registered builder has `status` of `ACTIVE`, and its four derived numbers — `open_corrective_action_count`, `revoked_package_count`, `certified_incentive_cents` and the `sampling_eligible` flag — are computed immediately, which for a brand-new builder means `open_corrective_action_count`, `revoked_package_count` and `certified_incentive_cents` all read zero."
        PRD §3.1: "It is true when, and only when, all three of the following hold: `builder_type` is `PRODUCTION`, `status` is `ACTIVE`, and `open_corrective_action_count` is zero."
        PRD §2.4: "`Builder`, `Subdivision`, `PlanModel`, `Home`, `Rater`, `Rating`, `Inspection`, `SampleSet`, `QAReview`, `CorrectiveAction` and `DocumentPackage` additionally carry `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of that row — and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

        Design: Corner/entities/builder_creation_returns_system_fields_and_computed_defaults
        """
        response = api.create_builder(
            factories.builder_payload(
                name="Anchor Homes",
                builder_type="PRODUCTION",
                utility_program_budget_cents=250000,
            ),
            ADMIN_HEADERS,
        )
        data = validate_success(response, 201)

        assert data["status"] == "ACTIVE", data
        assert data["sampling_eligible"] is True, data
        assert data["open_corrective_action_count"] == 0, data
        assert data["revoked_package_count"] == 0, data
        assert_cents(data["certified_incentive_cents"], 0)
        assert_cents(data["utility_program_budget_cents"], 250000)
        assert_common_fields(data, expected_version=1)

        # §2.2 envelope: `req_`-prefixed request id, ISO timestamp, object type.
        assert_object_envelope(response.json())

    def test_subdivision_defaults_applied_when_optional_fields_omitted(self, api):
        """PRD §3.1: "`sampling_enabled` says whether the sampling protocol may be used in this subdivision and defaults to `false` when omitted."
        PRD §3.1: "`compliance_path_preference` is the binding code-compliance path election for every rating in the subdivision; it is either `ERI_PATH` or `PRESCRIPTIVE_PATH` and defaults to `ERI_PATH`."
        PRD §3.1: "On creation the subdivision's coverage ledger — `homes_count`, `sampled_home_count` and `unsampled_home_count` — starts at zero across the board."

        Design: Corner/entities/subdivision_defaults_applied_when_optional_fields_omitted
        """
        builder = create_builder(api, name="Anchor Homes")

        payload = factories.subdivision_payload(
            builder["id"], name="Mill Race", code_edition="IECC_2021", climate_zone="CZ5"
        )
        assert "sampling_enabled" not in payload
        assert "compliance_path_preference" not in payload

        data = validate_success(api.create_subdivision(payload, ADMIN_HEADERS), 201)

        assert data["sampling_enabled"] is False, data
        assert data["compliance_path_preference"] == "ERI_PATH", data
        assert data["climate_zone"] == "CZ5", data
        assert_coverage_ledger(
            data, homes_count=0, sampled_home_count=0, unsampled_home_count=0
        )

    def test_rating_computed_fields_derived_from_pinned_plan_model(self, api):
        """PRD §3.2: "The home's current plan is pinned onto the rating as its own `plan_model_id`, so that any later edit to the builder's plan catalogue cannot move this rating's numbers; and the pinned plan's projected index is copied onto the rating as its `projected_index`."
        PRD §3.2: "A new rating starts with `stage` of `PROJECTED`, `compliance_status` of `UNDETERMINED`, `qa_status` of `NOT_SELECTED`, `registry_status` of `NOT_SUBMITTED`, and `file_locked` of `false`; `confirmed_index`, `confirmed_ach50`, `confirmed_duct_leakage_cfm25_per_100sqft`, `eri_target`, `submitted_index`, `registry_confirmation_number`, `rejection_reason` and `confirmed_at` are all null, and `compliance_path` is `NONE`."

        Design: Corner/entities/rating_computed_fields_derived_from_pinned_plan_model
        """
        world = build_rating_world(api, with_rating=False, lot_number="L-2201")
        assert_index(world.plan_model["projected_index"], 43)

        data = validate_success(
            api.create_rating(
                factories.rating_payload(world.home_id, world.rater_id),
                make_certified_rater_headers(world.rater_id),
            ),
            201,
        )

        assert data["plan_model_id"] == world.plan_model_id, data
        assert_index(data["projected_index"], 43)
        assert_fresh_rating(data)
        assert_common_fields(data, expected_version=1)


class TestRetrievalAndListing:
    def test_home_retrieval_returns_stored_fields(self, api):
        """PRD §3.2: "A freshly registered lot has `sampling_role` of `UNASSIGNED`, a null `sample_set_id`, and `individual_testing_required` set to `false`, and its registration raises the owning subdivision's `homes_count` and `unsampled_home_count` each by one."

        Design: Corner/entities/home_retrieval_returns_stored_fields
        """
        world = build_rating_world(
            api, with_rating=False, lot_number="L-2001", permit_date="2026-08-10"
        )

        data = validate_success(
            api.get_home(world.home_id, make_builder_rep_headers(world.builder_id)), 200
        )

        assert data["lot_number"] == "L-2001", data
        assert data["permit_date"] == "2026-08-10", data
        assert data["subdivision_id"] == world.subdivision_id, data
        assert data["plan_model_id"] == world.plan_model_id, data
        assert_home_sampling_state(
            data,
            sampling_role="UNASSIGNED",
            sample_set_id=None,
            individual_testing_required=False,
        )

        assert_coverage_ledger(
            get_subdivision(api, world.subdivision_id),
            homes_count=1,
            sampled_home_count=0,
            unsampled_home_count=1,
        )

    def test_homes_listing_filters_by_subdivision_and_paginates(self, api):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` reports the number of rows matching the filters before pagination is applied and `has_more` reports whether any matching row remains beyond the returned page."
        PRD §2.3: "Unless a specific list endpoint states otherwise, results are ordered by the resource's `created_at` timestamp in ascending order — oldest first."

        Design: Corner/entities/homes_listing_filters_by_subdivision_and_paginates
        """
        world = build_rating_world(api, with_home=False, with_rating=False)
        homes = [
            create_home(
                api,
                world.subdivision_id,
                world.plan_model_id,
                world.builder_id,
                lot_number=lot_number,
                permit_date=permit_date,
            )
            for lot_number, permit_date in (
                ("L-2101", "2026-08-10"),
                ("L-2102", "2026-08-11"),
                ("L-2103", "2026-08-12"),
            )
        ]
        rep_headers = make_builder_rep_headers(world.builder_id)

        first_page, first_meta = validate_paginated(
            api.list_homes(
                rep_headers,
                params={"subdivision_id": world.subdivision_id, "limit": 2, "offset": 0},
            )
        )
        assert_count(first_page, 2)
        assert first_meta["total_count"] == 3, first_meta
        assert first_meta["has_more"] is True, first_meta
        assert first_meta["limit"] == 2, first_meta
        assert first_meta["offset"] == 0, first_meta

        second_page, second_meta = validate_paginated(
            api.list_homes(
                rep_headers,
                params={"subdivision_id": world.subdivision_id, "limit": 2, "offset": 2},
            )
        )
        assert_count(second_page, 1)
        assert second_meta["total_count"] == 3, second_meta
        assert second_meta["has_more"] is False, second_meta
        assert second_page[0]["id"] == homes[2]["id"], second_page

    def test_get_rating_with_unknown_id_returns_404_not_found(self, api):
        """PRD §2.8: "Existence of every identifier in the URL path, validated strictly left to right, so the leftmost missing identifier is the one reported."
        PRD §2.8: "Each resource has its own not-found code: `ERR_BUILDER_NOT_FOUND`, `ERR_SUBDIVISION_NOT_FOUND`, `ERR_PLAN_MODEL_NOT_FOUND`, `ERR_HOME_NOT_FOUND`, `ERR_RATER_NOT_FOUND`, `ERR_RATING_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_SAMPLE_SET_NOT_FOUND`, `ERR_QA_REVIEW_NOT_FOUND`, `ERR_CORRECTIVE_ACTION_NOT_FOUND` and `ERR_DOCUMENT_PACKAGE_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/get_rating_with_unknown_id_returns_404_not_found
        """
        response = api.get_rating(UNKNOWN_ID, ADMIN_HEADERS)

        validate_error(response, ERR_RATING_NOT_FOUND, 404)
        assert_error_envelope(response.json(), ERR_RATING_NOT_FOUND)


class TestAppendOnlyEvidence:
    def test_diagnostic_test_is_immutable_and_carries_no_version(self, api):
        """PRD §2.4: "A recorded measurement is append-only evidence: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it."
        PRD §2.4: "A diagnostic test is never edited, never re-graded and never deleted once written."
        PRD §3.3: "Recording a duct-leakage reading normalizes it per unit floor area: multiply the `measured_value` by 100, divide by the pinned plan's `conditioned_floor_area_sqft`, and round the quotient half-up to two decimal places to obtain `normalized_value`."

        Design: Corner/entities/diagnostic_test_is_immutable_and_carries_no_version
        """
        world = build_rating_world(api, lot_number="L-2301")
        inspection = schedule_inspection(
            api,
            world.rating_id,
            world.inspector_id,
            checkpoint="FINAL",
            air_handler_installed=True,
        )

        data = validate_success(
            api.create_diagnostic_test(
                inspection["id"],
                factories.diagnostic_test_payload("DUCT_LEAKAGE_TOTAL", 96),
                make_field_inspector_headers(world.inspector_id),
            ),
            201,
        )

        assert data["result"] == "PASS", data
        assert_normalized_value(data["normalized_value"], 4.00)
        assert_append_only_evidence(data)

        assert_count(list_diagnostic_tests(api, inspection["id"]), 1)


class TestRequestShapeAndForeignKeys:
    def test_plan_model_missing_required_field_rejected(self, api):
        """PRD §2.8: "Request-shape validation, performed before any database read: all required input fields present, all types correct, all enum members recognized, and all numeric and ordering constraints honoured — `conditioned_floor_area_sqft` and `conditioned_volume_cuft` and `envelope_ua_btu_per_hr_f` and `design_ach50` strictly greater than zero, `bedrooms` at least 1, `hvac_efficiency_index` between 1 and 20 inclusive, `pv_capacity_kw_dc` and `design_duct_leakage_cfm25_per_100sqft` and `measured_value` and `utility_program_budget_cents` at least zero, `scheduled_end_utc` strictly after `scheduled_start_utc`, `window_end_date` on or after `window_start_date`, `limit` within 1 through 100, `offset` at least zero."
        PRD §2.8: "Any violation is `ERR_INVALID_REQUEST`, 422."

        Design: Corner/entities/plan_model_missing_required_field_rejected
        """
        builder = create_builder(api, name="Anchor Homes")
        subdivision = create_subdivision(api, builder["id"], name="Mill Race")
        rater = create_rater(api, full_name="Rae Tarrant", cert_level="RATER")

        payload = factories.plan_model_payload(subdivision["id"])
        del payload["conditioned_volume_cuft"]

        validate_error(
            api.create_plan_model(payload, make_certified_rater_headers(rater["id"])),
            ERR_INVALID_REQUEST,
            422,
        )

        plan_models, _meta = validate_paginated(
            api.list_plan_models(subdivision["id"], ADMIN_HEADERS)
        )
        assert_count(plan_models, 0)

    def test_invalid_enum_member_on_climate_zone_rejected(self, api):
        """PRD §2.7: "Every subdivision fixes two jurisdictional facts at creation: `code_edition`, which is either `IECC_2015` or `IECC_2021`, and `climate_zone`, which is one of `CZ2`, `CZ3`, `CZ4`, `CZ5` or `CZ6`."
        PRD §2.8: "Any violation is `ERR_INVALID_REQUEST`, 422."

        Design: Corner/entities/invalid_enum_member_on_climate_zone_rejected
        """
        builder = create_builder(api, name="Anchor Homes")

        validate_error(
            api.create_subdivision(
                factories.subdivision_payload(
                    builder["id"],
                    name="Mill Race",
                    code_edition="IECC_2021",
                    climate_zone="CZ9",
                    sampling_enabled=False,
                    compliance_path_preference="ERI_PATH",
                ),
                ADMIN_HEADERS,
            ),
            ERR_INVALID_REQUEST,
            422,
        )

        subdivisions, _meta = validate_paginated(
            api.list_subdivisions(ADMIN_HEADERS, params={"builder_id": builder["id"]})
        )
        assert_count(subdivisions, 0)

    def test_home_with_unknown_subdivision_parent_returns_404(self, api):
        """PRD §2.8: "Existence of every foreign-key identifier in the request body, validated in the order the endpoint declares its inputs, yielding the same resource-specific 404 codes as step 4."
        PRD §3.2: "A builder representative registers each lot it intends to have rated as a `Home`, supplying the `subdivision_id`, the `plan_model_id` of the plan being built on that lot, a `lot_number` unique within the subdivision, and a `permit_date` as a `YYYY-MM-DD` calendar date."

        Design: Corner/entities/home_with_unknown_subdivision_parent_returns_404
        """
        world = build_rating_world(api, with_home=False, with_rating=False)

        validate_error(
            api.create_home(
                factories.home_payload(
                    UNKNOWN_ID, world.plan_model_id, lot_number="L-2401"
                ),
                make_builder_rep_headers(world.builder_id),
            ),
            ERR_SUBDIVISION_NOT_FOUND,
            404,
        )

        assert_coverage_ledger(
            get_subdivision(api, world.subdivision_id), homes_count=0
        )

    def test_home_rejects_plan_model_from_another_subdivision(self, api):
        """PRD §3.2: "The named plan model must belong to the *same* subdivision as the home and must still be `ACTIVE`; a plan from a different subdivision, or one that has been archived, is rejected with `ERR_PLAN_MODEL_MISMATCH`."

        Design: Corner/entities/home_rejects_plan_model_from_another_subdivision
        """
        world = build_rating_world(api, with_home=False, with_rating=False)
        other_subdivision = create_subdivision(
            api, world.builder_id, name="Stone Row", climate_zone="CZ4"
        )

        validate_error(
            api.create_home(
                factories.home_payload(
                    other_subdivision["id"], world.plan_model_id, lot_number="L-2501"
                ),
                make_builder_rep_headers(world.builder_id),
            ),
            ERR_PLAN_MODEL_MISMATCH,
            422,
        )

        assert_coverage_ledger(
            get_subdivision(api, other_subdivision["id"]), homes_count=0
        )
