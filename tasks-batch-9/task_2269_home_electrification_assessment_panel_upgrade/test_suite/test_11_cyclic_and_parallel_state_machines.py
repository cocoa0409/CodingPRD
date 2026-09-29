"""A revision cycle carrying a counter, two parallel line dimensions, and a terminal sibling."""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    ContractorStatus,
    DEFAULT_GROUP_CAP_CENTS,
    DEFAULT_LOW_TIER_CAP_CENTS,
    DEFAULT_QUALITY_SUSPENSION_THRESHOLD,
    EnrollmentDecision,
    InspectionStatus,
    InspectionType,
    InstallStatus,
    LineRejectionReason,
    MEASURE_HPWH,
    MEASURE_HP_DUCT,
    MEASURE_HP_HVAC,
    ProjectReviewDecision,
    ProjectStatus,
    SuspensionAction,
    SuspensionReason,
    VerificationStatus,
    assert_household_cap,
    assert_measure_codes_in_order,
    assert_quote_line,
    build_assessment_measure,
    build_duct_payload,
    build_fail_result_payload,
    build_hvac_heat_pump_payload,
    build_measure_result,
    build_pass_result_payload,
    build_project_measure,
    build_suspension_payload,
    build_water_heater_payload,
    build_world,
    create_contractor,
    create_inspector,
    create_project,
    decide_enrollment,
    find_measure_line,
    open_remediation,
    read_contractor,
    read_household,
    read_project,
    read_project_measures,
    read_quote,
    record_result,
    reinstate_contractor,
    report_installation,
    reserve_project,
    review_project,
    schedule_inspection,
    submit_project,
    suspend_contractor,
    validate_error,
    validate_success,
)


