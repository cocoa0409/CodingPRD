"""Three pairs of simultaneously violated rungs, each with a forced winner and status code."""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    ContractorStatus,
    DEFAULT_LOW_TIER_CAP_CENTS,
    InspectionStatus,
    MEASURE_HP_DUCT,
    MEASURE_HP_HVAC,
    MEASURE_PANEL_200A,
    MEASURE_STOVE,
    ProjectStatus,
    REVIEWER_HEADERS,
    REVIEWER_TWO_HEADERS,
    SuspensionReason,
    UserRole,
    assert_household_cap,
    assert_program_buckets,
    assert_version_unchanged,
    build_assessment_measure,
    build_duct_payload,
    build_hvac_heat_pump_payload,
    build_inspection_payload,
    build_panel_200a_payload,
    build_project_measure,
    build_project_payload,
    build_reservation_payload,
    build_world,
    create_inspector,
    headers_without_user_id,
    read_assessment,
    read_household,
    read_program,
    read_project,
    reinstate_contractor,
    review_project,
    suspend_contractor,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStateGateBeatsBudgetExhaustion:
    def test_a_submitted_project_in_a_penniless_program_reports_the_state_error(self, api):
        """Both rungs are live; the 409 fourteen levels higher is the one reported.

        PRD §2.10: "Every request is evaluated against an ordered ladder of checks.
        Evaluation stops at the **first** violated rung; no later rung runs, and the
        response carries that rung's error. The order is normative — a caller with two
        simultaneous problems always learns about the lower-numbered one."

        PRD §2.10: "**State gate.** The source entity is in a state from which the
        requested transition is declared, and the enclosing program is `OPEN` where the
        transition requires it. This is the umbrella rung, and an entity in a terminal
        state always fails here."

        PRD §2.10: "**Appropriation available.** `budget_available_cents` is at least the
        amount to be reserved → otherwise `ERR_PROGRAM_BUDGET_EXHAUSTED` (422). Applies
        to `POST /rebate-projects/{id}/reservations`. This is the last rung in the entire
        ladder: appropriation scarcity is reported only when every other aspect of the
        request is sound."

        PRD §2.10: "A reservation requested for a project still in `SUBMITTED`, inside a
        program whose `budget_available_cents` is 0, reports
        `ERR_PROJECT_NOT_APPROVED_FOR_RESERVATION` (409) — the state gate at rung 8 wins
        over the budget rung by fourteen levels."

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_budget_exhaustion_on_reservation
        """
        world = build_world(
            api,
            stage="submitted",
            program_overrides={"budget_total_cents": 1},
            catalog=[build_hvac_heat_pump_payload()],
        )
        program_id = world["program_id"]
        project_id = world["project_id"]
        household_id = world["household_id"]

        #  One cent of appropriation against an 800000 ask, and the household cap is
        #  untouched so no rung between the two under test can fire.
        program_before = read_program(api, program_id)
        assert program_before["budget_available_cents"] == 1
        project_before = read_project(api, project_id)
        assert project_before["status"] == ProjectStatus.SUBMITTED
        assert project_before["provisional_total_incentive_cents"] == 800000
        assert project_before["reviewed_by_user_id"] is None
        assert_household_cap(
            read_household(api, household_id),
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
        )

        validate_error(
            api.create_reservation(
                project_id,
                build_reservation_payload(program_before["version"]),
                REVIEWER_TWO_HEADERS,
            ),
            ApiErrorId.ERR_PROJECT_NOT_APPROVED_FOR_RESERVATION,
            expected_status=409,
        )

        #  Nothing was encumbered and no version moved.
        _rows, meta = validate_paginated(
            api.list_reservations(REVIEWER_HEADERS, {"project_id": project_id})
        )
        assert meta["total_count"] == 0
        program_after = read_program(api, program_id)
        assert_program_buckets(program_after, available=1, reserved=0, committed=0, clawed_back=0)
        assert_version_unchanged(program_before, program_after, "program")
        project_after = read_project(api, project_id)
        assert project_after["status"] == ProjectStatus.SUBMITTED
        assert_version_unchanged(project_before, project_after, "project")
        assert_household_cap(
            read_household(api, household_id),
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
        )

    def test_approving_the_project_uncovers_the_appropriation_rung_underneath(self, api):
        """The fiscal violation was real: with the state problem gone it answers 422.

        PRD §3.6: "It requires the project to be `APPROVED`, the program to be `OPEN`, the
        contractor to be `ENROLLED_ACTIVE`, the acting `X-User-ID` to differ from the
        project's `reviewed_by_user_id`, the household's `lifetime_cap_remaining_cents` to
        be at least the project's `provisional_total_incentive_cents`, and the program's
        `budget_available_cents` to be at least that same amount."

        PRD §2.10: "**Household cap not exhausted.** At reservation time
        `lifetime_cap_remaining_cents` is at least 1 → otherwise
        `ERR_HOUSEHOLD_CAP_EXHAUSTED` (422). Applies to
        `POST /rebate-projects/{id}/reservations`."

        PRD §2.10: "**Appropriation available.** `budget_available_cents` is at least the
        amount to be reserved → otherwise `ERR_PROGRAM_BUDGET_EXHAUSTED` (422). Applies
        to `POST /rebate-projects/{id}/reservations`. This is the last rung in the entire
        ladder: appropriation scarcity is reported only when every other aspect of the
        request is sound."

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_budget_exhaustion_on_reservation
        """
        world = build_world(
            api,
            stage="submitted",
            program_overrides={"budget_total_cents": 1},
            catalog=[build_hvac_heat_pump_payload()],
        )
        program_id = world["program_id"]
        project_id = world["project_id"]
        household_id = world["household_id"]

        validate_error(
            api.create_reservation(
                project_id,
                build_reservation_payload(read_program(api, program_id)["version"]),
                REVIEWER_TWO_HEADERS,
            ),
            ApiErrorId.ERR_PROJECT_NOT_APPROVED_FOR_RESERVATION,
            expected_status=409,
        )

        #  Remove the rung-8 violation and nothing else.
        approved = review_project(api, project_id)
        assert approved["status"] == ProjectStatus.APPROVED
        program_before = read_program(api, program_id)
        assert program_before["budget_available_cents"] == 1
        household_before = read_household(api, household_id)
        assert household_before["lifetime_cap_remaining_cents"] == DEFAULT_LOW_TIER_CAP_CENTS

        validate_error(
            api.create_reservation(
                project_id,
                build_reservation_payload(program_before["version"]),
                REVIEWER_TWO_HEADERS,
            ),
            ApiErrorId.ERR_PROGRAM_BUDGET_EXHAUSTED,
            expected_status=422,
        )

        #  The refusal is still a refusal: nothing moved.
        _rows, meta = validate_paginated(
            api.list_reservations(REVIEWER_HEADERS, {"project_id": project_id})
        )
        assert meta["total_count"] == 0
        program_after = read_program(api, program_id)
        assert_program_buckets(program_after, available=1, reserved=0, committed=0, clawed_back=0)
        assert_version_unchanged(program_before, program_after, "program")
        project_after = read_project(api, project_id)
        assert project_after["status"] == ProjectStatus.APPROVED
        assert_version_unchanged(approved, project_after, "project")
        assert_household_cap(
            read_household(api, household_id),
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
        )


