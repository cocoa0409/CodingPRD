"""Triggerable error codes: identity, existence, state gates and fiscal refusals."""

from test_helpers import (
    ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    AssessmentDecision,
    AssessmentStatus,
    CombinedCapGroup,
    DEFAULT_LOW_TIER_CAP_CENTS,
    IncomeTier,
    IncomeVerificationStatus,
    MEASURE_ENV_INS,
    MEASURE_HP_DUCT,
    MEASURE_HP_HVAC,
    ProjectStatus,
    REVIEWER_HEADERS,
    REVIEWER_TWO_HEADERS,
    ReservationStatus,
    StackingDeclarationStatus,
    UserRole,
    assert_household_cap,
    assert_program_buckets,
    build_assessment_measure,
    build_assessment_payload,
    build_duct_payload,
    build_extension_payload,
    build_hvac_heat_pump_payload,
    build_income_verification_payload,
    build_installation_payload,
    build_insulation_payload,
    build_measure_result,
    build_project_measure,
    build_project_payload,
    build_reservation_payload,
    build_verify_decision_payload,
    build_world,
    create_assessment,
    create_enrolled_contractor,
    create_household,
    create_project,
    decide_assessment,
    file_income_verification,
    find_by,
    find_measure_line,
    household_version,
    make_applicant_headers,
    make_contractor_headers,
    program_version,
    read_assessment,
    read_eligible_measures,
    read_household,
    read_income_verification,
    read_program,
    read_project,
    read_project_measures,
    read_reservation,
    report_installation,
    reserve_project,
    review_project,
    set_clock,
    submit_project,
    sweep,
    validate_error,
    validate_paginated,
    validate_success,
    verify_income_verification,
)


