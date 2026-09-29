"""Entity contracts: declared fields, defaults, system fields, enums, listings and immutability."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    OMIT,
    ApiClient,
    ApiErrorId,
    PROGRAM_ADMIN_HEADERS,
    assert_common_fields,
    assert_log_elements_present,
    assert_log_entry_has_no_version_block,
    assert_plan_state,
    assert_total_count,
    assert_two_decimal_value,
    build_hazard_assessment,
    build_incident_report,
    build_prevention_plan,
    build_team_assignment,
    build_training_module,
    build_work_area,
    build_worksite,
    read_plan,
    read_work_area,
    setup_clock,
    setup_draft_plan,
    setup_amended_log_case,
    setup_escalated_report,
    setup_open_case,
    setup_programme,
    setup_work_area,
    setup_worksite,
    setup_worksite_with_area,
)


class TestWorksiteAndWorkAreaShape:
    """The two reference-data rows echo their inputs and expose their computed fields."""

    def test_worksite_creation_returns_every_declared_field(self, api: ApiClient) -> None:
        """A fresh North Plant carries the three inputs, both counters at their defaults and the common block.

        PRD: "A fresh worksite starts with `violent_incident_count_12mo` at 0 and `high_risk_flag` at false."
        Design: Corner/entities/worksite_creation_returns_all_declared_fields
        """
        setup_clock(api)

        worksite = get_success_data(
            api.create_worksite(build_worksite(), PROGRAM_ADMIN_HEADERS), 201
        )

        assert worksite["name"] == "North Plant"
        assert worksite["state_code"] == "CA"
        assert worksite["employee_count"] == 20
        assert worksite["violent_incident_count_12mo"] == 0
        assert worksite["high_risk_flag"] is False
        assert_common_fields(worksite, expected_version=1)

    def test_work_area_read_back_shows_a_null_hazard_score(self, api: ApiClient) -> None:
        """With no live plan governing the front desk, both counters sit at their pre-activity values.

        PRD: "The latter is the `hazard_score` of the area's non-`SUPERSEDED` hazard assessment belonging to the worksite's plan whose `status` is `ACTIVE` or `REVIEW_DUE`; when the worksite has no such plan, or that plan has no live assessment for the area, `current_hazard_score` stays null."
        Design: Corner/entities/work_area_retrieval_returns_stored_fields_and_null_hazard_score
        """
        ctx = setup_worksite_with_area(api)

        area = read_work_area(api, ctx["work_area"]["id"])

        assert area["id"] == ctx["work_area"]["id"]
        assert area["worksite_id"] == ctx["worksite"]["id"]
        assert area["name"] == "Front Desk"
        assert area["job_function"] == "CASH_HANDLING"
        assert area["public_access_flag"] is True
        assert area["lone_worker_flag"] is False
        assert area["night_shift_flag"] is True
        assert area["occupancy_cap"] == 8
        assert area["restricted_employee_count"] == 0
        assert area["current_hazard_score"] is None
        assert_common_fields(area, expected_version=1)

    def test_client_supplied_system_fields_are_overwritten_by_the_server(
        self, api: ApiClient
    ) -> None:
        """A create carrying id, both timestamps and version keeps none of them.

        PRD: "Clients never supply it, and supplying one has no effect."
        Design: Corner/entities/worksite_system_fields_generated_with_client_id_input_ignored
        """
        setup_clock(api, "2026-09-15T12:00:00Z")

        worksite = get_success_data(
            api.create_worksite(
                build_worksite(
                    name="South Depot",
                    state_code="OR",
                    employee_count=12,
                    id="11111111-1111-1111-1111-111111111111",
                    created_at="2020-01-01T00:00:00Z",
                    updated_at="2020-01-01T00:00:00Z",
                    version=99,
                ),
                PROGRAM_ADMIN_HEADERS,
            ),
            201,
        )

        assert worksite["id"] != "11111111-1111-1111-1111-111111111111"
        assert worksite["created_at"] != "2020-01-01T00:00:00Z"
        assert worksite["updated_at"] != "2020-01-01T00:00:00Z"
        assert worksite["version"] == 1
        assert worksite["name"] == "South Depot"
        assert worksite["employee_count"] == 12

    def test_an_out_of_range_enum_and_a_broken_bound_are_both_request_shape_errors(
        self, api: ApiClient
    ) -> None:
        """JANITORIAL is no job function and an occupancy cap of zero breaks the declared minimum.

        PRD: "Each is created against a `worksite_id` with a `name` of 1 to 120 characters, a `job_function` drawn from `PATIENT_CARE`, `CASH_HANDLING`, `FIELD_SERVICE`, `WAREHOUSE`, `SECURITY` and `ADMIN`, and an `occupancy_cap` of at least 1 giving the maximum staff headcount the area may hold at any instant."
        Design: Corner/entities/work_area_invalid_job_function_enum_rejected
        """
        setup_clock(api)
        worksite = setup_worksite(api)

        validate_error(
            api.create_work_area(
                build_work_area(
                    worksite["id"],
                    name="Janitor Closet",
                    job_function="JANITORIAL",
                    occupancy_cap=2,
                ),
                PROGRAM_ADMIN_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )
        validate_error(
            api.create_work_area(
                build_work_area(
                    worksite["id"], name="Records Room", job_function="ADMIN", occupancy_cap=0
                ),
                PROGRAM_ADMIN_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        assert_total_count(
            api.list_work_areas(PROGRAM_ADMIN_HEADERS, {"worksite_id": worksite["id"]}), 0
        )


class TestDefaultsAndComputedFields:
    """Omitted optional inputs are filled by the server; supplied computed values are ignored."""

    def test_three_creates_take_every_declared_default(self, api: ApiClient) -> None:
        """The area flags, the review interval and the module's three optional inputs all default.

        PRD: "Three further inputs have defaults: `refresh_interval_days`, the number of days a completion stays current before the annual refresh falls due, defaults to 365 and must lie between 30 and 1095; `passing_score` defaults to 80 and must lie between 0 and 100; and `required_for_escort` defaults to false, becoming true for modules whose completion is a precondition for acting as a security escort."
        Design: Corner/entities/prevention_plan_and_module_defaults_applied_when_fields_omitted
        """
        ctx = setup_programme(api)

        area = setup_work_area(
            api,
            ctx["worksite"]["id"],
            name="Records Room",
            job_function="ADMIN",
            occupancy_cap=4,
            public_access_flag=OMIT,
            lone_worker_flag=OMIT,
            night_shift_flag=OMIT,
        )
        plan = get_success_data(
            api.create_prevention_plan(
                build_prevention_plan(ctx["worksite"]["id"], review_interval_days=OMIT),
                ctx["headers"]["safety_officer"],
            )
        )
        module = get_success_data(
            api.create_training_module(
                build_training_module(
                    code="WVP-GEN",
                    refresh_interval_days=OMIT,
                    passing_score=OMIT,
                    required_for_escort=OMIT,
                ),
                PROGRAM_ADMIN_HEADERS,
            )
        )

        assert area["public_access_flag"] is False
        assert area["lone_worker_flag"] is False
        assert area["night_shift_flag"] is False
        assert plan["review_interval_days"] == 365
        assert_plan_state(
            plan, status="DRAFT", compliance_posture="FROZEN", inspection_ready=False
        )
        assert plan["submitted_by_employee_id"] is None
        assert plan["activated_by_employee_id"] is None
        assert plan["activated_at"] is None
        assert plan["review_due_date"] is None
        assert module["refresh_interval_days"] == 365
        assert module["passing_score"] == 80
        assert module["required_for_escort"] is False

    def test_a_client_supplied_hazard_score_is_ignored_in_favour_of_the_formula(
        self, api: ApiClient
    ) -> None:
        """The stored row reads 64.00 and TIER_1_ENGINEERING, not the 1.00 and tier the client sent.

        PRD: "Unknown extra body fields are ignored rather than rejected, and computed or system-managed fields supplied by a client are ignored."
        Design: Corner/entities/hazard_assessment_client_supplied_hazard_score_extra_field
        """
        ctx = setup_draft_plan(api)
        plan = read_plan(api, ctx)

        assessment = get_success_data(
            api.create_hazard_assessment(
                build_hazard_assessment(
                    plan["id"],
                    ctx["work_area"]["id"],
                    plan["version"],
                    hazard_score=1.00,
                    control_tier="TIER_3_TRAINING_ONLY",
                    mitigation_verified=True,
                    score_variant="VALIDATED",
                ),
                ctx["headers"]["safety_officer"],
            ),
            201,
        )

        assert_two_decimal_value(assessment["hazard_score"], 64.00, "hazard_score")
        assert assessment["control_tier"] == "TIER_1_ENGINEERING"
        assert assessment["score_variant"] == "SCREENING"
        assert assessment["mitigation_verified"] is False
        assert assessment["authored_by_employee_id"] == ctx["so"]["id"]
        assert assessment["validated_by_employee_id"] is None
        assert read_work_area(api, ctx["work_area"]["id"])["current_hazard_score"] is None


class TestListingAndIdentifierResolution:
    """Filters narrow the register; unknown identifiers resolve to their own not-found codes."""

    def test_the_report_listing_filters_on_triage_status_and_paginates(
        self, api: ApiClient
    ) -> None:
        """One escalated and one untouched report: the filter returns one row, the window returns the other.

        PRD: "Beyond pagination, list endpoints accept equality filters on the fields named in §4's description column."
        Design: Corner/entities/incident_report_listing_paginates_and_filters_by_triage_status
        """
        ctx = setup_escalated_report(api)
        second = get_success_data(
            api.create_incident_report(
                build_incident_report(
                    ctx["worksite"]["id"],
                    ctx["work_area"]["id"],
                    ctx["rep"]["id"],
                    channel="SUPERVISOR",
                    occurred_at="2026-07-29T08:00:00Z",
                    narrative="Client refused to leave the lobby and shouted at the receptionist.",
                    incident_type="TYPE_2_CLIENT",
                    weapon_involved=False,
                    injury_level="NONE",
                ),
                ctx["headers"]["employee"],
            )
        )

        filtered, meta = validate_paginated(
            api.list_incident_reports(
                ctx["headers"]["safety_officer"],
                {"worksite_id": ctx["worksite"]["id"], "triage_status": "NEW"},
            )
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(filtered) == 1
        assert filtered[0]["id"] == second["id"]
        assert filtered[0]["triage_status"] == "NEW"

        page, page_meta = validate_paginated(
            api.list_incident_reports(
                ctx["headers"]["safety_officer"],
                {"worksite_id": ctx["worksite"]["id"], "limit": 1, "offset": 1},
            )
        )
        assert page_meta["total_count"] == 2
        assert page_meta["limit"] == 1
        assert page_meta["offset"] == 1
        assert page_meta["has_more"] is False
        assert len(page) == 1

    def test_an_unknown_threat_case_id_on_a_read_returns_its_own_not_found_code(
        self, api: ApiClient
    ) -> None:
        """An authorised lead reading a case that does not exist gets 404, not 403.

        PRD: "Templated path segments are resolved strictly left to right, and the first segment that fails to resolve determines the 404 code."
        Design: Corner/entities/threat_case_not_found_returns_404
        """
        ctx = setup_programme(api)

        response = api.get_threat_case(
            NON_EXISTENT_UUID, ctx["headers"]["threat_team_lead"]
        )

        validate_error(response, ApiErrorId.THREAT_CASE_NOT_FOUND, 404)
        body = response.json()["data"]
        assert body["error_id"] != ApiErrorId.UNAUTHORIZED
        assert isinstance(body["message"], str) and body["message"]

    def test_a_missing_required_field_outranks_the_body_foreign_key_check(
        self, api: ApiClient
    ) -> None:
        """Omitting worksite_id is a 400; naming an unknown one is a 404, and neither writes a plan.

        PRD: "Request shape: the body and query string parse, every statically required field is present, every enum value is in range, every number respects its declared bounds, and pagination stays within its limits — `ERR_INVALID_REQUEST` (400)."
        Design: Corner/entities/prevention_plan_missing_worksite_id_returns_invalid_request
        """
        ctx = setup_programme(api)

        validate_error(
            api.create_prevention_plan(
                build_prevention_plan(OMIT),
                ctx["headers"]["safety_officer"],
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )
        validate_error(
            api.create_prevention_plan(
                build_prevention_plan(NON_EXISTENT_UUID, review_interval_days=OMIT),
                ctx["headers"]["safety_officer"],
            ),
            ApiErrorId.WORKSITE_NOT_FOUND,
            404,
        )

        assert_total_count(
            api.list_prevention_plans(
                ctx["headers"]["safety_officer"], {"worksite_id": ctx["worksite"]["id"]}
            ),
            0,
        )

    def test_each_unresolvable_foreign_key_reports_its_own_entity_code(
        self, api: ApiClient
    ) -> None:
        """An unknown worksite_id and an unknown member_employee_id map to two different 404 codes.

        PRD: "Every employee-valued field — `employee_id`, `lead_employee_id`, `member_employee_id`, `subject_employee_id`, `reporter_employee_id`, `escort_employee_id`, and `assigned_employee_id` — reports `ERR_EMPLOYEE_NOT_FOUND` when it names no employee."
        Design: Corner/entities/prevention_plan_with_unknown_worksite_returns_worksite_not_found
        """
        ctx = setup_open_case(api)

        validate_error(
            api.create_prevention_plan(
                build_prevention_plan(NON_EXISTENT_UUID), ctx["headers"]["safety_officer"]
            ),
            ApiErrorId.WORKSITE_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_team_assignment(
                ctx["case"]["id"],
                build_team_assignment(NON_EXISTENT_UUID, "SECURITY"),
                ctx["headers"]["threat_team_lead"],
            ),
            ApiErrorId.EMPLOYEE_NOT_FOUND,
            404,
        )

        assert ctx["case"]["status"] == "OPEN"
        assert ctx["case"]["quorum_met"] is False
        assert_total_count(
            api.list_team_assignments(
                ctx["headers"]["threat_team_lead"], {"case_id": ctx["case"]["id"]}
            ),
            0,
        )

    def test_a_cross_worksite_work_area_is_refused_after_both_keys_resolve(
        self, api: ApiClient
    ) -> None:
        """Both foreign keys exist, so the flat topology needs the explicit mismatch rule to catch this.

        PRD: "The work area named must belong to the plan's worksite; a cross-worksite reference is refused with `ERR_WORK_AREA_WORKSITE_MISMATCH`."
        Design: Corner/entities/hazard_assessment_work_area_from_another_worksite_rejected
        """
        ctx = setup_draft_plan(api)
        other_worksite = setup_worksite(api, name="South Depot", state_code="OR", employee_count=12)
        other_area = setup_work_area(
            api,
            other_worksite["id"],
            name="Depot Dock",
            job_function="WAREHOUSE",
            public_access_flag=False,
            lone_worker_flag=False,
            night_shift_flag=False,
            occupancy_cap=6,
        )

        response = api.create_hazard_assessment(
            build_hazard_assessment(
                ctx["plan"]["id"],
                other_area["id"],
                ctx["plan"]["version"],
                reported_incident_count=2,
                proximity_factor="LOW",
            ),
            ctx["headers"]["safety_officer"],
        )

        validate_error(response, ApiErrorId.WORK_AREA_WORKSITE_MISMATCH, 409)
        assert response.json()["data"]["error_id"] != ApiErrorId.WORK_AREA_NOT_FOUND
        assert read_plan(api, ctx)["version"] == 1
        assert_total_count(
            api.list_hazard_assessments(
                ctx["headers"]["safety_officer"], {"plan_id": ctx["plan"]["id"]}
            ),
            0,
        )


class TestLogEntryImmutability:
    """The one entity without a version block is corrected by appending, never by editing."""

    def test_an_amendment_appends_a_successor_and_leaves_the_original_untouched(
        self, api: ApiClient
    ) -> None:
        """The original keeps its six elements and its null narratives while the successor carries eight.

        PRD: "Neither `updated_at` nor `version` exists on a log entry, because a log entry is never mutated in place."
        Design: Corner/entities/violent_incident_log_entry_is_immutable_with_no_version_and_no_update_endpoint
        """
        ctx = setup_amended_log_case(api)
        original_id = ctx["log_entry"]["id"]
        amendment = ctx["log_amendment"]

        assert amendment["id"] != original_id
        assert amendment["supersedes_entry_id"] == original_id
        assert_log_elements_present(amendment, 8)

        original = get_success_data(
            api.get_log_entry(original_id, ctx["headers"]["safety_officer"])
        )
        assert original["superseded_flag"] is True
        assert original["incident_at"] == ctx["log_entry"]["incident_at"]
        assert original["work_area_name"] == ctx["log_entry"]["work_area_name"]
        assert original["incident_type"] == ctx["log_entry"]["incident_type"]
        assert original["perpetrator_class"] == ctx["log_entry"]["perpetrator_class"]
        assert original["injury_level"] == ctx["log_entry"]["injury_level"]
        assert original["law_enforcement_notified"] == ctx["log_entry"]["law_enforcement_notified"]
        assert original["consequence_narrative"] is None
        assert original["controls_summary"] is None
        assert_log_elements_present(original, 6)
        assert_log_entry_has_no_version_block(original)
        assert_log_entry_has_no_version_block(amendment)