class TestInstallerFitnessBeatsMeasureSetCoherence:
    def test_a_suspended_contractor_masks_the_anchorless_panel_upgrade(self, api):
        """409 at rung 11, not 422 at rung 13, though the measure set is genuinely broken.

        PRD §2.10: "**Installer fitness.** The contractor attached to the operation is
        `ENROLLED_ACTIVE`, and both `license_expires_on` and `insurance_expires_on` fall
        on or after the logical clock's date. Enrollment status is checked *before*
        credential currency, so a suspended contractor with lapsed paperwork reports
        `ERR_CONTRACTOR_NOT_ACTIVE` rather than `ERR_CONTRACTOR_CREDENTIAL_EXPIRED`; both
        are 409."

        PRD §2.10: "**Measure-set coherence.** A panel or service upgrade line requires at
        least one qualifying appliance anchor line on the same project, and every line
        whose catalog item declares a `prerequisite_measure_code` requires that measure to
        be present and qualified on the same project. The anchor rule is evaluated first
        and reports `ERR_PANEL_UPGRADE_ANCHOR_MISSING`; the prerequisite rule follows and
        reports `ERR_PREREQUISITE_MEASURE_MISSING`; both are 422."

        PRD §2.10: "A project opened with a suspended contractor **and** a panel upgrade
        with no qualifying appliance anchor reports `ERR_CONTRACTOR_NOT_ACTIVE` (409):
        installer fitness at rung 11 outranks measure-set coherence at rung 13."

        Design: Difficulty/priority_pair_validation_conflict/installer_fitness_beats_measure_set_coherence_on_project_create
        """
        world = build_world(
            api,
            stage="assessment",
            catalog=[build_hvac_heat_pump_payload(), build_panel_200a_payload()],
            household_overrides={"existing_panel_amps": 100},
            assessed_panel_amps=100,
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_PANEL_200A, 1, 600000),
            ],
        )
        contractor_id = world["contractor_id"]

        #  Both measures qualified at assessment time, so rungs 14 and 15 are satisfied
        #  and the panel line carries the capacity the dwelling will have.
        assessment = read_assessment(api, world["assessment_id"])
        assert assessment["qualified_measure_count"] == 2
        assert assessment["effective_panel_amps"] == 200

        suspended = suspend_contractor(
            api, contractor_id, suspension_reason=SuspensionReason.ADMIN_ACTION
        )
        assert suspended["status"] == ContractorStatus.SUSPENDED

        payload = build_project_payload(
            world["household_id"],
            world["assessment_id"],
            contractor_id,
            world["income_verification"]["id"],
            [build_project_measure(MEASURE_PANEL_200A, 1, 600000)],
            estimated_project_cost_cents=600000,
        )
        validate_error(
            api.create_rebate_project(payload, world["contractor_headers"]),
            ApiErrorId.ERR_CONTRACTOR_NOT_ACTIVE,
            expected_status=409,
        )
        _rows, meta = validate_paginated(api.list_rebate_projects(REVIEWER_HEADERS))
        assert meta["total_count"] == 0

        #  Clear rung 11 and the outranked rung-13 violation surfaces unchanged.
        reinstated = reinstate_contractor(api, contractor_id)
        assert reinstated["status"] == ContractorStatus.ENROLLED_ACTIVE
        validate_error(
            api.create_rebate_project(payload, world["contractor_headers"]),
            ApiErrorId.ERR_PANEL_UPGRADE_ANCHOR_MISSING,
            expected_status=422,
        )
        _still, still_meta = validate_paginated(api.list_rebate_projects(REVIEWER_HEADERS))
        assert still_meta["total_count"] == 0

    def test_the_same_pair_orders_the_prerequisite_arm_and_yields_to_rung_six(self, api):
        """The masking is the rung number, not the specific coherence error.

        PRD §2.10: "**Measure-set coherence.** A panel or service upgrade line requires at
        least one qualifying appliance anchor line on the same project, and every line
        whose catalog item declares a `prerequisite_measure_code` requires that measure to
        be present and qualified on the same project. The anchor rule is evaluated first
        and reports `ERR_PANEL_UPGRADE_ANCHOR_MISSING`; the prerequisite rule follows and
        reports `ERR_PREREQUISITE_MEASURE_MISSING`; both are 422."

        PRD §2.10: "**Installer fitness.** The contractor attached to the operation is
        `ENROLLED_ACTIVE`, and both `license_expires_on` and `insurance_expires_on` fall
        on or after the logical clock's date."

        PRD §2.10: "**Body-referenced entities exist and belong to the same program.** This
        covers `program_id`, `household_id`, `contractor_id`, `inspector_id`,
        `assessment_id`, `income_verification_id`, `project_id`, and every `measure_code`
        that must resolve to a catalog item of that program. Body references are resolved
        after path references, in the declaration order of the request body. A
        `measure_code` that exists only in another program's catalog is treated as absent
        and yields `ERR_MEASURE_CODE_NOT_IN_CATALOG` (404)."

        Design: Difficulty/priority_pair_validation_conflict/installer_fitness_beats_measure_set_coherence_on_project_create
        """
        world = build_world(
            api,
            stage="assessment",
            catalog=[build_hvac_heat_pump_payload(), build_duct_payload()],
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HP_DUCT, 1, 300000),
            ],
        )
        contractor_id = world["contractor_id"]
        assessment = read_assessment(api, world["assessment_id"])
        assert assessment["qualified_measure_count"] == 2

        suspend_contractor(api, contractor_id, suspension_reason=SuspensionReason.ADMIN_ACTION)

        #  The duct line's catalog item declares HP-HVAC-01 as its prerequisite, and the
        #  request leaves it out.
        payload = build_project_payload(
            world["household_id"],
            world["assessment_id"],
            contractor_id,
            world["income_verification"]["id"],
            [build_project_measure(MEASURE_HP_DUCT, 1, 300000)],
            estimated_project_cost_cents=300000,
        )
        validate_error(
            api.create_rebate_project(payload, world["contractor_headers"]),
            ApiErrorId.ERR_CONTRACTOR_NOT_ACTIVE,
            expected_status=409,
        )

        #  A body reference that resolves to nothing is checked five rungs earlier than
        #  installer fitness, so the suspension cannot mask it.
        unknown_payload = build_project_payload(
            world["household_id"],
            world["assessment_id"],
            contractor_id,
            world["income_verification"]["id"],
            [build_project_measure(MEASURE_STOVE, 1, 200000)],
            estimated_project_cost_cents=200000,
        )
        validate_error(
            api.create_rebate_project(unknown_payload, world["contractor_headers"]),
            ApiErrorId.ERR_MEASURE_CODE_NOT_IN_CATALOG,
            expected_status=404,
        )

        #  Reinstated, the prerequisite arm of rung 13 answers instead.
        reinstate_contractor(api, contractor_id)
        validate_error(
            api.create_rebate_project(payload, world["contractor_headers"]),
            ApiErrorId.ERR_PREREQUISITE_MEASURE_MISSING,
            expected_status=422,
        )
        _rows, meta = validate_paginated(api.list_rebate_projects(REVIEWER_HEADERS))
        assert meta["total_count"] == 0

        #  Naming the prerequisite alongside it is accepted, so nothing else was wrong.
        good_payload = build_project_payload(
            world["household_id"],
            world["assessment_id"],
            contractor_id,
            world["income_verification"]["id"],
            [
                build_project_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_project_measure(MEASURE_HP_DUCT, 1, 300000),
            ],
            estimated_project_cost_cents=1300000,
        )
        created = validate_success(
            api.create_rebate_project(good_payload, world["contractor_headers"]), 201
        )
        assert created["status"] == ProjectStatus.DRAFT


