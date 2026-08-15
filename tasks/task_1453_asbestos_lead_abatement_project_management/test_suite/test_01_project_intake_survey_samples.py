"""Project intake, survey/sample lifecycle, list pagination, and the
provisional-vs-final survey quantity variants."""
from test_helpers import (
    ADMIN,
    IH,
    REG,
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_sample,
    api_client,
    assert_project,
    assert_sample,
    assert_survey,
    create_project_entity,
    create_project_payload,
    create_sample_payload,
    create_survey_entity,
    create_survey_payload,
    finalize_survey,
    get_survey,
    is_valid_uuid,
    list_samples,
    make_supervisor_headers,
    report_sample,
    submit_survey,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProjectIntake:
    def test_missing_name_rejected(self):
        """PRD section 3.1: "A `ContractorAdmin` opens an abatement engagement
        by creating a **project** with a `name`, the `site_address` of the
        structure, a `work_type` of either `RENOVATION` or `DEMOLITION`, a
        `hazard_class` of `ASBESTOS`, `LEAD`, or `MIXED`, an informational
        `planned_start`, and the contracted `base_abatement_cost_cents` (an
        integer number of cents, zero or greater)."
        PRD section 2.9: "**Field validation** — required fields are present,
        JSON types are correct, enum members are valid, numeric ranges are
        sane (`ERR_VALIDATION`, 400)."

        Design: Corner/entities/create_project_missing_required_name_returns_400
        """
        payload = create_project_payload()
        payload.pop("name")
        resp = api_client.create_project(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_invalid_work_type_enum_rejected(self):
        """PRD section 2.6: "Enum fields accept only the exact uppercase
        strings documented for them in §3; any other value is a
        field-validation failure."

        Design: Corner/entities/create_project_invalid_enum_rejected
        """
        resp = api_client.create_project(
            create_project_payload(name="P-X", work_type="GUTTING"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_project_defaults_and_initial_state(self):
        """PRD section 3.1: "A new project begins in `DRAFT` status with its
        `reoccupancy_status` `BLOCKED` and every computed figure at zero:
        `total_acm_sq_ft`, `estimated_disposal_cost_cents`,
        `manifested_weight_lbs`, `final_disposal_cost_cents`,
        `insurance_surcharge_cents`, and `total_project_cost_cents`."
        PRD section 2.4: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`."

        Design: Corner/entities/project_defaults_and_initial_state
        """
        resp = api_client.create_project(
            create_project_payload(
                name="P-DEF", site_address="2 Elm St", work_type="DEMOLITION",
                hazard_class="MIXED", planned_start="2026-09-01T00:00:00Z",
                base_abatement_cost_cents=25_000),
            ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_project(data)
        assert data["status"] == "DRAFT", "new project must start DRAFT"
        assert data["reoccupancy_status"] == "BLOCKED", \
            "new project must start with the re-occupancy gate BLOCKED"
        for field in ("total_acm_sq_ft", "estimated_disposal_cost_cents",
                      "manifested_weight_lbs", "final_disposal_cost_cents",
                      "insurance_surcharge_cents", "total_project_cost_cents"):
            assert data[field] == 0, f"{field} must start at zero"
        assert is_valid_uuid(data["id"]), "id must be a bare UUID"
        assert data["created_at"].startswith("2026-08-01T00:00:00"), (
            f"created_at must be stamped from the logical clock default, "
            f"got {data['created_at']}"
        )

    def test_get_project_not_found(self):
        """PRD section 2.11: "Each resource family has its own error
        identifier: `ERR_PROJECT_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`,
        `ERR_SAMPLE_NOT_FOUND`, `ERR_WORKER_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`,
        `ERR_CONTAINMENT_NOT_FOUND`, `ERR_AIR_TEST_NOT_FOUND`,
        `ERR_MANIFEST_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
        `ERR_UNIT_NOT_FOUND`, and `ERR_RELOCATION_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/get_project_not_found_returns_404
        """
        resp = api_client.get_project(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND)

    def test_not_found_sweep_reads(self):
        """PRD section 2.11: "Each resource family has its own error
        identifier: `ERR_PROJECT_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`,
        `ERR_SAMPLE_NOT_FOUND`, `ERR_WORKER_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`,
        `ERR_CONTAINMENT_NOT_FOUND`, `ERR_AIR_TEST_NOT_FOUND`,
        `ERR_MANIFEST_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
        `ERR_UNIT_NOT_FOUND`, and `ERR_RELOCATION_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/not_found_sweep_reads
        """
        validate_error(api_client.get_worker(NON_EXISTENT_UUID, ADMIN),
                       ApiErrorId.ERR_WORKER_NOT_FOUND)
        validate_error(api_client.get_survey(NON_EXISTENT_UUID, ADMIN),
                       ApiErrorId.ERR_SURVEY_NOT_FOUND)
        validate_error(api_client.get_facility(NON_EXISTENT_UUID, ADMIN),
                       ApiErrorId.ERR_FACILITY_NOT_FOUND)
        validate_error(
            api_client.get_relocation_unit(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_UNIT_NOT_FOUND)

    def test_not_found_sweep_actions(self):
        """PRD section 2.11: "Requests that address nested resources validate
        every referenced identifier in strict left-to-right order — path
        identifiers first, then body references — and reject with the 404
        error of the **first** reference that does not resolve."

        Design: Corner/entities/not_found_sweep_actions
        """
        validate_error(
            api_client.record_sample_result(
                NON_EXISTENT_UUID, {"lab_result": "NEGATIVE"}, IH),
            ApiErrorId.ERR_SAMPLE_NOT_FOUND)
        validate_error(api_client.cancel_assignment(NON_EXISTENT_UUID, ADMIN),
                       ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND)
        validate_error(
            api_client.acknowledge_notification(NON_EXISTENT_UUID, REG),
            ApiErrorId.ERR_NOTIFICATION_NOT_FOUND)
        validate_error(
            api_client.verify_containment(
                NON_EXISTENT_UUID, {"pressure_reading_inwg": -0.03},
                make_supervisor_headers("sup_x")),
            ApiErrorId.ERR_CONTAINMENT_NOT_FOUND)
        validate_error(
            api_client.record_air_test_result(
                NON_EXISTENT_UUID, {"result_f_cc": 0.005}, IH),
            ApiErrorId.ERR_AIR_TEST_NOT_FOUND)
        validate_error(
            api_client.seal_manifest(
                NON_EXISTENT_UUID, make_supervisor_headers("sup_x")),
            ApiErrorId.ERR_MANIFEST_NOT_FOUND)
        validate_error(api_client.return_relocation(NON_EXISTENT_UUID, ADMIN),
                       ApiErrorId.ERR_RELOCATION_NOT_FOUND)


class TestAuthEnvelope:
    def test_create_project_missing_auth_headers_unauthenticated(self):
        """PRD section 2.1: "A request missing either header, or naming a role
        the system does not declare, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/create_project_missing_auth_header_unauthenticated
        """
        resp = api_client.create_project(
            create_project_payload(name="P-NoAuth"), None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_create_project_unauthorized_role_forbidden(self):
        """PRD section 2.1: "Beyond authentication, each endpoint restricts
        which roles may call it; a call from a role outside the permitted set
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD section 2.1: "`RegulatorClerk` — regulator staff. Acknowledges
        filed notifications."

        Design: Corner/rbac/create_project_unauthorized_role_forbidden
        """
        resp = api_client.create_project(
            create_project_payload(name="P-R1"), REG)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestSurveyLifecycle:
    def test_second_survey_rejected(self):
        """PRD section 3.2: "The project must still be in `DRAFT` (otherwise
        `ERR_INVALID_STATE`), and a project may have at most one survey — a
        second attempt is rejected with `ERR_SURVEY_ALREADY_EXISTS`."

        Design: Corner/validations/create_second_survey_rejected
        """
        project = create_project_entity(name="P-V1")
        first = api_client.create_survey(
            create_survey_payload(project["id"]), ADMIN)
        validate_success(first, expected_status=201)
        resp = api_client.create_survey(
            create_survey_payload(project["id"], surveyor_name="Insp B",
                                  survey_date="2026-07-21T00:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_SURVEY_ALREADY_EXISTS)

    def test_sample_result_before_lab_submit_rejected(self):
        """PRD section 3.2: "Once the survey is `IN_LAB`, an
        `IndustrialHygienist` records each sample's result, moving the sample
        from `PENDING` to `REPORTED`. Recording against a survey that is not
        `IN_LAB` fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/sample_result_before_lab_submit_rejected
        """
        project = create_project_entity(name="P-SM1")
        survey = create_survey_entity(project["id"])
        sample = add_sample(survey["id"])
        # Survey is still DRAFT (never submitted).
        resp = api_client.record_sample_result(
            sample["id"], {"lab_result": "POSITIVE", "asbestos_pct": 40}, IH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_sample_create_on_in_lab_survey_rejected(self):
        """PRD section 3.2: "While the survey remains in `DRAFT`, the
        administrator adds **bulk samples** to it (adding to a survey that has
        left `DRAFT` fails with `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/sample_create_on_in_lab_survey_rejected
        """
        project = create_project_entity(name="P-SM2")
        survey = create_survey_entity(project["id"])
        add_sample(survey["id"])
        submit_survey(survey["id"])
        resp = api_client.create_sample(
            create_sample_payload(
                survey["id"], material="floor tile", location_desc="kitchen",
                quantity_sq_ft=50, friable=False),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_finalize_with_pending_samples_rejected(self):
        """PRD section 3.2: "Finalizing the survey moves it from `IN_LAB` to
        `FINALIZED` and is permitted only when every sample of the survey has
        been reported; if even one sample is still `PENDING`, finalization
        fails with `ERR_SAMPLES_STILL_PENDING`."

        Design: Corner/state_machines/finalize_survey_with_pending_samples_rejected
        """
        project = create_project_entity(name="P-SM3")
        survey = create_survey_entity(project["id"])
        sample_a = add_sample(survey["id"])
        add_sample(survey["id"], material="floor tile",
                   location_desc="kitchen", quantity_sq_ft=50, friable=False)
        submit_survey(survey["id"])
        report_sample(sample_a["id"], lab_result="NEGATIVE")
        resp = api_client.finalize_survey(survey["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SAMPLES_STILL_PENDING)
        survey_after = get_survey(survey["id"])
        assert survey_after["status"] == "IN_LAB", \
            "survey must remain IN_LAB after a rejected finalize"

    def test_resubmit_finalized_survey_rejected(self):
        """PRD section 2.10: "Terminal states are locked. A `CLOSED` project,
        a `FINALIZED` survey, a `REPORTED` sample or air test, a `COMPLETED`
        or `CANCELLED` assignment, a `SUPERSEDED` notification, a `CONFIRMED`
        or `VOIDED` manifest, a `SUSPENDED` facility, and a `RETURNED`
        relocation record admit no further transitions; any attempt to act on
        a resource from a state that does not permit the transition — terminal
        or otherwise — is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/resubmit_finalized_survey_rejected
        """
        project = create_project_entity(name="P-SM4")
        survey = create_survey_entity(project["id"])
        sample = add_sample(survey["id"])
        submit_survey(survey["id"])
        report_sample(sample["id"])
        finalize_survey(survey["id"])
        resp = api_client.submit_survey(survey["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_contractor_admin_cannot_record_sample_result(self):
        """PRD section 2.1: "`IndustrialHygienist` — the independent
        third-party hygienist/laboratory. Records sample results and air-test
        results, and is the only role that may create or report
        `CLEARANCE`-phase air tests."
        PRD section 2.1: "Beyond authentication, each endpoint restricts which
        roles may call it; a call from a role outside the permitted set is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/contractor_admin_cannot_record_sample_result
        """
        project = create_project_entity(name="P-R4")
        survey = create_survey_entity(project["id"])
        sample = add_sample(survey["id"])
        submit_survey(survey["id"])
        resp = api_client.record_sample_result(
            sample["id"], {"lab_result": "NEGATIVE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        samples = list_samples(survey["id"])
        pending = [s for s in samples if s["id"] == sample["id"]]
        assert pending and pending[0]["status"] == "PENDING", \
            "sample must remain PENDING after a rejected result recording"


class TestSampleListing:
    def test_samples_list_pagination_envelope(self):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned: it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter skips a number of items from the start of the
        result set and defaults to 0."
        PRD section 2.3: "Every list response carries `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/samples_list_pagination_envelope
        """
        project = create_project_entity(name="P-E1")
        survey = create_survey_entity(project["id"])
        add_sample(survey["id"])
        add_sample(survey["id"], material="floor tile",
                   location_desc="kitchen", quantity_sq_ft=50, friable=False)
        add_sample(survey["id"], material="ceiling texture",
                   location_desc="hall", quantity_sq_ft=200, friable=True)

        resp1 = api_client.list_samples(survey["id"], ADMIN,
                                        params={"limit": 2, "offset": 0})
        page1, meta1 = validate_paginated(resp1)
        assert resp1.json()["response_type"] == "array", \
            "list responses must use the array response_type"
        assert isinstance(meta1.get("api_request_id"), str), \
            "meta.api_request_id must be present"
        assert len(page1) == 2, "page 1 with limit 2 must hold 2 samples"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        resp2 = api_client.list_samples(survey["id"], ADMIN,
                                        params={"limit": 2, "offset": 2})
        page2, meta2 = validate_paginated(resp2)
        assert len(page2) == 1, "page 2 with offset 2 must hold 1 sample"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        for sample in page1 + page2:
            assert_sample(sample)


class TestSurveyQuantityVariants:
    def test_provisional_counts_pending_as_assumed_positive(self):
        """PRD section 3.2: "`acm_sq_ft_provisional` — the planning variant —
        sums `quantity_sq_ft` over all samples of the survey whose
        `lab_result` is `PENDING` or `POSITIVE`."
        PRD section 3.2: "`acm_sq_ft_final` — the regulatory variant — sums
        `quantity_sq_ft` over samples whose `lab_result` is `POSITIVE` only."
        PRD section 3.2: "`friable_acm_sq_ft_final` sums `quantity_sq_ft`
        over samples whose `lab_result` is `POSITIVE` and whose `friable`
        flag is true."

        Design: Difficulty/dual_variant_calc/survey_provisional_assumes_pending_vs_final_positive_only
        """
        project = create_project_entity(name="P-DV1")
        survey = create_survey_entity(project["id"])
        sample_a = add_sample(survey["id"], quantity_sq_ft=100, friable=True)
        add_sample(survey["id"], material="floor tile",
                   location_desc="kitchen", quantity_sq_ft=50, friable=False)
        submit_survey(survey["id"])
        report_sample(sample_a["id"], lab_result="POSITIVE", asbestos_pct=40)
        # Sample B stays PENDING.
        data = get_survey(survey["id"])
        assert_survey(data)
        assert data["acm_sq_ft_provisional"] == 150, (
            f"provisional counts PENDING+POSITIVE: expected 150, "
            f"got {data['acm_sq_ft_provisional']}"
        )
        assert data["acm_sq_ft_final"] == 100, (
            f"final counts POSITIVE only: expected 100, "
            f"got {data['acm_sq_ft_final']}"
        )
        assert data["friable_acm_sq_ft_final"] == 100
        assert data["acm_sq_ft_provisional"] != data["acm_sq_ft_final"], \
            "variants must diverge while a sample remains unresolved"

    def test_provisional_converges_to_final_when_pending_resolves(self):
        """PRD section 3.2: "Pending samples are treated as assumed-positive,
        so this variant diverges from the final figure whenever any sample
        remains unresolved."
        PRD section 3.2: "`acm_sq_ft_final` — the regulatory variant — sums
        `quantity_sq_ft` over samples whose `lab_result` is `POSITIVE` only."

        Design: Difficulty/dual_variant_calc/survey_provisional_assumes_pending_vs_final_positive_only
        """
        project = create_project_entity(name="P-DV1B")
        survey = create_survey_entity(project["id"])
        sample_a = add_sample(survey["id"], quantity_sq_ft=100, friable=True)
        sample_b = add_sample(survey["id"], material="floor tile",
                              location_desc="kitchen", quantity_sq_ft=50,
                              friable=False)
        submit_survey(survey["id"])
        report_sample(sample_a["id"], lab_result="POSITIVE", asbestos_pct=40)
        mid = get_survey(survey["id"])
        assert mid["acm_sq_ft_provisional"] == 150
        assert mid["acm_sq_ft_final"] == 100
        report_sample(sample_b["id"], lab_result="NEGATIVE")
        data = get_survey(survey["id"])
        assert data["acm_sq_ft_provisional"] == 100, (
            f"with no PENDING samples the provisional variant must converge: "
            f"expected 100, got {data['acm_sq_ft_provisional']}"
        )
        assert data["acm_sq_ft_final"] == 100
        assert data["acm_sq_ft_provisional"] == data["acm_sq_ft_final"]
