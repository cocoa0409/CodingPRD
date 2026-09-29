"""Role exclusivity, shared operations, segregation of duties and identity binding."""

from test_helpers import (
    ADMIN_HEADERS,
    ADMIN_ONE,
    ApiErrorId,
    IncomeVerificationStatus,
    InspectionStatus,
    InspectionType,
    MEASURE_HP_HVAC,
    ProjectStatus,
    REVIEWER_HEADERS,
    REVIEWER_ONE,
    REVIEWER_TWO,
    REVIEWER_TWO_HEADERS,
    ReservationStatus,
    StackingDeclarationStatus,
    build_hvac_heat_pump_payload,
    build_income_verification_payload,
    build_inspection_payload,
    build_measure_result,
    build_pass_result_payload,
    build_project_measure,
    build_project_payload,
    build_project_review_payload,
    build_reservation_payload,
    build_stacking_payload,
    build_verify_decision_payload,
    build_world,
    create_household,
    create_inspector,
    make_field_inspector_headers,
    make_reviewer_headers,
    program_version,
    read_contractor,
    read_income_verification,
    read_inspection,
    read_program,
    read_project,
    record_result,
    report_installation,
    schedule_inspection,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRoleExclusivity:
    def test_no_role_reaches_another_roles_exclusive_operation_not_even_the_administrator(
        self, api
    ):
        """Seven exclusive writes refuse the wrong role, then the right role succeeds.

        PRD §2.1: "A `FieldInspector` records spot and post-installation inspection
        results and nothing else — inspectors never schedule, reserve, or pay."

        PRD §2.1: "A `ProgramAdmin` configures the program and its catalog, decides
        contractor suspension, runs the expiry sweep, disburses payment, and drives
        the logical clock; an administrator may not review projects or record
        inspection results."

        PRD §2.10: "**Role permitted.** `X-User-Role` is present and listed among the
        endpoint's authorised roles → otherwise `ERR_FORBIDDEN_ROLE` (403). This beats
        body validation: a `Contractor` posting a malformed payment body receives 403,
        never 400. Applies to every endpoint."

        Design: Corner/rbac/each_role_is_locked_out_of_the_other_roles_exclusive_operations
        """
        world = build_world(
            api,
            stage="inspection_scheduled",
            catalog=[build_hvac_heat_pump_payload()],
            measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
        )
        program_id = world["program_id"]
        project_id = world["project_id"]
        verification_id = world["income_verification"]["id"]
        inspector_id = world["inspector_id"]
        inspection_id = world["inspection_id"]

        #  Verifying income is ProgramReviewer-exclusive: neither the applicant who
        #  owns the packet nor the administrator who may file one can decide it.
        validate_error(
            api.verify_income_verification(
                verification_id, build_verify_decision_payload(), world["applicant_headers"]
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        validate_error(
            api.verify_income_verification(
                verification_id, build_verify_decision_payload(), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )

        #  Reviewing a project is ProgramReviewer-exclusive; the administrator is not
        #  a superuser here either.
        validate_error(
            api.review_rebate_project(
                project_id, build_project_review_payload(), world["contractor_headers"]
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        validate_error(
            api.review_rebate_project(project_id, build_project_review_payload(), ADMIN_HEADERS),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )

        #  Inspectors never schedule.
        validate_error(
            api.create_inspection(
                build_inspection_payload(
                    project_id,
                    inspector_id,
                    InspectionType.SPOT,
                    scheduled_start="2026-08-22T09:00:00Z",
                    scheduled_end="2026-08-22T11:00:00Z",
                ),
                world["inspector_headers"],
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )

        #  Recording a result is FieldInspector-exclusive, and the sweep is
        #  ProgramAdmin-exclusive: the two privileged roles are disjoint on writes.
        validate_error(
            api.record_inspection_result(
                inspection_id, build_pass_result_payload(), REVIEWER_HEADERS
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        validate_error(
            api.sweep_program(program_id, REVIEWER_HEADERS), ApiErrorId.ERR_FORBIDDEN_ROLE
        )

        #  Nothing the seven refusals aimed at moved.
        packet = read_income_verification(api, world["household_id"], verification_id)
        assert packet["status"] == IncomeVerificationStatus.VERIFIED
        assert packet["verified_by_user_id"] == REVIEWER_ONE
        assert read_project(api, project_id)["status"] == ProjectStatus.INSTALLED
        assert read_inspection(api, inspection_id)["status"] == InspectionStatus.SCHEDULED
        _rows, meta = validate_paginated(
            api.list_inspections(REVIEWER_HEADERS, {"project_id": project_id})
        )
        assert meta["total_count"] == 1

        #  The only difference between the refused result and this one is the role.
        recorded = validate_success(
            api.record_inspection_result(
                inspection_id,
                build_pass_result_payload(),
                make_field_inspector_headers(inspector_id),
            )
        )
        assert recorded["status"] == InspectionStatus.PASSED
        assert recorded["recorded_by_user_id"] == inspector_id


class TestSharedProjectPipeline:
    def test_the_applicant_opens_the_project_the_contractor_submits_and_declares_stacking(
        self, api
    ):
        """A shared write does not unlock the reviewer-only collection read.

        PRD §2.1: "An `Applicant` is the homeowner: they own the household record,
        file income documentation, open and submit projects, declare stacked benefits,
        and request reservation extensions."

        PRD §2.1: "A `Contractor` is the enrolled installer: they perform
        pre-installation assessments, may open and submit projects on a household's
        behalf, report installation, and open remediation cycles."

        PRD §3.9: "The state incentive going in is the project's
        `final_total_incentive_cents` when that is not null, and its
        `provisional_total_incentive_cents` otherwise. This value is stored as the
        declaration's `computed_state_incentive_before_cents`."

        PRD §3.9: "If the total benefit exceeds the limit, the allowed state incentive
        becomes the state incentive less the excess, clamped up to 0; otherwise the
        allowed state incentive is the state incentive unchanged. The result is stored
        as `allowed_state_incentive_cents`."

        Design: Corner/rbac/project_create_and_submit_are_shared_between_applicant_and_contractor
        """
        world = build_world(
            api, stage="assessment", catalog=[build_hvac_heat_pump_payload()]
        )
        household_id = world["household_id"]
        contractor_id = world["contractor_id"]
        applicant_headers = world["applicant_headers"]
        contractor_headers = world["contractor_headers"]

        #  The homeowner opens the project.
        project = validate_success(
            api.create_rebate_project(
                build_project_payload(
                    household_id,
                    world["assessment_id"],
                    contractor_id,
                    world["income_verification"]["id"],
                    [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
                    estimated_project_cost_cents=1000000,
                ),
                applicant_headers,
            ),
            expected_status=201,
        )
        assert project["household_id"] == household_id
        assert project["contractor_id"] == contractor_id
        assert project["provisional_total_incentive_cents"] == 800000
        project_id = project["id"]

        #  The installer submits what the homeowner created.
        submitted = validate_success(api.submit_rebate_project(project_id, contractor_headers))
        assert submitted["status"] == ProjectStatus.SUBMITTED

        #  Either party may declare stacked benefits. Basis 1000000, S0 800000,
        #  U 150000, F 15000: the total 965000 stays inside the 1000000 limit, so the
        #  state incentive survives whole and nothing residual is left over.
        declaration = validate_success(
            api.create_stacking_declaration(
                project_id,
                build_stacking_payload(150000, utility_program_name="Xcel Heat Pump Rebate"),
                contractor_headers,
            ),
            expected_status=201,
        )
        assert declaration["status"] == StackingDeclarationStatus.ACTIVE
        assert declaration["computed_state_incentive_before_cents"] == 800000
        assert declaration["combined_benefit_limit_cents"] == 1000000
        assert declaration["allowed_state_incentive_cents"] == 800000
        assert declaration["allowed_federal_credit_cents"] == 15000
        assert declaration["residual_overage_cents"] == 0

        #  Both entity-backed parties read exactly the same project.
        applicant_view = validate_success(api.get_rebate_project(project_id, applicant_headers))
        contractor_view = validate_success(api.get_rebate_project(project_id, contractor_headers))
        assert applicant_view == contractor_view
        assert applicant_view["stacking_adjusted_state_incentive_cents"] == 800000

        #  The collection read stays reviewer/admin-only for the same filter.
        listing_filter = {"household_id": household_id}
        validate_error(
            api.list_rebate_projects(applicant_headers, listing_filter),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        validate_error(
            api.list_rebate_projects(contractor_headers, listing_filter),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        rows, meta = validate_paginated(
            api.list_rebate_projects(REVIEWER_HEADERS, listing_filter)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == project_id


class TestSegregationOfDuties:
    def test_the_reviewer_who_decided_the_project_may_neither_reserve_nor_pay_it(self, api):
        """Segregation of duties is per user and per project, and two hats do not launder it.

        PRD §2.9: "Four operations enforce that the user recording a decision is not
        the user who produced the artefact being decided. In all four the rejection is
        `ERR_SEGREGATION_OF_DUTIES` (403):"

        PRD §2.9: "Verifying an income verification: the acting `X-User-ID` may not
        equal the `submitted_by_user_id` recorded when the packet was filed."

        PRD §2.9: "Creating a reservation for a project: the acting `X-User-ID` may not
        equal the project's `reviewed_by_user_id`. The reviewer who returned the review
        decision may not also encumber budget against it."

        PRD §2.9: "Disbursing payment for a project: the acting `X-User-ID` may not
        equal the project's `reviewed_by_user_id` either. The person who pays may not
        be the person who reviewed."

        PRD §3.5: "The project is created in `DRAFT` with `submission_count` at 0,
        `remediation_count` at 0, `conditional_pass_flag` false, `disbursed_amount_cents`
        at 0, `provisional_total_incentive_cents` at 0, `final_total_incentive_cents`
        and `stacking_adjusted_state_incentive_cents` null, `actual_project_cost_cents`
        null, and `install_start_date`, `install_end_date`, and `installed_panel_amps`
        all null."

        Design: Corner/rbac/same_user_cannot_review_then_reserve_or_pay_the_same_project
        """
        world = build_world(
            api, stage="approved", catalog=[build_hvac_heat_pump_payload()]
        )
        program_id = world["program_id"]
        project_id = world["project_id"]
        contractor_id = world["contractor_id"]
        assert world["project"]["reviewed_by_user_id"] == REVIEWER_ONE

        #  A second household whose packet was filed by the operator "admin-1".
        other = create_household(
            api,
            program_id,
            applicant_name="Sol Okonkwo",
            email="sol@example.com",
            service_address_line1="332 Ledger St",
        )
        other_packet = validate_success(
            api.create_income_verification(
                other["id"], build_income_verification_payload(), ADMIN_HEADERS
            ),
            expected_status=201,
        )

        observed_version = program_version(api, program_id)

        #  The reviewer who approved this project cannot encumber budget for it.
        validate_error(
            api.create_reservation(
                project_id, build_reservation_payload(observed_version), REVIEWER_HEADERS
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        assert read_program(api, program_id)["version"] == observed_version

        #  Wearing the reviewer hat does not let "admin-1" decide its own packet.
        validate_error(
            api.verify_income_verification(
                other_packet["id"], build_verify_decision_payload(), make_reviewer_headers(ADMIN_ONE)
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        assert (
            read_income_verification(api, other["id"], other_packet["id"])["status"]
            == IncomeVerificationStatus.SUBMITTED
        )

        #  The only difference here is the acting user id, and the stale-looking token
        #  is still current precisely because the refusal wrote nothing.
        reservation = validate_success(
            api.create_reservation(
                project_id, build_reservation_payload(observed_version), REVIEWER_TWO_HEADERS
            ),
            expected_status=201,
        )
        assert reservation["reserved_amount_cents"] == 800000
        assert reservation["status"] == ReservationStatus.RESERVED

        report_installation(
            api,
            project_id,
            contractor_id,
            [build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
            actual_project_cost_cents=700000,
        )

        #  Scheduling is not one of the four incompatible steps, so reviewer-1 may do it.
        inspector = create_inspector(api, program_id, inspector_name="Ines Ferrer")
        inspection = schedule_inspection(
            api, project_id, inspector["id"], headers=REVIEWER_HEADERS
        )
        assert inspection["scheduled_by_user_id"] == REVIEWER_ONE
        record_result(api, inspection["id"], inspector["id"], build_pass_result_payload())
        assert read_project(api, project_id)["status"] == ProjectStatus.VERIFIED

        #  The review conflict bars payment too.
        validate_error(
            api.disburse_payment(project_id, REVIEWER_HEADERS, {"payment_reference": "SOD-1"}),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        blocked = read_project(api, project_id)
        assert blocked["status"] == ProjectStatus.VERIFIED
        assert blocked["disbursed_amount_cents"] == 0

        #  Reserving and paying the same project is no conflict at all.
        paid = validate_success(
            api.disburse_payment(project_id, REVIEWER_TWO_HEADERS, {"payment_reference": "SOD-2"})
        )
        assert paid["status"] == ProjectStatus.PAID
        assert paid["disbursed_amount_cents"] == 700000
        assert paid["reviewed_by_user_id"] == REVIEWER_ONE
        assert REVIEWER_TWO != REVIEWER_ONE


class TestInspectorIdentityBinding:
    def test_the_wrong_inspector_and_the_wrong_role_earn_two_different_403s(self, api):
        """Right role plus wrong identity is distinguishable from wrong role.

        PRD §2.1: "A request from an entity-backed role that addresses a resource
        belonging to a different household, contractor, or inspector is rejected with
        `ERR_NOT_RESOURCE_OWNER` (403)."

        PRD §3.8: "Recording the outcome is exclusively a `FieldInspector` action,
        supplying a `result` together with optional `deficiency_count`,
        `deficiency_severity_max` (an integer from 0 for none through 5 for life
        safety), `rejected_measure_codes`, and `notes`."

        PRD §3.8: "Every branch requires the inspection to still be in `SCHEDULED` — a
        second attempt is refused with `ERR_INSPECTION_ALREADY_RECORDED` — and requires
        the acting inspector's identifier to equal the inspection's `inspector_id`."

        PRD §3.3: "This is the measure persisted on `quality_score_rolling` every time
        an inspection result is recorded, alongside a refreshed
        `completed_inspection_count` counting the candidate set."

        Design: Corner/rbac/inspection_results_are_bound_to_the_assigned_inspector
        """
        world = build_world(
            api,
            stage="installed",
            catalog=[build_hvac_heat_pump_payload()],
            measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
        )
        program_id = world["program_id"]
        project_id = world["project_id"]
        assigned = create_inspector(
            api, program_id, inspector_name="Assigned Inspector", certification_id="INS-101"
        )
        idle = create_inspector(
            api, program_id, inspector_name="Idle Inspector", certification_id="INS-102"
        )
        assigned_headers = make_field_inspector_headers(assigned["id"])
        idle_headers = make_field_inspector_headers(idle["id"])
        inspection = schedule_inspection(api, project_id, assigned["id"])

        #  Right role, wrong inspector.
        validate_error(
            api.record_inspection_result(
                inspection["id"], build_pass_result_payload(), idle_headers
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        )

        #  Wrong role entirely — a different code, one rung earlier.
        validate_error(
            api.record_inspection_result(
                inspection["id"], build_pass_result_payload(), world["contractor_headers"]
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )

        #  Reading the inspection is not identity-bound; only recording the result is.
        seen = validate_success(api.get_inspection(inspection["id"], idle_headers))
        assert seen["status"] == InspectionStatus.SCHEDULED
        assert seen["recorded_by_user_id"] is None
        assert seen["result_recorded_at"] is None
        assert validate_success(api.get_inspector(idle["id"], idle_headers))["id"] == idle["id"]

        #  The assigned inspector's result lands, and only that one counts.
        recorded = validate_success(
            api.record_inspection_result(
                inspection["id"], build_pass_result_payload(), assigned_headers
            )
        )
        assert recorded["status"] == InspectionStatus.PASSED
        assert recorded["recorded_by_user_id"] == assigned["id"]
        assert recorded["result_recorded_at"] is not None

        contractor = read_contractor(api, world["contractor_id"])
        assert contractor["quality_score_rolling"] == 100
        assert contractor["completed_inspection_count"] == 1