class TestRoleGateBeatsMalformedBody:
    def test_a_forbidden_role_hears_403_even_with_two_fields_missing(self, api):
        """The body is unusable, but rung 2 answers before rung 3 ever runs.

        PRD §2.10: "**Role permitted.** `X-User-Role` is present and listed among the
        endpoint's authorised roles → otherwise `ERR_FORBIDDEN_ROLE` (403). This beats
        body validation: a `Contractor` posting a malformed payment body receives 403,
        never 400. Applies to every endpoint."

        PRD §2.10: "**Request shape.** The body or query parses; required fields are
        present; types and enumerated values are valid; numeric ranges are respected; a
        date or datetime range is ordered so that the end is not earlier than the start →
        otherwise `ERR_INVALID_REQUEST` (400). This runs before any database lookup, so a
        malformed body aimed at a non-existent parent yields 400, not 404."

        PRD §2.10: "**Identity present.** `X-User-ID` is present and non-empty → otherwise
        `ERR_UNAUTHENTICATED` (401). This precedes everything, including malformed bodies.
        Applies to every endpoint."

        PRD §3.1: "The mandatory inputs are a published `name`, a `state_code` of exactly
        two uppercase letters identifying the state that owns the program, and a
        `budget_total_cents` appropriation of zero or more."

        Design: Difficulty/priority_pair_validation_conflict/role_gate_beats_malformed_request_body
        """
        world = build_world(api, stage="household", catalog=[build_hvac_heat_pump_payload()])
        _programs, before = validate_paginated(api.list_programs(ADMIN_HEADERS))
        assert before["total_count"] == 1

        #  Program creation is exclusive to ProgramAdmin; this body is missing `name` and
        #  `budget_total_cents` and its `state_code` is not two uppercase letters.
        broken = {"state_code": "COLORADO"}
        validate_error(
            api.create_program(broken, world["applicant_headers"]),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )

        #  The same body from the authorised role reaches rung 3 and is refused there.
        validate_error(
            api.create_program(broken, ADMIN_HEADERS),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        #  Drop the identity and the answer moves up one rung again.
        validate_error(
            api.create_program(broken, headers_without_user_id(UserRole.PROGRAM_ADMIN)),
            ApiErrorId.ERR_UNAUTHENTICATED,
            expected_status=401,
        )

        _after_programs, after = validate_paginated(api.list_programs(ADMIN_HEADERS))
        assert after["total_count"] == 1

    def test_an_inverted_inspection_window_is_still_a_403_for_two_wrong_roles(self, api):
        """Same pair, a different endpoint and a different shape violation.

        PRD §2.10: "**Role permitted.** `X-User-Role` is present and listed among the
        endpoint's authorised roles → otherwise `ERR_FORBIDDEN_ROLE` (403). This beats
        body validation: a `Contractor` posting a malformed payment body receives 403,
        never 400. Applies to every endpoint."

        PRD §2.10: "**Request shape.** The body or query parses; required fields are
        present; types and enumerated values are valid; numeric ranges are respected; a
        date or datetime range is ordered so that the end is not earlier than the start →
        otherwise `ERR_INVALID_REQUEST` (400)."

        PRD §3.8: "A `ProgramReviewer` or `ProgramAdmin` schedules one by naming the
        `project_id`, the `inspector_id`, the `inspection_type`, and the on-site window as
        a `scheduled_start` that is inclusive and a `scheduled_end` that is exclusive."

        Design: Difficulty/priority_pair_validation_conflict/role_gate_beats_malformed_request_body
        """
        world = build_world(api, stage="reserved", catalog=[build_hvac_heat_pump_payload()])
        inspector = create_inspector(api, world["program_id"], inspector_name="Lena Fuchs")
        inverted = build_inspection_payload(
            world["project_id"],
            inspector["id"],
            scheduled_start="2026-08-21T11:00:00Z",
            scheduled_end="2026-08-21T09:00:00Z",
        )

        #  Neither the contractor nor the applicant may schedule an inspection.
        for headers in (world["contractor_headers"], world["applicant_headers"]):
            validate_error(
                api.create_inspection(inverted, headers),
                ApiErrorId.ERR_FORBIDDEN_ROLE,
                expected_status=403,
            )

        #  With no identity at all the 401 outranks even the role gate.
        validate_error(
            api.create_inspection(inverted, headers_without_user_id(UserRole.CONTRACTOR)),
            ApiErrorId.ERR_UNAUTHENTICATED,
            expected_status=401,
        )

        #  The reviewer is authorised, so the inverted window is finally reported.
        validate_error(
            api.create_inspection(inverted, REVIEWER_HEADERS),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )
        _rows, meta = validate_paginated(
            api.list_inspections(REVIEWER_HEADERS, {"project_id": world["project_id"]})
        )
        assert meta["total_count"] == 0

        #  Ordering the window correctly is all that was missing.
        scheduled = validate_success(
            api.create_inspection(
                build_inspection_payload(world["project_id"], inspector["id"]),
                REVIEWER_HEADERS,
            ),
            201,
        )
        assert scheduled["status"] == InspectionStatus.SCHEDULED
