"""Declared transitions, initial states, terminal lockdown and guarded replays."""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    AssessmentStatus,
    ContractorStatus,
    IncomeTier,
    IncomeVerificationStatus,
    InspectionStatus,
    InstallStatus,
    LineRejectionReason,
    MEASURE_HP_HVAC,
    MEASURE_HPWH,
    ProgramStatus,
    ProjectStatus,
    REVIEWER_HEADERS,
    REVIEWER_TWO_HEADERS,
    ReservationStatus,
    SuspensionReason,
    VerificationStatus,
    add_catalog,
    assert_fields,
    assert_household_cap,
    assert_program_buckets,
    build_assessment_measure,
    build_contractor_payload,
    build_fail_result_payload,
    build_hvac_heat_pump_payload,
    build_income_verification_payload,
    build_pass_result_payload,
    build_project_measure,
    build_reject_income_decision_payload,
    build_verify_decision_payload,
    build_water_heater_payload,
    create_approved_assessment,
    create_assessment,
    create_draft_program,
    create_enrolled_contractor,
    create_household,
    create_open_program,
    create_project,
    create_verified_household,
    decide_assessment,
    file_income_verification,
    find_measure_line,
    household_version,
    make_applicant_headers,
    make_contractor_headers,
    open_program,
    read_contractor,
    read_eligible_measures,
    read_household,
    read_program,
    read_project,
    read_project_measures,
    read_quality_review,
    read_reservation,
    record_result,
    set_program_status,
    submit_project,
    validate_error,
    validate_paginated,
    validate_success,
    verify_income_verification,
)


class TestProgramLifecycle:
    def test_program_walks_draft_open_suspended_open_bumping_the_version_each_time(self, api):
        """The program machine is cyclic and each declared hop costs one version.

        PRD §3.1: "`SUSPENDED → OPEN` returns a suspended program to service,
        which makes the program machine cyclic. `CLOSED` is terminal and may be
        reached from either `OPEN` or `SUSPENDED`, but only when no reservation of
        that program is still in status `RESERVED`. Every one of these five
        transitions increments the program's version by one."

        Design: Corner/state_machines/program_status_walks_draft_open_suspended_open
        """
        program = create_draft_program(api, name="HEEHRA 2026 Walk")

        opened = validate_success(
            api.set_program_status(program["id"], {"new_status": "OPEN"}, ADMIN_HEADERS)
        )
        assert_fields(opened, "Program", status=ProgramStatus.OPEN, version=2)

        suspended = validate_success(
            api.set_program_status(
                program["id"],
                {"new_status": "SUSPENDED", "status_note": "Quarterly appropriation review"},
                ADMIN_HEADERS,
            )
        )
        assert_fields(suspended, "Program", status=ProgramStatus.SUSPENDED, version=3)

        reopened = validate_success(
            api.set_program_status(program["id"], {"new_status": "OPEN"}, ADMIN_HEADERS)
        )
        assert_fields(reopened, "Program", status=ProgramStatus.OPEN, version=4)

        assert_program_buckets(
            reopened, available=50000000, reserved=0, committed=0, clawed_back=0
        )

        _open_rows, open_meta = validate_paginated(
            api.list_programs(ADMIN_HEADERS, {"status": ProgramStatus.OPEN})
        )
        assert open_meta["total_count"] == 1, "The reopened program should be listed as OPEN"
        _suspended_rows, suspended_meta = validate_paginated(
            api.list_programs(ADMIN_HEADERS, {"status": ProgramStatus.SUSPENDED})
        )
        assert suspended_meta["total_count"] == 0, (
            "No program should still be listed as SUSPENDED after the reopen"
        )

    def test_closed_program_refuses_every_further_status_request(self, api):
        """CLOSED is terminal, and a refused transition costs no version.

        PRD §3.1: "A requested status that is not declared for the program's
        current state is refused with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/closed_program_refuses_reopen_from_terminal_state
        """
        program = create_open_program(api, name="HEEHRA 2026 Closed")
        closed = set_program_status(
            api, program["id"], ProgramStatus.CLOSED, status_note="Program year closed out"
        )
        assert_fields(closed, "Program", status=ProgramStatus.CLOSED, version=3)

        for requested in (ProgramStatus.OPEN, ProgramStatus.SUSPENDED):
            response = api.set_program_status(
                program["id"], {"new_status": requested}, ADMIN_HEADERS
            )
            validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        after = read_program(api, program["id"])
        assert_fields(after, "Program", status=ProgramStatus.CLOSED, version=3)

        _rows, meta = validate_paginated(
            api.list_programs(ADMIN_HEADERS, {"status": ProgramStatus.CLOSED})
        )
        assert meta["total_count"] == 1, "The closed program should be listed as CLOSED"


