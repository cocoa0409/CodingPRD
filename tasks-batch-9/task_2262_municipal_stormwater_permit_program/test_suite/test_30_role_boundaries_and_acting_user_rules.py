"""Where the role matrix draws its lines, where it deliberately shares an
operation, and where the rule keys on the acting user rather than the role."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    CLERK_HEADERS,
    IDDE_HEADERS,
    INSPECTOR_HEADERS,
    MANAGER_HEADERS,
    MANAGER_TWO,
    MANAGER_TWO_HEADERS,
    OFFICER_HEADERS,
    OPERATIONS_HEADERS,
    OPERATIONS_ONE,
    OPERATIONS_TWO,
    OPERATIONS_TWO_HEADERS,
    make_property_owner_headers,
)

SAMPLE_AT = "2026-07-05T09:00:00Z"


class TestExclusiveOperationsStayWithTheirRole:
    """Five boundaries the domain tempts an implementation to blur."""

    @pytest.fixture
    def program(self, active_program):
        """An ACTIVE term carrying OF-01, one construction site and one account."""
        site = fx.create_site(
            active_program["term_id"],
            site_name="SITE-A",
            operator_name="Northgate Civil",
            disturbed_acres=3.00,
        )
        account = fx.create_account(active_program["term_id"], parcel_id="P-1000")
        return {
            "term_id": active_program["term_id"],
            "outfall": active_program["outfalls"]["OF-01"],
            "site": site,
            "account": account,
        }

    def test_01_the_plan_reviewer_holds_no_stop_work_authority(self, program):
        """Reviewing the plan and stopping the work are different offices.

        PRD: "`ConstructionInspector` — exclusively submits and reviews erosion and
        sediment control plans, closes stabilised sites, and opens, populates and finalizes
        both inspection programmes. Holds no stop-work authority of its own: a site is
        stopped either by the finalize cascade or by an `EnforcementOfficer`." And: "A role
        not listed for the endpoint yields `ERR_UNAUTHORIZED` (403). Because this precedes
        every existence and state check, an unauthorised caller can never learn whether a
        resource exists or what state it is in."

        Design: Corner/rbac/roles_cannot_perform_each_others_exclusive_operations
        """
        response = api_client.stop_work(
            program["site"]["id"],
            factories.stop_work_payload(reason="Sediment leaving the site"),
            INSPECTOR_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        site = fx.read_site(program["site"]["id"])
        assert site["field_status"] == "PRE_CONSTRUCTION", (
            f"the refusal moved nothing, got {site['field_status']}"
        )

    def test_02_the_enforcement_officer_cannot_write_the_documentation(self, program):
        """The officer acts on inspections but never authors one.

        PRD: "`EnforcementOfficer` — holds stop-work and release authority and the whole
        enforcement ladder: issuing, escalating, closing and rescinding actions. Cannot
        create or finalize the inspection that documents a violation." And: "A role not
        listed for the endpoint yields `ERR_UNAUTHORIZED` (403)."

        Design: Corner/rbac/roles_cannot_perform_each_others_exclusive_operations
        """
        response = api_client.create_inspection(
            factories.esc_inspection_payload(
                program["site"]["id"], "2026-07-01", "2026-07-31"
            ),
            OFFICER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        _, meta = validate_paginated(api_client.list_inspections(INSPECTOR_HEADERS))
        assert meta["total_count"] == 0, (
            f"no inspection was created, got {meta['total_count']}"
        )

    def test_03_owning_the_term_does_not_open_the_operations_or_utility_desks(
        self, program
    ):
        """The manager owns the permit and neither sweeps nor bills.

        PRD: "`StormwaterProgramManager` — owns the permit term, the minimum control
        measure set, monitoring assessment and the annual report. Exclusively creates,
        activates and expires permit terms; registers and retires control measures; retires
        outfalls; and opens, compiles, certifies and submits annual reports." And:
        "`MunicipalOperationsSupervisor` — runs municipal operations pollution prevention:
        exclusively appends street-sweeping runs, and shares outfall creation, observation
        recording, sample adjudication, load assessment and measurable-goal progress
        reporting." And: "`UtilityBillingClerk` — runs the utility: exclusively opens
        accounts, records impervious remeasurements, executes billing runs, and reviews and
        revokes credit applications."

        Design: Corner/rbac/roles_cannot_perform_each_others_exclusive_operations
        """
        sweeping = api_client.create_sweeping_run(
            program["outfall"]["id"],
            factories.sweeping_run_payload("2026-08-01", "2026-08-10", 5.00),
            MANAGER_HEADERS,
        )
        validate_error(sweeping, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        billing = api_client.create_billing_run(
            program["term_id"],
            factories.billing_run_payload("FINAL", "2026-01-01", "2026-12-31"),
            MANAGER_HEADERS,
        )
        validate_error(billing, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        outfall = fx.read_outfall(program["outfall"]["id"])
        assert outfall["sweeping_runs"] == [], "nothing was appended to the log"
        account = fx.read_account(program["account"]["id"])
        assert account["last_billed_run_type"] is None, (
            f"and nothing was billed, got {account['last_billed_run_type']}"
        )

    def test_04_the_billing_clerk_stays_out_of_the_field_and_the_report(self, program):
        """Screening an outfall and opening a report both sit elsewhere.

        PRD: "`UtilityBillingClerk` — runs the utility: exclusively opens accounts,
        records impervious remeasurements, executes billing runs, and reviews and revokes
        credit applications. Cannot resubmit a returned application; only its applicant
        can." And: "A role not listed for the endpoint yields `ERR_UNAUTHORIZED` (403)."

        Design: Corner/rbac/roles_cannot_perform_each_others_exclusive_operations
        """
        screening = api_client.create_observation(
            program["outfall"]["id"],
            {
                "observation_type": "DRY_WEATHER_SCREENING",
                "observed_at": "2026-08-01T08:00:00Z",
                "dry_weather_flow_present": False,
            },
            CLERK_HEADERS,
        )
        validate_error(screening, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        report = api_client.create_annual_report(
            factories.annual_report_payload(
                program["term_id"], "2026-01-01", "2026-12-31"
            ),
            CLERK_HEADERS,
        )
        validate_error(report, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        outfall = fx.read_outfall(program["outfall"]["id"])
        assert outfall["screening_count"] == 0, (
            f"no screening was recorded, got {outfall['screening_count']}"
        )
        _, meta = validate_paginated(
            api_client.list_term_annual_reports(program["term_id"], MANAGER_HEADERS)
        )
        assert meta["total_count"] == 0, (
            f"and no report was opened, got {meta['total_count']}"
        )

    def test_05_the_property_owner_sees_only_its_own_account(self, program):
        """It cannot read the operational surface nor remeasure its own parcel.

        PRD: "`PropertyOwner` — a billed parcel owner. Exclusively resubmits its own
        returned credit application, may file an application jointly with the clerk, and may
        read its own account, its credit applications and the permanent-control inventory.
        The entire operational surface — screenings, cases, inspections, enforcement and
        reports — is closed to it." And: "Where a role column reads "All roles except
        `PropertyOwner`", the six operational roles are authorised and `PropertyOwner` is
        not."

        Design: Corner/rbac/roles_cannot_perform_each_others_exclusive_operations
        """
        account = program["account"]
        owner = make_property_owner_headers(account["id"])

        validate_error(
            api_client.list_inspections(owner), ApiErrorId.ERR_UNAUTHORIZED.value, 403
        )
        validate_error(
            api_client.get_permit_term(program["term_id"], owner),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.create_impervious_update(
                account["id"],
                factories.impervious_update_payload(4500.0, account["version"]),
                owner,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

        stored = fx.read_account(account["id"])
        assert stored["version"] == account["version"], (
            "the refused remeasurement spent no version, expected "
            f"{account['version']}, got {stored['version']}"
        )
        assert stored["impervious_area_sqft"] == pytest.approx(3000.0, abs=0.01), (
            f"and the measured area is unchanged, got {stored['impervious_area_sqft']}"
        )
        assert validate_success(api_client.get_account(account["id"], owner))["id"] == (
            account["id"]
        ), "its own account is still readable"


class TestSharedOperationsAnswerToEitherHolder:
    """Each shared operation exercised from the second holder of the pair."""

    def test_06_the_operations_supervisor_may_extend_the_inventory(
        self, active_program
    ):
        """OF-01 came from the manager; OF-02 comes from operations.

        PRD: "The **outfall inventory** is built by a `StormwaterProgramManager` or a
        `MunicipalOperationsSupervisor`, each new outfall naming the `permit_term_id` of its
        term, the field `outfall_code` that identifies it (1 to 32 characters, unique within
        the term), the `receiving_water` it discharges to, the `drainage_area_acres` of
        contributing area (which must be greater than 0), and the `priority_tier` assigned
        during inventory, one of `HIGH`, `MEDIUM` or `LOW`."

        Design: Corner/rbac/shared_operations_are_open_to_both_holders_of_the_pair
        """
        outfall = validate_success(
            api_client.create_outfall(
                factories.outfall_payload(
                    active_program["term_id"],
                    "OF-02",
                    drainage_area_acres=12.00,
                    priority_tier="LOW",
                    baseline_concentration_mg_per_l=0.20,
                    design_runoff_kl=8000,
                    sweeping_capacity_lane_miles_per_month=10.00,
                ),
                OPERATIONS_HEADERS,
            ),
            201,
        )

        assert outfall["outfall_code"] == "OF-02", "the second outfall is on the books"
        assert outfall["status"] == "ACTIVE", "and it is active from the start"
        assert outfall["priority_tier"] == "LOW", "at the tier operations assigned"

    def test_07_the_operations_supervisor_may_report_a_measurable_goal(
        self, active_program
    ):
        """Progress reporting is shared, and twelve of twelve is MET.

        PRD: "The manager or a `MunicipalOperationsSupervisor` reports progress by supplying
        `measurable_goal_actual`, which requires the measure's `status` to be `ACTIVE`; the
        call stamps `last_progress_reported_at` from the logical clock." And: "otherwise it
        is 100 multiplied by `measurable_goal_actual`, divided by `measurable_goal_target`,
        rounded to 2 decimal places." And: "If `attainment_pct` is at least 100.00, the
        result is `MET`."

        Design: Corner/rbac/shared_operations_are_open_to_both_holders_of_the_pair
        """
        measure_id = active_program["measures"]["PUBLIC_EDUCATION"]["id"]

        measure = validate_success(
            api_client.report_measure_progress(
                measure_id, factories.report_progress_payload(12.00), OPERATIONS_HEADERS
            )
        )

        assert measure["measurable_goal_actual"] == pytest.approx(12.00, abs=0.01), (
            f"the reported actual landed, got {measure['measurable_goal_actual']}"
        )
        assert measure["attainment_pct"] == pytest.approx(100.00, abs=0.01), (
            f"twelve of twelve is 100.00, got {measure['attainment_pct']}"
        )
        assert measure["goal_status"] == "MET", (
            f"which is the MET band, got {measure['goal_status']}"
        )
        assert measure["last_progress_reported_at"] == "2026-08-01T00:00:00Z", (
            f"stamped from the clock, got {measure['last_progress_reported_at']}"
        )

    def test_08_the_manager_may_enrol_a_site_and_record_its_agreement(
        self, active_program
    ):
        """Site enrolment, facility inventory and the agreement are all shared.

        PRD: "A **post-construction facility** is a permanent structural control
        inventoried against a `construction_site_id` by a `ConstructionInspector` or the
        `StormwaterProgramManager`." And: "Recording the agreement supplies the instrument's
        `agreement_reference`, the `recorded_at` instant of recordation and the
        `inspection_interval_months` agreed for maintenance inspection, which must be
        between 1 and 60 inclusive." And: "Enrol a construction site of one acre or more
        under the permit term | ConstructionInspector, StormwaterProgramManager"

        Design: Corner/rbac/shared_operations_are_open_to_both_holders_of_the_pair
        """
        site = validate_success(
            api_client.create_construction_site(
                factories.construction_site_payload(
                    active_program["term_id"],
                    site_name="SITE-C",
                    disturbed_acres=3.00,
                    operator_name="Southline Build",
                ),
                MANAGER_HEADERS,
            ),
            201,
        )
        facility = validate_success(
            api_client.create_post_construction_facility(
                factories.facility_payload(
                    site["id"],
                    "PRIVATE",
                    facility_type="INFILTRATION_TRENCH",
                    design_capacity_cf=1500.00,
                    service_area_acres=0.90,
                ),
                MANAGER_HEADERS,
            ),
            201,
        )

        recorded = validate_success(
            api_client.record_agreement(
                facility["id"],
                factories.record_agreement_payload(
                    "2026-08-01T00:00:00Z",
                    24,
                    agreement_reference="INST-2026-90",
                ),
                MANAGER_HEADERS,
            ),
            200,
        )

        assert recorded["agreement_status"] == "RECORDED", (
            f"the manager recorded it, got {recorded['agreement_status']}"
        )
        assert recorded["inspection_interval_months"] == 24, (
            f"on a two-year interval, got {recorded['inspection_interval_months']}"
        )
        assert recorded["agreement_reference"] == "INST-2026-90", "under its reference"
        assert recorded["credit_eligible"] is True, "and the control is now eligible"

    def test_09_recording_and_adjudicating_a_sample_are_separately_shared(
        self, active_program
    ):
        """The investigator records it and a second operations user adjudicates.

        PRD: "Field observations at an outfall are recorded by an `IDDEInvestigator` or a
        `MunicipalOperationsSupervisor` and come in two kinds, discriminated by
        `observation_type`." And: "Adjudication is performed by a
        `MunicipalOperationsSupervisor` or a `StormwaterProgramManager` supplying a
        `decision` of `VALIDATE` or `REJECT`; it applies only to a `WET_WEATHER_SAMPLE`
        whose `validation_status` is `PENDING`" And: "`sample_load_lb` is the sample's
        `pollutant_concentration_mg_per_l` multiplied by its `runoff_volume_kl`, multiplied
        by the unit conversion factor 0.00220462 pounds per milligram-per-litre-kilolitre,
        rounded to 4 decimal places."

        Design: Corner/rbac/shared_operations_are_open_to_both_holders_of_the_pair
        """
        outfall = validate_success(
            api_client.create_outfall(
                factories.outfall_payload(
                    active_program["term_id"],
                    "OF-02",
                    drainage_area_acres=12.00,
                    priority_tier="LOW",
                    baseline_concentration_mg_per_l=0.20,
                    design_runoff_kl=8000,
                    sweeping_capacity_lane_miles_per_month=10.00,
                ),
                OPERATIONS_HEADERS,
            ),
            201,
        )

        sample = validate_success(
            api_client.create_observation(
                outfall["id"],
                factories.sample_payload(SAMPLE_AT, 0.20, 8000.00),
                IDDE_HEADERS,
            ),
            201,
        )
        assert sample["validation_status"] == "PENDING", "a sample awaits adjudication"

        adjudicated = validate_success(
            api_client.validate_observation(
                sample["id"],
                factories.validate_observation_payload("VALIDATE"),
                OPERATIONS_TWO_HEADERS,
            )
        )

        assert adjudicated["validation_status"] == "VALIDATED", (
            f"the second operations user validated it, got "
            f"{adjudicated['validation_status']}"
        )
        assert adjudicated["sample_load_lb"] == pytest.approx(3.5274, abs=0.00005), (
            "0.20 times 8000 times 0.00220462 is 3.5274, got "
            f"{adjudicated['sample_load_lb']}"
        )

    def test_10_the_operations_supervisor_may_assess_the_annual_load(
        self, active_program
    ):
        """A FINAL assessment counts only the one validated sample.

        PRD: "The **annual pollutant load** at one outfall is assessed on demand by a
        `StormwaterProgramManager` or `MunicipalOperationsSupervisor`, who supplies a
        `variant` of `FINAL` or `PROVISIONAL` and the `reporting_year` being assessed." And:
        "In the `FINAL` variant the projected shortfall is treated as zero, so only validated
        samples count. Either way, `gross_load_lb` is the resulting total rounded to 2
        decimal places." And: "When the term's `tmdl_applicable` is false the status is
        `NOT_ASSESSED`."

        Design: Corner/rbac/shared_operations_are_open_to_both_holders_of_the_pair
        """
        outfall = validate_success(
            api_client.create_outfall(
                factories.outfall_payload(
                    active_program["term_id"],
                    "OF-02",
                    drainage_area_acres=12.00,
                    priority_tier="LOW",
                    baseline_concentration_mg_per_l=0.20,
                    design_runoff_kl=8000,
                    sweeping_capacity_lane_miles_per_month=10.00,
                ),
                OPERATIONS_HEADERS,
            ),
            201,
        )
        sample = validate_success(
            api_client.create_observation(
                outfall["id"],
                factories.sample_payload(SAMPLE_AT, 0.20, 8000.00),
                IDDE_HEADERS,
            ),
            201,
        )
        validate_success(
            api_client.validate_observation(
                sample["id"],
                factories.validate_observation_payload("VALIDATE"),
                OPERATIONS_TWO_HEADERS,
            )
        )

        assessment = validate_success(
            api_client.create_load_assessment(
                outfall["id"],
                factories.load_assessment_payload("FINAL", 2026),
                OPERATIONS_HEADERS,
            )
        )

        assert assessment["validated_sample_count"] == 1, (
            f"one sample is in hand, got {assessment['validated_sample_count']}"
        )
        assert assessment["gross_load_lb"] == pytest.approx(3.53, abs=0.01), (
            f"3.5274 rounds to 3.53 at two places, got {assessment['gross_load_lb']}"
        )
        assert assessment["sweeping_credit_lb"] == pytest.approx(0.00, abs=0.01), (
            f"no lane miles were swept here, got {assessment['sweeping_credit_lb']}"
        )
        assert assessment["net_load_lb"] == pytest.approx(3.53, abs=0.01), (
            f"so the net equals the gross, got {assessment['net_load_lb']}"
        )
        assert assessment["tmdl_status"] == "NOT_ASSESSED", (
            f"the term carries no allocation, got {assessment['tmdl_status']}"
        )


class TestSegregationOfDutiesKeysOnTheActingUser:
    """The same role, a different identity, and the opposite outcome."""

    @pytest.fixture
    def pending_sample(self, active_program):
        """A wet-weather sample of 0.45 mg/l over 40000 kL recorded by ops-01."""
        outfall = active_program["outfalls"]["OF-01"]
        sample = fx.record_sample(outfall["id"], SAMPLE_AT, 0.45, 40000.00)
        return {"term_id": active_program["term_id"], "sample": sample}

    def test_11_the_recorder_of_a_sample_may_not_adjudicate_it(self, pending_sample):
        """ops-01 recorded it, so ops-01 cannot be the one to validate it.

        PRD: "The adjudicator must not be the `recorded_by_user_id` that recorded the
        observation, otherwise `ERR_SELF_VALIDATION_FORBIDDEN`." And:
        "`ERR_SELF_VALIDATION_FORBIDDEN`, `ERR_INSPECTOR_CANNOT_ENFORCE` and
        `ERR_SAME_USER_CERTIFICATION` (all 409), covering sample adjudication, enforcement
        issuance and report certification respectively."

        Design: Corner/rbac/segregation_of_duties_keys_on_the_acting_user_not_on_the_role
        """
        assert pending_sample["sample"]["recorded_by_user_id"] == OPERATIONS_ONE, (
            "the sample was recorded by ops-01"
        )

        response = api_client.validate_observation(
            pending_sample["sample"]["id"],
            factories.validate_observation_payload("VALIDATE"),
            OPERATIONS_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_SELF_VALIDATION_FORBIDDEN.value, 409)

    def test_12_a_second_holder_of_the_same_role_may(self, pending_sample):
        """The identical payload and role from ops-02 goes through.

        PRD: "The adjudicator must not be the `recorded_by_user_id` that recorded the
        observation, otherwise `ERR_SELF_VALIDATION_FORBIDDEN`." And: "Both decisions stamp
        `validated_at` from the logical clock: `VALIDATE` writes `VALIDATED` and admits the
        sample's `sample_load_lb` into both load variants" And: "`sample_load_lb` is the
        sample's `pollutant_concentration_mg_per_l` multiplied by its `runoff_volume_kl`,
        multiplied by the unit conversion factor 0.00220462 pounds per
        milligram-per-litre-kilolitre, rounded to 4 decimal places."

        Design: Corner/rbac/segregation_of_duties_keys_on_the_acting_user_not_on_the_role
        """
        validate_error(
            api_client.validate_observation(
                pending_sample["sample"]["id"],
                factories.validate_observation_payload("VALIDATE"),
                OPERATIONS_HEADERS,
            ),
            ApiErrorId.ERR_SELF_VALIDATION_FORBIDDEN.value,
            409,
        )

        adjudicated = validate_success(
            api_client.validate_observation(
                pending_sample["sample"]["id"],
                factories.validate_observation_payload("VALIDATE"),
                OPERATIONS_TWO_HEADERS,
            )
        )

        assert adjudicated["validation_status"] == "VALIDATED", (
            f"ops-02 differs from ops-01, got {adjudicated['validation_status']}"
        )
        assert adjudicated["validated_at"] == "2026-08-01T00:00:00Z", (
            f"stamped from the clock, got {adjudicated['validated_at']}"
        )
        assert adjudicated["sample_load_lb"] == pytest.approx(39.6832, abs=0.00005), (
            "0.45 times 40000 times 0.00220462 is 39.6832, got "
            f"{adjudicated['sample_load_lb']}"
        )

    @pytest.fixture
    def compiled_report(self, pending_sample):
        """A report compiled by mgr-01 once the window holds no pending sample."""
        validate_success(
            api_client.validate_observation(
                pending_sample["sample"]["id"],
                factories.validate_observation_payload("VALIDATE"),
                OPERATIONS_TWO_HEADERS,
            )
        )
        report = fx.create_report(pending_sample["term_id"], "2026-01-01", "2026-12-31")
        return fx.compile_report(report["id"], pending_sample["term_id"])

    def test_13_the_compiler_of_a_report_may_not_certify_it(self, compiled_report):
        """mgr-01 assembled the figures, so mgr-01 cannot attest to them.

        PRD: "Certifying an annual report requires the actor to differ from its
        `compiled_by_user_id`, otherwise `ERR_SAME_USER_CERTIFICATION`." And: "The
        certifying manager supplies the `certification_statement`, must not be the
        `compiled_by_user_id` that compiled the report — otherwise
        `ERR_SAME_USER_CERTIFICATION` — and may not certify at all while the term's
        `compliance_posture` is `NON_COMPLIANT`, which is refused with
        `ERR_POSTURE_NON_COMPLIANT`."

        Design: Corner/rbac/segregation_of_duties_keys_on_the_acting_user_not_on_the_role
        """
        assert compiled_report["status"] == "COMPILED", (
            f"the report is ready to certify, got {compiled_report['status']}"
        )

        response = api_client.certify_annual_report(
            compiled_report["id"], factories.certify_report_payload(), MANAGER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_SAME_USER_CERTIFICATION.value, 409)

        report = fx.read_report(compiled_report["id"])
        assert report["status"] == "COMPILED", (
            f"the refusal left it compiled, got {report['status']}"
        )
        assert report["certified_by_user_id"] is None, "and nobody has attested yet"

    def test_14_the_second_manager_certifies_the_same_report(self, compiled_report):
        """A different identity in the same office satisfies the rule.

        PRD: "Certifying an annual report requires the actor to differ from its
        `compiled_by_user_id`, otherwise `ERR_SAME_USER_CERTIFICATION`." And: "Certification
        stamps `certified_at` and records `certified_by_user_id` and the statement." And: "A
        `NON_COMPLIANT` posture blocks annual report certification, which is how a single
        behind measure eventually reaches the end of the cascade chain."

        Design: Corner/rbac/segregation_of_duties_keys_on_the_acting_user_not_on_the_role
        """
        term = fx.read_term(compiled_report["permit_term_id"])
        assert term["compliance_posture"] != "NON_COMPLIANT", (
            f"the posture gate is open, got {term['compliance_posture']}"
        )

        certified = validate_success(
            api_client.certify_annual_report(
                compiled_report["id"],
                factories.certify_report_payload(),
                MANAGER_TWO_HEADERS,
            )
        )

        assert certified["status"] == "CERTIFIED", (
            f"the attestation landed, got {certified['status']}"
        )
        assert certified["certified_by_user_id"] == MANAGER_TWO, (
            f"and it was mgr-02 who signed, got {certified['certified_by_user_id']}"
        )
        assert certified["certified_at"] == "2026-08-01T00:00:00Z", (
            f"stamped from the clock, got {certified['certified_at']}"
        )


class TestOnlyTheApplicantMayResubmit:
    """A 403 that is not ERR_UNAUTHORIZED, and one that is."""

    @pytest.fixture
    def two_returned_applications(self, active_program):
        """Two accounts, each with one RETURNED application filed by its own owner."""
        term_id = active_program["term_id"]
        account_a = fx.create_account(term_id, parcel_id="P-1000", owner_name="Ada Owner")
        account_b = fx.create_account(term_id, parcel_id="P-2000", owner_name="Ben Owner")
        application_a = fx.setup_returned_credit_application(account_a, 0.1500)
        application_b = fx.setup_returned_credit_application(account_b, 0.1500)
        return {
            "account_a": account_a,
            "account_b": account_b,
            "application_a": application_a,
            "application_b": application_b,
        }

    def test_15_another_owner_is_refused_with_its_own_code(
        self, two_returned_applications
    ):
        """The role passes and the ownership rule refuses, distinctly.

        PRD: "A returned application is revived by its own applicant, and only by the
        `PropertyOwner` whose `X-User-ID` equals `applicant_user_id`; anyone else is refused
        with `ERR_NOT_APPLICANT`." And: "At the same level, resubmission by someone other
        than the original applicant yields `ERR_NOT_APPLICANT` (403)."

        Design: Corner/rbac/a_property_owner_cannot_resubmit_another_owners_application
        """
        response = api_client.resubmit_fee_credit_application(
            two_returned_applications["application_a"]["id"],
            factories.credit_resubmit_payload(
                0.2000, bmp_description="Swale along the frontage, photographs attached"
            ),
            make_property_owner_headers(two_returned_applications["account_b"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_NOT_APPLICANT.value, 403)

        application = fx.read_application(
            two_returned_applications["application_a"]["id"]
        )
        assert application["status"] == "RETURNED", (
            f"the application is still out for revision, got {application['status']}"
        )
        assert application["resubmission_count"] == 0, "and nothing was counted"

    def test_16_the_reviewing_clerk_is_refused_by_the_role_check(
        self, two_returned_applications
    ):
        """The clerk reviews and revokes but never resubmits.

        PRD: "Resubmit a returned application with a revised request | PropertyOwner" And:
        "A role not listed for the endpoint yields `ERR_UNAUTHORIZED` (403). Because this
        precedes every existence and state check, an unauthorised caller can never learn
        whether a resource exists or what state it is in."

        Design: Corner/rbac/a_property_owner_cannot_resubmit_another_owners_application
        """
        response = api_client.resubmit_fee_credit_application(
            two_returned_applications["application_a"]["id"],
            factories.credit_resubmit_payload(
                0.2000, bmp_description="Swale along the frontage, photographs attached"
            ),
            CLERK_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    def test_17_the_original_applicant_revives_its_own_application(
        self, two_returned_applications
    ):
        """The identical body from the account that filed it is accepted.

        PRD: "It carries a fresh `requested_credit_pct` and `bmp_description`, which
        overwrite the stored values, clears `return_reason` to null, writes `SUBMITTED` back
        into `status`, increments `resubmission_count` by one, and returns the requested
        percentage to the `INTERIM` pool."

        Design: Corner/rbac/a_property_owner_cannot_resubmit_another_owners_application
        """
        resubmitted = validate_success(
            api_client.resubmit_fee_credit_application(
                two_returned_applications["application_a"]["id"],
                factories.credit_resubmit_payload(
                    0.2000,
                    bmp_description="Swale along the frontage, photographs attached",
                ),
                make_property_owner_headers(
                    two_returned_applications["account_a"]["id"]
                ),
            )
        )

        assert resubmitted["status"] == "SUBMITTED", (
            f"the application is back in the queue, got {resubmitted['status']}"
        )
        assert resubmitted["resubmission_count"] == 1, (
            f"one revision has been used, got {resubmitted['resubmission_count']}"
        )
        assert resubmitted["return_reason"] is None, "the return reason was cleared"
        assert resubmitted["requested_credit_pct"] == pytest.approx(
            0.2000, abs=0.00005
        ), (
            "and the revised request overwrote the old one, got "
            f"{resubmitted['requested_credit_pct']}"
        )

    def test_18_an_owner_sees_only_the_applications_on_its_own_account(
        self, two_returned_applications
    ):
        """Filtering by the account narrows two rows down to one.

        PRD: "Fee credit applications filter on `stormwater_account_id`,
        `post_construction_facility_id` and `status`." And: "ownership checks on any
        resource that references a `StormwaterAccount` compare the resource's account
        foreign key to `X-User-ID`, and a fee credit application additionally records the
        submitting owner in `applicant_user_id` and compares it on resubmission."

        Design: Corner/rbac/a_property_owner_cannot_resubmit_another_owners_application
        """
        account_a = two_returned_applications["account_a"]

        rows, meta = validate_paginated(
            api_client.list_fee_credit_applications(
                make_property_owner_headers(account_a["id"]),
                {"stormwater_account_id": account_a["id"]},
            )
        )

        assert meta["total_count"] == 1, (
            f"one application belongs to account A, got {meta['total_count']}"
        )
        assert rows[0]["id"] == two_returned_applications["application_a"]["id"], (
            "and it is the one filed against it"
        )
        assert rows[0]["applicant_user_id"] == account_a["id"], (
            f"filed by the account's own owner, got {rows[0]['applicant_user_id']}"
        )