class TestIncompleteResubmissionLoop:
    def test_the_loop_returns_to_submitted_with_a_replaced_measure_set_worth_600000(self, api):
        """One project passes through SUBMITTED twice for two different amounts.

        PRD §3.6: "Returning it moves the project `SUBMITTED → INCOMPLETE` and requires
        an `incomplete_reason`, which is stored on the project and returned to the
        applicant."

        PRD §3.5: "Resubmitting a project that was returned incomplete moves it
        `INCOMPLETE → SUBMITTED` under the same ownership rule, increments
        `submission_count`, clears the stored `incomplete_reason`, and re-runs the
        provisional allocation over every line against the household's *current*
        `lifetime_cap_remaining_cents`."

        PRD §3.5: "When `measures` is supplied, the line set is replaced and the pinned
        rates are re-pinned from the catalog as it stands at that moment."

        PRD §3.5: "If that sum is **strictly greater** than the program's
        `group_cap_cents` — a sum exactly equal to the cap does not prorate — then every
        member except the last in that order is reduced to its amount multiplied by the
        group cap divided by the sum, floored to whole cents, and the last member
        receives the group cap minus the sum of those floored members."

        PRD §2.10: "**State gate.** The source entity is in a state from which the
        requested transition is declared, and the enclosing program is `OPEN` where the
        transition requires it."

        Design: Difficulty/non_linear_state_machine/rebate_project_incomplete_resubmission_loop_repins_measure_set
        """
        world = build_world(
            api,
            stage="submitted",
            catalog=[build_hvac_heat_pump_payload(), build_duct_payload()],
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HP_DUCT, 1, 300000),
            ],
        )
        project_id = world["project_id"]
        contractor_headers = world["contractor_headers"]

        #  First pass through SUBMITTED: 800000 + 250000 is strictly over the 800000
        #  HVAC_GROUP cap, so the pair prorates to 609523 and the duct line absorbs the
        #  190477 residual.
        first = world["project"]
        assert first["status"] == ProjectStatus.SUBMITTED
        assert first["submission_count"] == 1
        assert first["provisional_total_incentive_cents"] == DEFAULT_GROUP_CAP_CENTS
        assert [
            line["provisional_incentive_cents"] for line in read_project_measures(api, project_id)
        ] == [609523, 190477]

        returned = review_project(
            api,
            project_id,
            ProjectReviewDecision.RETURN_INCOMPLETE,
            incomplete_reason="Duct scope not documented",
        )
        assert returned["status"] == ProjectStatus.INCOMPLETE
        assert returned["incomplete_reason"] == "Duct scope not documented"
        assert returned["submission_count"] == 1

        #  Second pass into the same state, with a smaller set: raw 800000, pinned cap
        #  800000, cost share floor(600000 * 1.00) = 600000, and one line in the group so
        #  nothing prorates.
        resubmitted = validate_success(
            api.submit_rebate_project(
                project_id,
                contractor_headers,
                {
                    "measures": [build_project_measure(MEASURE_HP_HVAC, 1, 600000)],
                    "estimated_project_cost_cents": 600000,
                },
            )
        )
        assert resubmitted["status"] == ProjectStatus.SUBMITTED
        assert resubmitted["submission_count"] == 2
        assert resubmitted["incomplete_reason"] is None
        assert resubmitted["estimated_project_cost_cents"] == 600000
        assert resubmitted["provisional_total_incentive_cents"] == 600000

        #  The duct line went away with the replaced set, and the survivor carries
        #  freshly pinned rates.
        replaced = read_project_measures(api, project_id)
        assert_measure_codes_in_order(replaced, [MEASURE_HP_HVAC])
        assert replaced[0]["estimated_cost_cents"] == 600000
        assert replaced[0]["provisional_incentive_cents"] == 600000
        assert replaced[0]["pinned_unit_incentive_cents"] == 800000
        assert replaced[0]["pinned_measure_cap_cents"] == 800000
        assert replaced[0]["pinned_max_quantity"] == 1
        assert replaced[0]["install_status"] == InstallStatus.PLANNED
        assert replaced[0]["verification_status"] == VerificationStatus.PENDING

        assert review_project(api, project_id)["status"] == ProjectStatus.APPROVED

        #  The loop is bounded on the exit side: no submit edge leaves APPROVED.
        validate_error(
            api.submit_rebate_project(project_id, contractor_headers),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )
        refused = read_project(api, project_id)
        assert refused["status"] == ProjectStatus.APPROVED
        assert refused["submission_count"] == 2

    def test_a_resubmission_without_measures_reallocates_against_the_cap_left_today(self, api):
        """The same lines are worth less on the way back because a sibling took the cap.

        PRD §3.5: "Resubmitting a project that was returned incomplete moves it
        `INCOMPLETE → SUBMITTED` under the same ownership rule, increments
        `submission_count`, clears the stored `incomplete_reason`, and re-runs the
        provisional allocation over every line against the household's *current*
        `lifetime_cap_remaining_cents`."

        PRD §3.5: "*Stage 3* applies the household lifetime cap, and only after Stage 2
        has settled. The available ceiling is the household's
        `lifetime_cap_remaining_cents` plus whatever this project has already encumbered
        for itself — that is, plus this project's own reservation's
        `reserved_amount_cents` when a reservation in status `RESERVED` exists, and plus
        0 when none does."

        PRD §3.5: "The members here are **all** participating lines of the project, again
        ordered by `pinned_sort_order` ascending then `created_at` ascending, and their
        post-Stage-2 amounts are summed. If that sum exceeds the ceiling, every member
        except the last is reduced to its amount multiplied by the ceiling divided by the
        sum, floored, and the last member receives the ceiling minus the sum of the
        floored members."

        PRD §3.5: "Because both cap stages are invisible in the stored totals alone, a
        computed read replays the whole waterfall over the project's current lines and
        exposes each stage without changing any state."

        Design: Difficulty/non_linear_state_machine/rebate_project_incomplete_resubmission_loop_repins_measure_set
        """
        world = build_world(
            api,
            stage="submitted",
            catalog=[build_hvac_heat_pump_payload(), build_duct_payload()],
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HP_DUCT, 1, 300000),
            ],
        )
        project_id = world["project_id"]
        household_id = world["household_id"]
        contractor_id = world["contractor_id"]

        returned = review_project(
            api,
            project_id,
            ProjectReviewDecision.RETURN_INCOMPLETE,
            incomplete_reason="Panel photographs missing",
        )
        assert returned["status"] == ProjectStatus.INCOMPLETE
        assert returned["provisional_total_incentive_cents"] == DEFAULT_GROUP_CAP_CENTS

        #  While this project sits in INCOMPLETE a sibling project of the same household
        #  encumbers 800000 of the 1400000 lifetime cap.
        sibling = create_project(
            api,
            household_id,
            world["assessment_id"],
            contractor_id,
            world["income_verification"]["id"],
            [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
            estimated_project_cost_cents=1000000,
        )
        assert sibling["provisional_total_incentive_cents"] == 800000
        submit_project(api, sibling["id"], contractor_id)
        review_project(api, sibling["id"])
        reserve_project(api, sibling["id"], world["program_id"])
        assert_household_cap(
            read_household(api, household_id),
            remaining=600000,
            encumbered=800000,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

        #  The resubmission keeps both lines and both pinned rates, but Stage 3 now sees
        #  a 600000 ceiling and no reservation of its own: 609523 becomes
        #  floor(609523 * 600000 / 800000) = 457142 and the duct line takes the residual.
        resubmitted = submit_project(api, project_id, contractor_id)
        assert resubmitted["status"] == ProjectStatus.SUBMITTED
        assert resubmitted["submission_count"] == 2
        assert resubmitted["incomplete_reason"] is None
        assert resubmitted["provisional_total_incentive_cents"] == 600000

        lines = read_project_measures(api, project_id)
        assert_measure_codes_in_order(lines, [MEASURE_HP_HVAC, MEASURE_HP_DUCT])
        assert [line["provisional_incentive_cents"] for line in lines] == [457142, 142858]
        assert [line["pinned_unit_incentive_cents"] for line in lines] == [800000, 250000]
        assert [line["estimated_cost_cents"] for line in lines] == [1000000, 300000]

        #  The replay shows both stages biting in order.
        quote = read_quote(api, project_id)
        assert_quote_line(quote, MEASURE_HP_HVAC, 800000, 1000000, 800000, 457142)
        assert_quote_line(quote, MEASURE_HP_DUCT, 250000, 300000, 250000, 142858)
        assert quote["group_capped_total_cents"] == DEFAULT_GROUP_CAP_CENTS
        assert quote["household_cap_limit_cents"] == 600000
        assert quote["total_incentive_cents"] == 600000
        assert quote["group_cap_applied"] is True
        assert quote["household_cap_applied"] is True
        assert quote["residual_cents_assigned_to_measure_code"] == MEASURE_HP_DUCT


class TestParallelInstallAndVerificationDimensions:
    def test_one_failure_splits_two_sibling_lines_and_remediation_reopens_only_one(self, api):
        """The rejected line keeps INSTALLED while its verification loops back to PENDING.

        PRD §3.7: "A line's `install_status` evolves independently of its
        `verification_status`, so a line can sit at `INSTALLED` while still `PENDING`
        verification — the two dimensions live on the same row but never gate each
        other."

        PRD §3.8: "First, every measure line named in `rejected_measure_codes` moves
        `verification_status` from `PENDING` to `REJECTED` with `rejection_reason` set to
        `INSPECTION_DEFICIENCY` and its `final_incentive_cents` set to 0."

        PRD §3.8: "Third — and caused by the second hop — the project's
        `final_total_incentive_cents` is recomputed by the final allocation over only the
        lines still eligible for verification, so the project total drops by whatever the
        rejected lines had been allocated."

        PRD §3.8: "The cycle increments `remediation_count` by one and resets every
        measure line whose `verification_status` is `REJECTED` back to `PENDING`,
        clearing each line's `rejection_reason` and incrementing each line's version."

        PRD §3.3: "When it lands strictly below the program's
        `quality_suspension_threshold`, the contractor is automatically taken
        `ENROLLED_ACTIVE → SUSPENDED` with `suspension_reason` set to `QUALITY_SCORE`,
        dragging the contractor-hold cascade behind it."

        Design: Difficulty/non_linear_state_machine/project_measure_parallel_install_and_verification_dimensions
        """
        world = build_world(
            api,
            stage="inspection_scheduled",
            program_overrides={"quality_suspension_threshold": 0},
            catalog=[build_hvac_heat_pump_payload(), build_water_heater_payload()],
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HPWH, 1, 300000),
            ],
            measure_results=[
                build_measure_result(MEASURE_HP_HVAC, 1, 700000),
                build_measure_result(MEASURE_HPWH, 1, 150000),
            ],
            installation_overrides={"actual_project_cost_cents": 850000},
        )
        project_id = world["project_id"]
        contractor_id = world["contractor_id"]

        #  800000 in HVAC_GROUP plus 175000 in WATER_GROUP: neither group is over its cap
        #  and 975000 stays under the 1400000 lifetime ceiling, so 975000 is reserved.
        assert world["reservation"]["reserved_amount_cents"] == 975000
        installed = read_project(api, project_id)
        assert installed["status"] == ProjectStatus.INSTALLED
        assert installed["final_total_incentive_cents"] is None

        #  The physical dimension has moved for both lines; the verification dimension
        #  has not moved for either.
        before = read_project_measures(api, project_id)
        assert [line["install_status"] for line in before] == [
            InstallStatus.INSTALLED,
            InstallStatus.INSTALLED,
        ]
        assert [line["verification_status"] for line in before] == [
            VerificationStatus.PENDING,
            VerificationStatus.PENDING,
        ]
        assert [line["actual_cost_cents"] for line in before] == [700000, 150000]

        #  One inspection call, two different combined states.
        failed = record_result(
            api,
            world["inspection_id"],
            world["inspector_id"],
            build_fail_result_payload(
                [MEASURE_HPWH],
                deficiency_count=1,
                deficiency_severity_max=4,
                notes="Water heater condensate not to code",
            ),
        )
        assert failed["status"] == InspectionStatus.FAILED

        after_fail = read_project_measures(api, project_id)
        water = find_measure_line(after_fail, MEASURE_HPWH)
        assert water["verification_status"] == VerificationStatus.REJECTED
        assert water["rejection_reason"] == LineRejectionReason.INSPECTION_DEFICIENCY
        assert water["final_incentive_cents"] == 0
        assert water["install_status"] == InstallStatus.INSTALLED

        heat_pump = find_measure_line(after_fail, MEASURE_HP_HVAC)
        assert heat_pump["verification_status"] == VerificationStatus.PENDING
        assert heat_pump["install_status"] == InstallStatus.INSTALLED
        assert heat_pump["rejection_reason"] is None

        #  Only the surviving line allocates: min(800000, 800000, floor(700000 * 1.00)).
        after_project = read_project(api, project_id)
        assert after_project["status"] == ProjectStatus.INSPECTION_FAILED
        assert after_project["final_total_incentive_cents"] == 700000
        assert after_project["remediation_count"] == 0

        #  A threshold of 0 is never met from below, so the quality cascade stays out of
        #  the way of the remediation step.
        contractor = read_contractor(api, contractor_id)
        assert contractor["quality_score_rolling"] == 0
        assert contractor["completed_inspection_count"] == 1
        assert contractor["status"] == ContractorStatus.ENROLLED_ACTIVE

        #  Remediation closes the verification-dimension cycle without touching the
        #  physical dimension.
        remediated = open_remediation(
            api, project_id, contractor_id, remediation_notes="Condensate line re-run"
        )
        assert remediated["status"] == ProjectStatus.REMEDIATION
        assert remediated["remediation_count"] == 1

        reopened = find_measure_line(read_project_measures(api, project_id), MEASURE_HPWH)
        assert reopened["verification_status"] == VerificationStatus.PENDING
        assert reopened["rejection_reason"] is None
        assert reopened["install_status"] == InstallStatus.INSTALLED

        pending = read_project_measures(
            api, project_id, verification_status=VerificationStatus.PENDING
        )
        assert_measure_codes_in_order(pending, [MEASURE_HP_HVAC, MEASURE_HPWH])

    def test_rejection_voids_the_physical_dimension_while_a_pass_moves_only_the_other(self, api):
        """Each dimension has its own trigger, and neither drags the other along.

        PRD §3.6: "Rejecting moves the project `SUBMITTED → REJECTED`, which is terminal
        and sets every one of the project's measure lines to `install_status` `VOID`."

        PRD §3.7: "On the physical dimension a line goes `PLANNED` → `INSTALLED` when
        installation is reported, and reaches the terminal `VOID` from either `PLANNED`
        or `INSTALLED` — from `PLANNED` when the project is rejected at review or
        expires, and from `INSTALLED` when the project reaches `FAILED_FINAL`."

        PRD §3.8: "On a `POST_INSTALL` inspection of an installed project it moves the
        project `INSTALLED → VERIFIED`: every measure line moves `verification_status`
        from `PENDING` to `VERIFIED` and stores its `verified_quantity` from the result
        payload, the final allocation runs over the project and writes each line's
        `final_incentive_cents` and the project's `final_total_incentive_cents`, and the
        project's active stacking declaration, if one exists, is recomputed along with
        the project's `stacking_adjusted_state_incentive_cents`."

        Design: Difficulty/non_linear_state_machine/project_measure_parallel_install_and_verification_dimensions
        """
        world = build_world(
            api,
            stage="submitted",
            catalog=[build_hvac_heat_pump_payload(), build_water_heater_payload()],
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HPWH, 1, 300000),
            ],
        )
        household_id = world["household_id"]
        contractor_id = world["contractor_id"]
        doomed_id = world["project_id"]

        #  Nothing physical has happened yet on the first project.
        assert [line["install_status"] for line in read_project_measures(api, doomed_id)] == [
            InstallStatus.PLANNED,
            InstallStatus.PLANNED,
        ]

        rejected = review_project(api, doomed_id, ProjectReviewDecision.REJECT)
        assert rejected["status"] == ProjectStatus.REJECTED

        #  The review decision moved only the physical dimension, straight to its
        #  terminal value, and left verification where it was.
        voided = read_project_measures(api, doomed_id)
        assert [line["install_status"] for line in voided] == [
            InstallStatus.VOID,
            InstallStatus.VOID,
        ]
        assert [line["verification_status"] for line in voided] == [
            VerificationStatus.PENDING,
            VerificationStatus.PENDING,
        ]
        assert [line["final_incentive_cents"] for line in voided] == [None, None]

        #  A second project of the same household walks the other edge of each dimension.
        project = create_project(
            api,
            household_id,
            world["assessment_id"],
            contractor_id,
            world["income_verification"]["id"],
            [
                build_project_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_project_measure(MEASURE_HPWH, 1, 300000),
            ],
            estimated_project_cost_cents=1300000,
        )
        project_id = project["id"]
        assert project["provisional_total_incentive_cents"] == 975000
        submit_project(api, project_id, contractor_id)
        review_project(api, project_id)
        reserve_project(api, project_id, world["program_id"])
        report_installation(
            api,
            project_id,
            contractor_id,
            [
                build_measure_result(MEASURE_HP_HVAC, 1, 700000),
                build_measure_result(MEASURE_HPWH, 1, 150000),
            ],
            actual_project_cost_cents=850000,
        )
        mid = read_project_measures(api, project_id)
        assert [line["install_status"] for line in mid] == [
            InstallStatus.INSTALLED,
            InstallStatus.INSTALLED,
        ]
        assert [line["verification_status"] for line in mid] == [
            VerificationStatus.PENDING,
            VerificationStatus.PENDING,
        ]

        inspector = create_inspector(api, world["program_id"], inspector_name="Ivo Marek")
        inspection = schedule_inspection(api, project_id, inspector["id"])
        passed = record_result(api, inspection["id"], inspector["id"], build_pass_result_payload())
        assert passed["status"] == InspectionStatus.PASSED

        #  The pass moved verification only: 700000 + 150000 with no cap in the way.
        verified_project = read_project(api, project_id)
        assert verified_project["status"] == ProjectStatus.VERIFIED
        assert verified_project["final_total_incentive_cents"] == 850000
        verified_lines = read_project_measures(api, project_id)
        assert [line["verification_status"] for line in verified_lines] == [
            VerificationStatus.VERIFIED,
            VerificationStatus.VERIFIED,
        ]
        assert [line["install_status"] for line in verified_lines] == [
            InstallStatus.INSTALLED,
            InstallStatus.INSTALLED,
        ]
        assert [line["verified_quantity"] for line in verified_lines] == [1, 1]
        assert [line["final_incentive_cents"] for line in verified_lines] == [700000, 150000]