class TestInitialStates:
    def test_every_state_bearing_record_is_created_in_its_declared_initial_state(self, api):
        """Six records are created down one chain and none of them skips a state.

        PRD §3.5: "The project is created in `DRAFT` with `submission_count` at 0,
        `remediation_count` at 0, `conditional_pass_flag` false,
        `disbursed_amount_cents` at 0, `provisional_total_incentive_cents` at 0,
        `final_total_incentive_cents` and
        `stacking_adjusted_state_incentive_cents` null,
        `actual_project_cost_cents` null, and `install_start_date`,
        `install_end_date`, and `installed_panel_amps` all null."

        Design: Corner/state_machines/newly_created_entities_start_in_declared_initial_states
        """
        program = create_draft_program(api, name="HEEHRA 2026 Initial")
        assert program["status"] == ProgramStatus.DRAFT, (
            "A program is born in DRAFT; the OPEN state below is an explicit transition"
        )
        open_program(api, program["id"])
        add_catalog(api, program["id"], [build_hvac_heat_pump_payload()])

        household = create_household(
            api, program["id"], applicant_name="Iris Bello", email="iris@example.com"
        )
        contractor = create_enrolled_contractor(
            api, program["id"], business_name="Initial State Mechanical", license_number="MC-3001"
        )

        verification = file_income_verification(api, household["id"])
        assert_fields(
            verification,
            "IncomeVerification",
            status=IncomeVerificationStatus.SUBMITTED,
            verified_by_user_id=None,
            assigned_income_tier=None,
            assigned_cap_cents=0,
        )

        undecided = validate_success(
            api.create_contractor(
                build_contractor_payload(
                    program["id"],
                    business_name="Undecided Electric",
                    license_number="MC-3002",
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert_fields(
            undecided,
            "Contractor",
            status=ContractorStatus.PENDING_ENROLLMENT,
            quality_score_rolling=100,
            completed_inspection_count=0,
            suspension_reason=None,
        )

        verify_income_verification(api, verification["id"])

        assessment = create_assessment(api, household["id"], contractor["id"])
        assert_fields(
            assessment,
            "Assessment",
            status=AssessmentStatus.PENDING_REVIEW,
            approved_by_user_id=None,
        )
        decide_assessment(api, assessment["id"])

        project = create_project(
            api,
            household["id"],
            assessment["id"],
            contractor["id"],
            verification["id"],
        )
        assert_fields(
            project,
            "RebateProject",
            status=ProjectStatus.DRAFT,
            submission_count=0,
            remediation_count=0,
            conditional_pass_flag=False,
            disbursed_amount_cents=0,
            final_total_incentive_cents=None,
        )

        lines = read_project_measures(api, project["id"])
        assert len(lines) == 1, f"The project should carry one measure line, got {len(lines)}"
        assert_fields(
            lines[0],
            "ProjectMeasure",
            install_status=InstallStatus.PLANNED,
            verification_status=VerificationStatus.PENDING,
            rejection_reason=None,
            provisional_incentive_cents=800000,
        )


class TestIncomeVerificationGuard:
    def test_a_verified_household_refuses_both_refiling_and_a_second_verification(self, api):
        """The one-verified-packet rule is enforced on the filing door and the deciding door.

        PRD §3.2: "A household may hold at most one `VERIFIED` verification ever;
        filing or verifying a packet for a household that already holds one is
        refused with `ERR_INCOME_TIER_ALREADY_VERIFIED`."

        Design: Corner/state_machines/second_income_verification_after_verified_rejected
        """
        program = create_open_program(api, name="HEEHRA 2026 Verify Once")
        household = create_household(
            api, program["id"], applicant_name="Jonah Vex", email="jonah@example.com"
        )
        applicant_headers = make_applicant_headers(household["id"])

        first = file_income_verification(api, household["id"])
        second = file_income_verification(
            api, household["id"], annual_household_income_cents=4000000
        )
        verify_income_verification(api, first["id"])

        refile = api.create_income_verification(
            household["id"],
            build_income_verification_payload(annual_household_income_cents=4000000),
            applicant_headers,
        )
        validate_error(refile, ApiErrorId.ERR_INCOME_TIER_ALREADY_VERIFIED, 409)

        reverify = api.verify_income_verification(
            second["id"], build_verify_decision_payload(), REVIEWER_HEADERS
        )
        validate_error(reverify, ApiErrorId.ERR_INCOME_TIER_ALREADY_VERIFIED, 409)

        rejected = validate_success(
            api.verify_income_verification(
                second["id"],
                build_reject_income_decision_payload(
                    reviewer_notes="Superseded by the verified filing"
                ),
                REVIEWER_HEADERS,
            )
        )
        assert rejected["status"] == IncomeVerificationStatus.REJECTED, (
            "Rejecting a redundant SUBMITTED filing is a declared transition"
        )

        after = read_household(api, household["id"])
        assert_fields(
            after,
            "Household",
            income_tier=IncomeTier.LOW,
            ami_percent=80.0,
            rebate_cap_cents=1400000,
        )

        _rows, meta = validate_paginated(
            api.list_income_verifications(
                household["id"], REVIEWER_HEADERS, {"status": IncomeVerificationStatus.VERIFIED}
            )
        )
        assert meta["total_count"] == 1, (
            "Exactly one verification may ever stand VERIFIED for a household"
        )


class TestAssessmentSupersession:
    def test_creating_an_assessment_supersedes_the_prior_live_one_from_either_state(self, api):
        """Supersession fires from PENDING_REVIEW and from APPROVED alike.

        PRD §3.4: "The assessment is created in `PENDING_REVIEW`, and creating it
        moves the household's prior live assessment — whether it stood in
        `PENDING_REVIEW` or `APPROVED` — to `SUPERSEDED`, incrementing the
        superseded row's version."

        Design: Corner/state_machines/new_assessment_supersedes_prior_live_assessment
        """
        program = create_open_program(api, name="HEEHRA 2026 Supersede")
        add_catalog(api, program["id"], [build_hvac_heat_pump_payload(), build_water_heater_payload()])
        verified = create_verified_household(
            api, program["id"], applicant_name="Kira Mensah", email="kira@example.com"
        )
        household = verified["household"]
        contractor = create_enrolled_contractor(
            api, program["id"], business_name="Supersede Mechanical", license_number="MC-4001"
        )

        version_two = household_version(api, household["id"])
        first = create_assessment(
            api,
            household["id"],
            contractor["id"],
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
            expected_household_version=version_two,
        )

        version_three = household_version(api, household["id"])
        assert version_three == version_two + 1, (
            "Creating an assessment increments the household version by one"
        )
        second = create_assessment(
            api,
            household["id"],
            contractor["id"],
            [
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HPWH, 1, 400000),
            ],
            expected_household_version=version_three,
        )

        first_after = validate_success(api.get_assessment(first["id"], REVIEWER_HEADERS))
        assert first_after["status"] == AssessmentStatus.SUPERSEDED, (
            "The prior PENDING_REVIEW assessment must be superseded"
        )
        assert_fields(
            second,
            "Assessment",
            status=AssessmentStatus.PENDING_REVIEW,
            qualified_measure_count=2,
            estimated_total_incentive_cents=975000,
        )

        preserved = read_eligible_measures(api, first["id"])
        assert len(preserved) == 1, (
            "Superseding neither deletes nor re-evaluates the old measure set"
        )
        assert preserved[0]["measure_code"] == MEASURE_HP_HVAC
        assert preserved[0]["qualified"] is True

        decide_assessment(api, second["id"])
        version_four = household_version(api, household["id"])
        assert version_four == version_three + 1
        third = create_assessment(
            api,
            household["id"],
            contractor["id"],
            [build_assessment_measure(MEASURE_HPWH, 1, 400000)],
            expected_household_version=version_four,
        )

        second_after = validate_success(api.get_assessment(second["id"], REVIEWER_HEADERS))
        assert second_after["status"] == AssessmentStatus.SUPERSEDED, (
            "An APPROVED assessment is superseded by the next create as well"
        )
        assert_fields(
            third,
            "Assessment",
            status=AssessmentStatus.PENDING_REVIEW,
            qualified_measure_count=1,
        )

        rows, meta = validate_paginated(
            api.list_assessments(REVIEWER_HEADERS, {"household_id": household["id"]})
        )
        assert meta["total_count"] == 3, f"All three assessments should be listed, got {rows}"
        live = [row for row in rows if row["status"] != AssessmentStatus.SUPERSEDED]
        assert len(live) == 1, f"Exactly one assessment may stand live, got {len(live)}"


class TestProjectStateGate:
    def test_review_and_submit_are_refused_from_states_that_do_not_declare_them(self, api):
        """A DRAFT review, a double submit and a submit from REJECTED all fail the state gate.

        PRD §3.5: "Submitting a `DRAFT` project moves it `DRAFT → SUBMITTED`,
        permitted only when at least one project measure line exists and when the
        acting applicant's identifier equals the project's `household_id` or the
        acting contractor's identifier equals its `contractor_id`; the transition
        increments `submission_count` by one."

        Design: Corner/state_machines/review_and_resubmit_from_wrong_state_rejected
        """
        program = create_open_program(api, name="HEEHRA 2026 Wrong State")
        add_catalog(api, program["id"], [build_hvac_heat_pump_payload()])
        verified = create_verified_household(
            api, program["id"], applicant_name="Liam Osei", email="liam@example.com"
        )
        household = verified["household"]
        contractor = create_enrolled_contractor(
            api, program["id"], business_name="Wrong State Mechanical", license_number="MC-5001"
        )
        assessment = create_approved_assessment(api, household["id"], contractor["id"])
        project = create_project(
            api,
            household["id"],
            assessment["id"],
            contractor["id"],
            verified["income_verification"]["id"],
            [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
        )
        contractor_headers = make_contractor_headers(contractor["id"])

        review_draft = api.review_rebate_project(
            project["id"], {"decision": "APPROVE"}, REVIEWER_HEADERS
        )
        validate_error(review_draft, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        still_draft = read_project(api, project["id"])
        assert_fields(
            still_draft, "RebateProject", status=ProjectStatus.DRAFT, submission_count=0
        )

        submitted = submit_project(api, project["id"], contractor["id"])
        assert_fields(
            submitted, "RebateProject", status=ProjectStatus.SUBMITTED, submission_count=1
        )

        double_submit = api.submit_rebate_project(project["id"], contractor_headers)
        validate_error(double_submit, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        assert read_project(api, project["id"])["submission_count"] == 1, (
            "A refused submit must not increment submission_count"
        )

        rejected = validate_success(
            api.review_rebate_project(
                project["id"],
                {"decision": "REJECT", "review_notes": "Ineligible dwelling type"},
                REVIEWER_HEADERS,
            )
        )
        assert rejected["status"] == ProjectStatus.REJECTED
        line = find_measure_line(read_project_measures(api, project["id"]), MEASURE_HP_HVAC)
        assert line["install_status"] == InstallStatus.VOID, (
            "Rejection at review sets every measure line to VOID"
        )

        terminal_submit = api.submit_rebate_project(project["id"], contractor_headers)
        validate_error(terminal_submit, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        final = read_project(api, project["id"])
        assert final["submission_count"] == 1, (
            "The terminal REJECTED state declares no submit transition"
        )

        assert_program_buckets(read_program(api, program["id"]), available=50000000, reserved=0)


class TestInspectionResultGuard:
    def test_recording_a_second_inspection_result_is_refused_rather_than_replayed(
        self, api, scheduled_inspection_world
    ):
        """The result endpoint is guarded, so neither a replay nor a flip is accepted.

        PRD §3.8: "Every branch requires the inspection to still be in
        `SCHEDULED` — a second attempt is refused with
        `ERR_INSPECTION_ALREADY_RECORDED` — and requires the acting inspector's
        identifier to equal the inspection's `inspector_id`."

        Design: Corner/state_machines/inspection_result_recorded_twice_rejected
        """
        world = scheduled_inspection_world
        inspector_headers = world["inspector_headers"]

        first = record_result(
            api, world["inspection_id"], world["inspector_id"], build_pass_result_payload()
        )
        assert_fields(first, "Inspection", status=InspectionStatus.PASSED)
        assert first["result_recorded_at"] is not None
        assert first["recorded_by_user_id"] == world["inspector_id"]

        project = read_project(api, world["project_id"])
        assert_fields(
            project,
            "RebateProject",
            status=ProjectStatus.VERIFIED,
            final_total_incentive_cents=700000,
        )
        line = find_measure_line(
            read_project_measures(api, world["project_id"]), MEASURE_HP_HVAC
        )
        assert line["verification_status"] == VerificationStatus.VERIFIED

        replay = api.record_inspection_result(
            world["inspection_id"], build_pass_result_payload(), inspector_headers
        )
        validate_error(replay, ApiErrorId.ERR_INSPECTION_ALREADY_RECORDED, 409)

        flip = api.record_inspection_result(
            world["inspection_id"],
            build_fail_result_payload(deficiency_count=4, deficiency_severity_max=5),
            inspector_headers,
        )
        validate_error(flip, ApiErrorId.ERR_INSPECTION_ALREADY_RECORDED, 409)

        assert read_project(api, world["project_id"])["status"] == ProjectStatus.VERIFIED, (
            "A refused replay must not flip the project to INSPECTION_FAILED"
        )
        contractor = read_contractor(api, world["contractor_id"])
        assert_fields(
            contractor, "Contractor", completed_inspection_count=1, quality_score_rolling=100
        )
        assert (
            read_reservation(api, world["reservation_id"])["status"]
            == ReservationStatus.RESERVED
        )
        assert_program_buckets(read_program(api, world["program_id"]), reserved=800000)


class TestPaymentLedgerSync:
    def test_payment_reconciles_the_household_encumbrance_down_to_the_disbursed_amount(
        self, api, verified_project_world
    ):
        """Under-running the reservation credits the difference back to the household cap.

        PRD §3.9: "On the household side, `encumbered_cents` is reconciled to the
        disbursed amount and `lifetime_cap_remaining_cents` is credited by the
        release difference, with the household's version incremented."

        Design: Corner/state_machines/payment_reconciles_household_encumbrance_downward
        """
        world = verified_project_world

        before = read_household(api, world["household_id"])
        assert_household_cap(before, remaining=600000, encumbered=800000, cap=1400000)

        paid = validate_success(
            api.disburse_payment(
                world["project_id"], REVIEWER_TWO_HEADERS, {"payment_reference": "ACH-7001"}
            )
        )
        assert_fields(
            paid, "RebateProject", status=ProjectStatus.PAID, disbursed_amount_cents=700000
        )

        household = read_household(api, world["household_id"])
        assert_household_cap(household, remaining=700000, encumbered=700000, cap=1400000)
        assert household["version"] == 5, (
            "One write each for intake, income verification, assessment create, reservation "
            f"and payment reconciliation, so version 5, got {household['version']}"
        )

        reservation = read_reservation(api, world["reservation_id"])
        assert_fields(
            reservation,
            "Reservation",
            status=ReservationStatus.COMMITTED,
            initial_reserved_amount_cents=800000,
            reserved_amount_cents=700000,
        )
        assert reservation["committed_at"] is not None

        assert_program_buckets(
            read_program(api, world["program_id"]),
            available=49300000,
            reserved=0,
            committed=700000,
        )


class TestQualityCascade:
    def test_a_failed_post_install_inspection_suspends_the_installer_on_quality_score(
        self, api, scheduled_inspection_world
    ):
        """One failure drops the rolling score to 0, which is below the threshold.

        PRD §3.3: "When it lands strictly below the program's
        `quality_suspension_threshold`, the contractor is automatically taken
        `ENROLLED_ACTIVE → SUSPENDED` with `suspension_reason` set to
        `QUALITY_SCORE`, dragging the contractor-hold cascade behind it."

        Design: Corner/state_machines/failed_post_install_inspection_suspends_contractor_on_quality_score
        """
        world = scheduled_inspection_world

        failed = record_result(
            api,
            world["inspection_id"],
            world["inspector_id"],
            build_fail_result_payload(
                [MEASURE_HP_HVAC],
                deficiency_count=2,
                deficiency_severity_max=4,
                notes="Line-set brazing and condensate not to standard",
            ),
        )
        assert failed["status"] == InspectionStatus.FAILED

        project = read_project(api, world["project_id"])
        assert project["status"] == ProjectStatus.INSPECTION_FAILED, (
            "remediation_count 0 is still below the limit of 1, so this is not FAILED_FINAL"
        )
        line = find_measure_line(
            read_project_measures(api, world["project_id"]), MEASURE_HP_HVAC
        )
        assert_fields(
            line,
            "ProjectMeasure",
            verification_status=VerificationStatus.REJECTED,
            rejection_reason=LineRejectionReason.INSPECTION_DEFICIENCY,
        )

        contractor = read_contractor(api, world["contractor_id"])
        assert_fields(
            contractor,
            "Contractor",
            quality_score_rolling=0,
            completed_inspection_count=1,
            status=ContractorStatus.SUSPENDED,
            suspension_reason=SuspensionReason.QUALITY_SCORE,
        )

        review = read_quality_review(api, world["contractor_id"])
        assert_fields(
            review,
            "QualityReview",
            rolling_window_score=0,
            severity_weighted_score=0,
            rolling_window_inspection_count=1,
            weighted_inspection_count=1,
            suspension_threshold=70,
            recertification_threshold=75,
            recertification_eligible=False,
        )

        reservation = read_reservation(api, world["reservation_id"])
        assert_fields(
            reservation,
            "Reservation",
            status=ReservationStatus.RESERVED,
            reserved_amount_cents=800000,
        )
        assert_household_cap(
            read_household(api, world["household_id"]), remaining=600000, encumbered=800000
        )