class TestIdentityAndOwnership:
    def test_identity_then_existence_then_ownership_answer_the_same_household_read(self, api):
        """401, then 404 for a stranger id, then 403 for someone else's real household.

        PRD §2.1: "A request with a missing or empty `X-User-ID` is rejected with
        `ERR_UNAUTHENTICATED` (401) before any other consideration, including the
        shape of the body."

        PRD §2.10: "This rung deliberately sits *after* existence, so probing for a
        foreign identifier returns 404 when the identifier does not exist and 403
        when it does."

        PRD §3.2: "At intake the household's `ami_percent` and `income_tier` are
        both null, and `rebate_cap_cents`, `lifetime_cap_remaining_cents`, and
        `encumbered_cents` are all 0; nothing is assigned until a verification is
        decided."

        Design: Corner/errors/missing_user_id_header_then_foreign_household_read
        """
        world = build_world(api, stage="program", catalog=[build_hvac_heat_pump_payload()])
        mine = create_household(api, world["program_id"], applicant_name="Ada Rivera")
        theirs = create_household(
            api,
            world["program_id"],
            applicant_name="Bo Nakamura",
            email="bo@example.com",
            service_address_line1="88 Birch Ave",
        )
        my_headers = make_applicant_headers(mine["id"])

        validate_error(
            api.get_household(mine["id"], {"X-User-ID": "", "X-User-Role": UserRole.APPLICANT}),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )
        validate_error(
            api.get_household(NON_EXISTENT_UUID, my_headers), ApiErrorId.ERR_HOUSEHOLD_NOT_FOUND
        )
        validate_error(
            api.get_household(theirs["id"], my_headers), ApiErrorId.ERR_NOT_RESOURCE_OWNER
        )
        validate_error(
            api.create_income_verification(
                theirs["id"], build_income_verification_payload(), my_headers
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        )

        #  Nothing the four refused calls touched was written.
        _rows, meta = validate_paginated(
            api.list_income_verifications(theirs["id"], REVIEWER_HEADERS)
        )
        assert meta["total_count"] == 0
        assert read_household(api, theirs["id"])["version"] == 1

        own = validate_success(api.get_household(mine["id"], my_headers))
        assert own["id"] == mine["id"]
        assert own["ami_percent"] is None
        assert own["income_tier"] is None
        assert own["rebate_cap_cents"] == 0
        assert_household_cap(own, remaining=0, encumbered=0, cap=0)


class TestNotFoundCodes:
    def test_every_addressable_aggregate_owns_its_own_not_found_code(self, api):
        """One syntactically valid identifier, nine different 404s.

        PRD §2.10: "**Path entities exist,** resolved strictly left to right along
        the path. The error names the leftmost missing segment, drawn from
        `ERR_PROGRAM_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`,
        `ERR_CONTRACTOR_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_INCOME_VERIFICATION_NOT_FOUND`,
        `ERR_PROJECT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`,
        `ERR_INSPECTION_NOT_FOUND`, and `ERR_CLAWBACK_ACTION_NOT_FOUND`, each 404."

        Design: Corner/errors/not_found_sweep_over_every_addressable_aggregate
        """
        world = build_world(api, stage="program", catalog=[build_hvac_heat_pump_payload()])

        validate_error(
            api.get_program(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            ApiErrorId.ERR_PROGRAM_NOT_FOUND,
        )
        validate_error(
            api.get_household(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            ApiErrorId.ERR_HOUSEHOLD_NOT_FOUND,
        )
        validate_error(
            api.get_contractor(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            ApiErrorId.ERR_CONTRACTOR_NOT_FOUND,
        )
        validate_error(
            api.get_inspector(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            ApiErrorId.ERR_INSPECTOR_NOT_FOUND,
        )
        validate_error(
            api.get_assessment(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            ApiErrorId.ERR_ASSESSMENT_NOT_FOUND,
        )
        #  A well-formed decision body cannot rescue a missing packet: rung 5 answers
        #  long before the state gate at rung 8.
        validate_error(
            api.verify_income_verification(
                NON_EXISTENT_UUID, build_verify_decision_payload(), REVIEWER_HEADERS
            ),
            ApiErrorId.ERR_INCOME_VERIFICATION_NOT_FOUND,
        )
        validate_error(
            api.get_rebate_project(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            ApiErrorId.ERR_PROJECT_NOT_FOUND,
        )
        validate_error(
            api.get_reservation(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            ApiErrorId.ERR_RESERVATION_NOT_FOUND,
        )
        validate_error(
            api.get_inspection(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            ApiErrorId.ERR_INSPECTION_NOT_FOUND,
        )
        validate_error(
            api.get_clawback_action(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            ApiErrorId.ERR_CLAWBACK_ACTION_NOT_FOUND,
        )

        #  The store is healthy: the real program reads back and the empty audit
        #  collection lists cleanly.
        assert validate_success(api.get_program(world["program_id"], REVIEWER_HEADERS))["id"] == (
            world["program_id"]
        )
        _actions, meta = validate_paginated(api.list_clawback_actions(REVIEWER_HEADERS))
        assert meta["total_count"] == 0


class TestAssessmentBacking:
    def test_pending_superseded_and_rejected_assessments_all_refuse_to_back_a_project(self, api):
        """One code for three assessment states, including one that was approved.

        PRD §3.4: "Only an `APPROVED` assessment can back a rebate project;
        anything else is refused with `ERR_ASSESSMENT_NOT_APPROVED`."

        PRD §3.4: "creating it moves the household's prior live assessment —
        whether it stood in `PENDING_REVIEW` or `APPROVED` — to `SUPERSEDED`,
        incrementing the superseded row's version."

        Design: Corner/errors/project_creation_requires_an_approved_assessment_in_all_three_bad_states
        """
        measures = [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)]
        world = build_world(
            api,
            stage="assessment",
            catalog=[build_hvac_heat_pump_payload()],
            assessment_measures=measures,
            approve_assessment=False,
        )
        household_id = world["household_id"]
        contractor_id = world["contractor_id"]
        first = world["assessment"]
        contractor_headers = make_contractor_headers(contractor_id)
        lines = [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)]

        def project_payload(assessment_id):
            return build_project_payload(
                household_id,
                assessment_id,
                contractor_id,
                world["income_verification"]["id"],
                lines,
                estimated_project_cost_cents=1000000,
            )

        assert first["status"] == AssessmentStatus.PENDING_REVIEW
        validate_error(
            api.create_rebate_project(project_payload(first["id"]), contractor_headers),
            ApiErrorId.ERR_ASSESSMENT_NOT_APPROVED,
        )

        #  Approval is the only thing that changes between the two calls.
        decide_assessment(api, first["id"])
        project = validate_success(
            api.create_rebate_project(project_payload(first["id"]), contractor_headers),
            expected_status=201,
        )

        #  Filing a fresh assessment revokes the earlier approval.
        second = create_assessment(
            api,
            household_id,
            contractor_id,
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1050000)],
        )
        assert read_assessment(api, first["id"])["status"] == AssessmentStatus.SUPERSEDED
        validate_error(
            api.create_rebate_project(project_payload(first["id"]), contractor_headers),
            ApiErrorId.ERR_ASSESSMENT_NOT_APPROVED,
        )

        decide_assessment(
            api, second["id"], AssessmentDecision.REJECT, review_notes="Load calculation missing"
        )
        assert read_assessment(api, second["id"])["status"] == AssessmentStatus.REJECTED
        validate_error(
            api.create_rebate_project(project_payload(second["id"]), contractor_headers),
            ApiErrorId.ERR_ASSESSMENT_NOT_APPROVED,
        )

        rows, meta = validate_paginated(
            api.list_rebate_projects(REVIEWER_HEADERS, {"household_id": household_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == project["id"]
        assert read_project(api, project["id"])["status"] == ProjectStatus.DRAFT


class TestExpiryIsClockDriven:
    def test_installation_and_extension_are_refused_before_the_sweep_materialises_expiry(
        self, api
    ):
        """The row still reads RESERVED, yet both money-path calls are 409.

        PRD §3.7: "the project's reservation is still in status `RESERVED` with the
        logical clock strictly before its `expires_at`"

        PRD §3.6: "one already past its `expires_at` before the sweep has run is
        refused with `ERR_RESERVATION_EXPIRED`."

        Design: Corner/errors/installation_and_extension_after_expiry_but_before_the_sweep
        """
        world = build_world(api, stage="reserved", catalog=[build_hvac_heat_pump_payload()])
        program_id = world["program_id"]
        project_id = world["project_id"]
        reservation_id = world["reservation_id"]
        contractor_headers = make_contractor_headers(world["contractor_id"])
        results = [build_measure_result(MEASURE_HP_HVAC, 1, 700000)]

        set_clock(api, "2026-11-30T09:00:00Z")
        lapsed = read_reservation(api, reservation_id)
        assert lapsed["status"] == ReservationStatus.RESERVED
        assert lapsed["expires_at"].startswith("2026-11-29")

        validate_error(
            api.report_installation(
                project_id,
                build_installation_payload(
                    results,
                    install_start_date="2026-11-25",
                    install_end_date="2026-11-28",
                    actual_project_cost_cents=700000,
                ),
                contractor_headers,
            ),
            ApiErrorId.ERR_RESERVATION_EXPIRED,
        )
        held = read_project(api, project_id)
        assert held["status"] == ProjectStatus.RESERVED
        assert held["actual_project_cost_cents"] is None

        #  The state gate answers before the extension window arithmetic ever runs.
        validate_error(
            api.create_reservation_extension(
                reservation_id,
                build_extension_payload(30, extension_reason="Equipment backorder"),
                contractor_headers,
            ),
            ApiErrorId.ERR_RESERVATION_EXPIRED,
        )
        still = read_reservation(api, reservation_id)
        assert still["extension_count"] == 0
        assert still["extension_days_granted"] == 0
        assert still["expires_at"] == lapsed["expires_at"]

        result = sweep(api, program_id)
        assert result["swept_reservation_count"] == 1
        assert result["released_cents"] == 800000
        assert result["expired_project_ids"] == [project_id]

        #  After the sweep the same report meets a terminal project, so the code changes.
        validate_error(
            api.report_installation(
                project_id,
                build_installation_payload(
                    results,
                    install_start_date="2026-11-25",
                    install_end_date="2026-11-28",
                    actual_project_cost_cents=700000,
                ),
                contractor_headers,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )
        assert_program_buckets(
            read_program(api, program_id), available=50000000, reserved=0, committed=0
        )


class TestCommittedReservation:
    def test_a_committed_reservation_answers_not_active_while_the_paid_project_answers_terminal(
        self, api
    ):
        """Two different codes for the same "too late", from two different gates.

        PRD §3.6: "a reservation that is not in status `RESERVED` is refused with
        `ERR_RESERVATION_NOT_ACTIVE`, and one already past its `expires_at` before
        the sweep has run is refused with `ERR_RESERVATION_EXPIRED`."

        PRD §2.10: "This is the umbrella rung, and an entity in a terminal state
        always fails here."

        Design: Corner/errors/extension_request_on_a_committed_reservation_rejected
        """
        world = build_world(
            api,
            stage="paid",
            catalog=[build_hvac_heat_pump_payload()],
            measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
        )
        project_id = world["project_id"]
        reservation_id = world["reservation_id"]
        contractor_headers = make_contractor_headers(world["contractor_id"])

        committed = read_reservation(api, reservation_id)
        assert committed["status"] == ReservationStatus.COMMITTED
        assert committed["expires_at"].startswith("2026-11-29")
        assert committed["extension_count"] == 0

        validate_error(
            api.create_reservation_extension(
                reservation_id,
                build_extension_payload(30, extension_reason="Punch list follow-up"),
                contractor_headers,
            ),
            ApiErrorId.ERR_RESERVATION_NOT_ACTIVE,
        )
        unchanged = read_reservation(api, reservation_id)
        assert unchanged["expires_at"] == committed["expires_at"]
        assert unchanged["extension_count"] == 0
        assert unchanged["extension_days_granted"] == 0

        validate_error(
            api.report_installation(
                project_id,
                build_installation_payload(
                    [build_measure_result(MEASURE_HP_HVAC, 1, 750000)],
                    install_start_date="2026-08-25",
                    install_end_date="2026-08-26",
                    actual_project_cost_cents=750000,
                ),
                contractor_headers,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )
        paid = read_project(api, project_id)
        assert paid["status"] == ProjectStatus.PAID
        assert paid["disbursed_amount_cents"] == 700000
        assert paid["actual_project_cost_cents"] == 700000


class TestCollisionShapedFailures:
    def test_duplicate_catalog_code_unknown_code_and_a_repeated_project_line_differ(self, api):
        """Three collisions, three codes, and no household version consumed.

        PRD §3.1: "Reusing a `measure_code` already present in that program's
        catalog is refused with `ERR_DUPLICATE_MEASURE_CODE` (409)."

        PRD §2.10: "A `measure_code` that exists only in another program's catalog
        is treated as absent and yields `ERR_MEASURE_CODE_NOT_IN_CATALOG` (404)."

        PRD §2.10: "Every requested `measure_code` appears on the linked assessment
        as an eligible-measure row whose `qualified` flag is true, and no
        `measure_code` repeats within one request."

        Design: Corner/errors/duplicate_catalog_code_duplicate_line_and_unknown_measure_code
        """
        world = build_world(api, stage="contractor", catalog=[build_hvac_heat_pump_payload()])
        program_id = world["program_id"]
        household_id = world["household_id"]
        contractor_id = world["contractor_id"]
        contractor_headers = make_contractor_headers(contractor_id)

        validate_error(
            api.create_catalog_item(
                program_id,
                build_hvac_heat_pump_payload(
                    measure_name="Ducted heat pump (revised)",
                    unit_incentive_cents=900000,
                    measure_cap_cents=900000,
                    sort_order=11,
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_MEASURE_CODE,
        )
        items, catalog_meta = validate_paginated(
            api.list_catalog_items(program_id, REVIEWER_HEADERS)
        )
        assert catalog_meta["total_count"] == 1
        survivor = find_by(items, "measure_code", MEASURE_HP_HVAC)
        assert survivor["unit_incentive_cents"] == 800000
        assert survivor["measure_name"] == "Ducted air-source heat pump"

        version = household_version(api, household_id)
        validate_error(
            api.create_assessment(
                build_assessment_payload(
                    household_id,
                    contractor_id,
                    version,
                    [build_assessment_measure("XX-NONE-99", 1, 500000)],
                ),
                contractor_headers,
            ),
            ApiErrorId.ERR_MEASURE_CODE_NOT_IN_CATALOG,
        )

        #  The refused call consumed nothing, so the same token still works.
        assessment = create_assessment(
            api,
            household_id,
            contractor_id,
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
            expected_household_version=version,
        )
        assert assessment["qualified_measure_count"] == 1
        assert household_version(api, household_id) == version + 1
        decide_assessment(api, assessment["id"])

        #  A code repeated inside one project request is a different failure again.
        validate_error(
            api.create_rebate_project(
                build_project_payload(
                    household_id,
                    assessment["id"],
                    contractor_id,
                    world["income_verification"]["id"],
                    [
                        build_project_measure(MEASURE_HP_HVAC, 1, 1000000),
                        build_project_measure(MEASURE_HP_HVAC, 1, 900000),
                    ],
                    estimated_project_cost_cents=1900000,
                ),
                contractor_headers,
            ),
            ApiErrorId.ERR_DUPLICATE_MEASURE_LINE,
        )
        _projects, project_meta = validate_paginated(
            api.list_rebate_projects(REVIEWER_HEADERS, {"household_id": household_id})
        )
        assert project_meta["total_count"] == 0
        _assessments, assessment_meta = validate_paginated(
            api.list_assessments(REVIEWER_HEADERS, {"household_id": household_id})
        )
        assert assessment_meta["total_count"] == 1


class TestIncomeGate:
    def test_an_unverified_household_may_hold_an_assessment_but_not_open_a_project(self, api):
        """The identical payload is refused, then accepted, on verification alone.

        PRD §2.10: "**Income tier verified.** The household holds a `VERIFIED`
        income verification, so an `income_tier` and a `rebate_cap_cents` exist →
        otherwise `ERR_INCOME_TIER_NOT_VERIFIED` (422). Applies to
        `POST /rebate-projects` and `POST /rebate-projects/{id}/reservations`. An
        unverified household may still hold assessments."

        PRD §3.2: "It also writes the household's `ami_percent`, `income_tier`, and
        `rebate_cap_cents`, and sets `lifetime_cap_remaining_cents` to the assigned
        cap minus whatever the household already has in `encumbered_cents`."

        Design: Corner/errors/project_creation_without_a_verified_income_tier_rejected
        """
        world = build_world(api, stage="program", catalog=[build_hvac_heat_pump_payload()])
        program_id = world["program_id"]
        household = create_household(api, program_id)
        household_id = household["id"]
        verification = file_income_verification(api, household_id)
        enrolled = create_enrolled_contractor(api, program_id)
        contractor_headers = make_contractor_headers(enrolled["id"])
        assessment = create_assessment(
            api,
            household_id,
            enrolled["id"],
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
        )
        assessment = decide_assessment(api, assessment["id"])
        assert assessment["status"] == AssessmentStatus.APPROVED
        assert assessment["qualified_measure_count"] == 1

        unverified = read_household(api, household_id)
        assert unverified["income_tier"] is None
        assert unverified["rebate_cap_cents"] == 0
        assert (
            read_income_verification(api, household_id, verification["id"])["status"]
            == IncomeVerificationStatus.SUBMITTED
        )

        payload = build_project_payload(
            household_id,
            assessment["id"],
            enrolled["id"],
            verification["id"],
            [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
            estimated_project_cost_cents=1000000,
        )
        validate_error(
            api.create_rebate_project(payload, contractor_headers),
            ApiErrorId.ERR_INCOME_TIER_NOT_VERIFIED,
        )
        _rows, meta = validate_paginated(
            api.list_rebate_projects(REVIEWER_HEADERS, {"household_id": household_id})
        )
        assert meta["total_count"] == 0

        verify_income_verification(api, verification["id"])
        verified = read_household(api, household_id)
        assert verified["ami_percent"] == 80.0
        assert verified["income_tier"] == IncomeTier.LOW
        assert_household_cap(
            verified,
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

        #  The byte-identical payload now passes, and no new assessment was filed.
        project = validate_success(
            api.create_rebate_project(payload, contractor_headers), expected_status=201
        )
        assert project["provisional_total_incentive_cents"] == 800000
        assert project["assessment_id"] == assessment["id"]


class TestStackingHeadroom:
    def test_a_declaration_that_annihilates_the_state_share_is_refused_not_recorded(self, api):
        """A partial haircut is legal; driving the state incentive to 0 is not.

        PRD §2.10: "**Stacking headroom.** The declared utility rebate and the
        computed federal credit leave a state incentive above zero; a declaration
        that would drive the allowed state incentive to 0 is rejected rather than
        recorded, with `ERR_STACKING_LIMIT_EXCEEDED` (422)."

        PRD §3.9: "If the total benefit exceeds the limit, the allowed state
        incentive becomes the state incentive less the excess, clamped up to 0;
        otherwise the allowed state incentive is the state incentive unchanged."

        PRD §3.9: "That last figure is recorded strictly for the audit trail: it
        never enters any computation."

        Design: Corner/errors/stacking_declaration_that_zeroes_the_state_incentive_rejected
        """
        world = build_world(
            api,
            stage="project",
            catalog=[build_hvac_heat_pump_payload()],
            assessment_measures=[build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
        )
        project_id = world["project_id"]
        applicant_headers = make_applicant_headers(world["household_id"])
        assert read_project(api, project_id)["provisional_total_incentive_cents"] == 800000

        #  S0 800000 + U 1000000 + F 0 == 1800000 against a limit of 1000000, so the
        #  allowed state share would land on exactly 0.
        validate_error(
            api.create_stacking_declaration(
                project_id,
                {
                    "utility_program_name": "Xcel Whole-Home Electrification",
                    "utility_rebate_cents": 1000000,
                    "federal_credit_claimed_cents": 200000,
                },
                applicant_headers,
            ),
            ApiErrorId.ERR_STACKING_LIMIT_EXCEEDED,
        )
        _rows, meta = validate_paginated(
            api.list_stacking_declarations(project_id, REVIEWER_HEADERS)
        )
        assert meta["total_count"] == 0
        assert read_project(api, project_id)["stacking_adjusted_state_incentive_cents"] is None

        declaration = validate_success(
            api.create_stacking_declaration(
                project_id,
                {
                    "utility_program_name": "Xcel Whole-Home Electrification",
                    "utility_rebate_cents": 500000,
                    "federal_credit_claimed_cents": 200000,
                },
                applicant_headers,
            ),
            expected_status=201,
        )
        assert declaration["status"] == StackingDeclarationStatus.ACTIVE
        assert declaration["computed_state_incentive_before_cents"] == 800000
        assert declaration["combined_benefit_limit_cents"] == 1000000
        assert declaration["allowed_state_incentive_cents"] == 500000
        assert declaration["allowed_federal_credit_cents"] == 0
        assert declaration["residual_overage_cents"] == 0
        assert declaration["federal_credit_claimed_cents"] == 200000

        after = read_project(api, project_id)
        assert after["stacking_adjusted_state_incentive_cents"] == 500000
        assert after["provisional_total_incentive_cents"] == 800000


class TestMeasureSetCoherence:
    def test_a_dropped_prerequisite_and_an_underpowered_panel_are_two_different_refusals(
        self, api
    ):
        """The capacity yardstick moves from the assessment to the installed panel.

        PRD §2.10: "every line whose catalog item declares a
        `prerequisite_measure_code` requires that measure to be present and
        qualified on the same project."

        PRD §2.10: "Every non-panel-upgrade measure line's
        `required_panel_capacity_amps` is no greater than the project's effective
        service capacity — the assessment's `effective_panel_amps` before
        installation, or `installed_panel_amps` once installation is reported →
        otherwise `ERR_PANEL_CAPACITY_INSUFFICIENT` (422)."

        Design: Corner/errors/unpowerable_line_and_orphaned_prerequisite_line_rejected
        """
        duct = build_duct_payload(
            unit_incentive_cents=150000,
            measure_cap_cents=150000,
            combined_cap_group=CombinedCapGroup.NONE,
        )
        world = build_world(
            api,
            stage="assessment",
            catalog=[build_hvac_heat_pump_payload(), duct],
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HP_DUCT, 1, 200000),
            ],
        )
        household_id = world["household_id"]
        contractor_id = world["contractor_id"]
        assessment_id = world["assessment_id"]
        verification_id = world["income_verification"]["id"]
        contractor_headers = make_contractor_headers(contractor_id)

        rows = read_eligible_measures(api, assessment_id)
        assert len(rows) == 2
        for row in rows:
            assert row["qualified"] is True
            assert row["disqualification_reason"] is None

        #  Dropping the prerequisite at project level re-opens a check the assessment passed.
        validate_error(
            api.create_rebate_project(
                build_project_payload(
                    household_id,
                    assessment_id,
                    contractor_id,
                    verification_id,
                    [build_project_measure(MEASURE_HP_DUCT, 1, 200000)],
                    estimated_project_cost_cents=200000,
                ),
                contractor_headers,
            ),
            ApiErrorId.ERR_PREREQUISITE_MEASURE_MISSING,
        )

        project = create_project(
            api,
            household_id,
            assessment_id,
            contractor_id,
            verification_id,
            [
                build_project_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_project_measure(MEASURE_HP_DUCT, 1, 200000),
            ],
            estimated_project_cost_cents=1200000,
        )
        project_id = project["id"]
        assert project["provisional_total_incentive_cents"] == 950000

        submit_project(api, project_id, contractor_id)
        review_project(api, project_id)
        reservation = reserve_project(api, project_id, world["program_id"])
        assert reservation["reserved_amount_cents"] == 950000

        results = [
            build_measure_result(MEASURE_HP_HVAC, 1, 950000),
            build_measure_result(MEASURE_HP_DUCT, 1, 150000),
        ]
        validate_error(
            api.report_installation(
                project_id,
                build_installation_payload(
                    results, installed_panel_amps=150, actual_project_cost_cents=1100000
                ),
                contractor_headers,
            ),
            ApiErrorId.ERR_PANEL_CAPACITY_INSUFFICIENT,
        )
        refused = read_project(api, project_id)
        assert refused["status"] == ProjectStatus.RESERVED
        assert refused["installed_panel_amps"] is None

        installed = report_installation(
            api,
            project_id,
            contractor_id,
            results,
            installed_panel_amps=200,
            actual_project_cost_cents=1100000,
        )
        assert installed["status"] == ProjectStatus.INSTALLED
        assert installed["installed_panel_amps"] == 200
        #  The final variant does not run until post-installation verification.
        assert installed["final_total_incentive_cents"] is None
        assert read_reservation(api, reservation["id"])["reserved_amount_cents"] == 950000


class TestLifetimeCapGate:
    def test_a_fully_encumbered_household_cannot_open_a_second_reservation(self, api):
        """The cap is a lifetime entitlement, refused at reservation rather than clamped.

        PRD §2.10: "**Household cap not exhausted.** At reservation time
        `lifetime_cap_remaining_cents` is at least 1 → otherwise
        `ERR_HOUSEHOLD_CAP_EXHAUSTED` (422). Applies to
        `POST /rebate-projects/{id}/reservations`. A fully encumbered household
        cannot open a second reservation even though allocation would clamp the
        amount to zero anyway."

        PRD §3.5: "The available ceiling is the household's
        `lifetime_cap_remaining_cents` plus whatever this project has already
        encumbered for itself"

        Design: Corner/errors/second_reservation_for_a_fully_encumbered_household_rejected
        """
        insulation = build_insulation_payload(
            unit_incentive_cents=600000, measure_cap_cents=600000
        )
        world = build_world(
            api,
            stage="approved",
            catalog=[build_hvac_heat_pump_payload(), insulation],
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_ENV_INS, 1, 700000),
            ],
            project_measures=[
                build_project_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_project_measure(MEASURE_ENV_INS, 1, 700000),
            ],
        )
        program_id = world["program_id"]
        household_id = world["household_id"]
        contractor_id = world["contractor_id"]
        first_project = world["project_id"]

        #  800000 in HVAC_GROUP plus 600000 ungrouped is exactly the LOW-tier cap.
        assert read_project(api, first_project)["provisional_total_incentive_cents"] == 1400000
        first_reservation = reserve_project(api, first_project, program_id)
        assert first_reservation["reserved_amount_cents"] == DEFAULT_LOW_TIER_CAP_CENTS
        assert_household_cap(
            read_household(api, household_id),
            remaining=0,
            encumbered=DEFAULT_LOW_TIER_CAP_CENTS,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

        #  A second project is still perfectly creatable, but its Stage 3 ceiling is 0.
        second = create_project(
            api,
            household_id,
            world["assessment_id"],
            contractor_id,
            world["income_verification"]["id"],
            [build_project_measure(MEASURE_ENV_INS, 1, 700000)],
            estimated_project_cost_cents=700000,
        )
        second_id = second["id"]
        assert second["provisional_total_incentive_cents"] == 0
        assert find_measure_line(read_project_measures(api, second_id), MEASURE_ENV_INS)[
            "provisional_incentive_cents"
        ] == 0

        submit_project(api, second_id, contractor_id)
        review_project(api, second_id)
        validate_error(
            api.create_reservation(
                second_id,
                build_reservation_payload(program_version(api, program_id)),
                REVIEWER_TWO_HEADERS,
            ),
            ApiErrorId.ERR_HOUSEHOLD_CAP_EXHAUSTED,
        )

        _rows, meta = validate_paginated(
            api.list_reservations(REVIEWER_HEADERS, {"project_id": second_id})
        )
        assert meta["total_count"] == 0
        assert read_project(api, second_id)["status"] == ProjectStatus.APPROVED
        assert_program_buckets(
            read_program(api, program_id),
            available=48600000,
            reserved=DEFAULT_LOW_TIER_CAP_CENTS,
            committed=0,
        )