class TestContractorCycleVersusTerminalSibling:
    def test_the_same_two_node_cycle_is_entered_twice_for_two_different_reasons(self, api):
        """Admin action and a quality cascade write the same edge with different reasons.

        PRD §3.3: "Suspending an `ENROLLED_ACTIVE` contractor moves it `ENROLLED_ACTIVE →
        SUSPENDED` and sets `suspension_reason` to `ADMIN_ACTION` when the administrator
        initiated it, or to `QUALITY_SCORE` when the system initiated it as a quality
        cascade."

        PRD §3.3: "Reinstating a suspended contractor moves it `SUSPENDED →
        ENROLLED_ACTIVE` — permitted only when `license_expires_on` is still later than
        the logical clock's date — and cascades in the opposite direction: every project
        of this contractor in `CONTRACTOR_HOLD` whose reservation is still in status
        `RESERVED` moves `CONTRACTOR_HOLD → RESERVED`."

        PRD §3.3: "Each candidate contributes a point value determined by its status: 100
        points for `PASSED`, 70 for `CONDITIONAL_PASS`, and 0 for `FAILED`."

        PRD §3.3: "Rejecting it moves the contractor `PENDING_ENROLLMENT →
        ENROLLMENT_REJECTED`, which is terminal, stamping
        `enrollment_decided_by_user_id` and incrementing the version."

        PRD §3.8: "A `SPOT` failure recorded against a project already in `PAID` is the
        post-payment clawback, described in §3.9."

        Design: Difficulty/non_linear_state_machine/contractor_suspension_reinstatement_cycle_versus_terminal_rejection
        """
        world = build_world(api, stage="project", catalog=[build_hvac_heat_pump_payload()])
        program_id = world["program_id"]
        project_id = world["project_id"]
        contractor_id = world["contractor_id"]
        assert world["program"]["quality_suspension_threshold"] == (
            DEFAULT_QUALITY_SUSPENSION_THRESHOLD
        )
        enrolled = read_contractor(api, contractor_id)
        assert enrolled["status"] == ContractorStatus.ENROLLED_ACTIVE
        assert enrolled["quality_score_rolling"] == 100
        assert enrolled["suspension_reason"] is None

        #  A sibling installer parked in the terminal enrollment state.
        applicant = create_contractor(
            api,
            program_id,
            business_name="Nightshade Electric",
            license_number="EC-9002",
        )
        assert applicant["status"] == ContractorStatus.PENDING_ENROLLMENT
        terminal = decide_enrollment(
            api,
            applicant["id"],
            EnrollmentDecision.REJECT,
            decision_notes="License could not be verified",
        )
        assert terminal["status"] == ContractorStatus.ENROLLMENT_REJECTED
        terminal_version = terminal["version"]

        inspector = create_inspector(api, program_id, inspector_name="Ivo Marek")
        spot = schedule_inspection(
            api, project_id, inspector["id"], InspectionType.SPOT
        )

        #  First entry into SUSPENDED, driven by the administrator.
        suspended = suspend_contractor(
            api, contractor_id, suspension_reason=SuspensionReason.ADMIN_ACTION
        )
        assert suspended["status"] == ContractorStatus.SUSPENDED
        assert suspended["suspension_reason"] == SuspensionReason.ADMIN_ACTION
        assert suspended["version"] == enrolled["version"] + 1

        #  The cycle closes with no loss of standing.
        reinstated = reinstate_contractor(api, contractor_id)
        assert reinstated["status"] == ContractorStatus.ENROLLED_ACTIVE
        assert reinstated["quality_score_rolling"] == 100
        assert reinstated["completed_inspection_count"] == 0
        assert reinstated["version"] == suspended["version"] + 1

        #  Second entry into the very same state, this time by the score: one FAILED
        #  candidate scores 0, strictly below the threshold of 70.
        recorded = record_result(
            api,
            spot["id"],
            inspector["id"],
            build_fail_result_payload(deficiency_count=2, deficiency_severity_max=5),
        )
        assert recorded["status"] == InspectionStatus.FAILED

        cascaded = read_contractor(api, contractor_id)
        assert cascaded["status"] == ContractorStatus.SUSPENDED
        assert cascaded["suspension_reason"] == SuspensionReason.QUALITY_SCORE
        assert cascaded["quality_score_rolling"] == 0
        assert cascaded["completed_inspection_count"] == 1
        assert cascaded["version"] > reinstated["version"]

        #  A SPOT result on a project that holds no money moves no project money.
        assert read_project(api, project_id)["status"] == ProjectStatus.DRAFT

        #  The identical payload that closed the cycle for one contractor is refused for
        #  the terminal sibling.
        validate_error(
            api.set_contractor_suspension(
                applicant["id"],
                build_suspension_payload(SuspensionAction.REINSTATE),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )
        still_terminal = read_contractor(api, applicant["id"])
        assert still_terminal["status"] == ContractorStatus.ENROLLMENT_REJECTED
        assert still_terminal["version"] == terminal_version

    def test_neither_node_of_the_cycle_has_a_self_loop_and_no_other_state_has_the_edges(
        self, api
    ):
        """Suspend and reinstate exist only on the two nodes the cycle declares.

        PRD §3.3: "Suspension is a `ProgramAdmin` action taking an `action` of either
        suspend or reinstate, with an optional `suspension_reason`."

        PRD §3.3: "An application is created in `PENDING_ENROLLMENT` with
        `quality_score_rolling` at 100, `completed_inspection_count` at 0, and
        `suspension_reason` null."

        PRD §2.10: "**State gate.** The source entity is in a state from which the
        requested transition is declared, and the enclosing program is `OPEN` where the
        transition requires it. This is the umbrella rung, and an entity in a terminal
        state always fails here."

        Design: Difficulty/non_linear_state_machine/contractor_suspension_reinstatement_cycle_versus_terminal_rejection
        """
        world = build_world(api, stage="contractor", catalog=[build_hvac_heat_pump_payload()])
        program_id = world["program_id"]
        contractor_id = world["contractor_id"]
        active = read_contractor(api, contractor_id)
        assert active["status"] == ContractorStatus.ENROLLED_ACTIVE

        #  REINSTATE has no edge out of ENROLLED_ACTIVE.
        validate_error(
            api.set_contractor_suspension(
                contractor_id,
                build_suspension_payload(SuspensionAction.REINSTATE),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )
        assert read_contractor(api, contractor_id)["version"] == active["version"]

        suspended = suspend_contractor(api, contractor_id)
        assert suspended["status"] == ContractorStatus.SUSPENDED

        #  And SUSPEND has no edge out of SUSPENDED.
        validate_error(
            api.set_contractor_suspension(
                contractor_id,
                build_suspension_payload(SuspensionAction.SUSPEND),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )
        held = read_contractor(api, contractor_id)
        assert held["status"] == ContractorStatus.SUSPENDED
        assert held["version"] == suspended["version"]
        assert reinstate_contractor(api, contractor_id)["status"] == (
            ContractorStatus.ENROLLED_ACTIVE
        )

        #  An application that was never enrolled owns neither edge.
        applicant = create_contractor(
            api,
            program_id,
            business_name="Foothills Wiring",
            license_number="EC-9003",
        )
        assert applicant["status"] == ContractorStatus.PENDING_ENROLLMENT
        assert applicant["suspension_reason"] is None
        for action in (SuspensionAction.SUSPEND, SuspensionAction.REINSTATE):
            validate_error(
                api.set_contractor_suspension(
                    applicant["id"], build_suspension_payload(action), ADMIN_HEADERS
                ),
                ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            )
        untouched = read_contractor(api, applicant["id"])
        assert untouched["status"] == ContractorStatus.PENDING_ENROLLMENT
        assert untouched["version"] == applicant["version"]
        assert untouched["suspension_reason"] is None

        #  Nor does the terminal state, in either direction.
        rejected = decide_enrollment(api, applicant["id"], EnrollmentDecision.REJECT)
        assert rejected["status"] == ContractorStatus.ENROLLMENT_REJECTED
        for action in (SuspensionAction.SUSPEND, SuspensionAction.REINSTATE):
            validate_error(
                api.set_contractor_suspension(
                    applicant["id"], build_suspension_payload(action), ADMIN_HEADERS
                ),
                ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            )
        final = read_contractor(api, applicant["id"])
        assert final["status"] == ContractorStatus.ENROLLMENT_REJECTED
        assert final["version"] == rejected["version"]
