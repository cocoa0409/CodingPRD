"""Ladder ordering, fiscal boundaries, credential currency and staged qualification."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    AssessmentStatus,
    ContractorStatus,
    DEFAULT_LOW_TIER_CAP_CENTS,
    DEFAULT_STANDARD_TIER_CAP_CENTS,
    DisqualificationReason,
    IncomeTier,
    MEASURE_ENV_INS,
    MEASURE_HP_DUCT,
    MEASURE_HP_HVAC,
    MEASURE_HPWH,
    ProjectStatus,
    REVIEWER_HEADERS,
    REVIEWER_TWO_HEADERS,
    ReservationStatus,
    add_catalog,
    assert_household_cap,
    assert_pagination_meta,
    assert_program_buckets,
    build_assessment_measure,
    build_assessment_payload,
    build_duct_payload,
    build_hvac_heat_pump_payload,
    build_insulation_payload,
    build_project_measure,
    build_project_payload,
    build_reservation_payload,
    build_water_heater_payload,
    build_world,
    create_approved_assessment,
    create_assessment,
    create_enrolled_contractor,
    create_open_program,
    create_project,
    create_verified_household,
    decide_assessment,
    find_by,
    find_measure_line,
    household_version,
    make_contractor_headers,
    program_version,
    read_assessment,
    read_contractor,
    read_eligible_measures,
    read_household,
    read_program,
    read_project,
    read_project_measures,
    reserve_project,
    review_project,
    set_clock,
    submit_project,
    validate_error,
    validate_paginated,
)


class TestPerLineEligibility:
    def test_a_catalogued_measure_the_assessment_never_proposed_is_still_ineligible(self, api):
        """Rung 15 reads the assessment's qualified set, not the program catalog.

        PRD §2.10: "**Per-line eligibility and uniqueness.** Every requested
        `measure_code` appears on the linked assessment as an eligible-measure row
        whose `qualified` flag is true, and no `measure_code` repeats within one
        request."

        PRD §2.10: "A `measure_code` that exists only in another program's catalog
        is treated as absent and yields `ERR_MEASURE_CODE_NOT_IN_CATALOG` (404)."

        Design: Corner/validations/project_measure_absent_from_the_assessment_rejected
        """
        program = create_open_program(api, name="HEEHRA 2026 Not Eligible")
        add_catalog(
            api,
            program["id"],
            [build_hvac_heat_pump_payload(), build_water_heater_payload()],
        )
        verified = create_verified_household(api, program["id"])
        household = verified["household"]
        contractor = create_enrolled_contractor(api, program["id"])

        #  The assessment proposes the heat pump alone.
        assessment = create_approved_assessment(
            api,
            household["id"],
            contractor["id"],
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
        )

        validate_error(
            api.create_rebate_project(
                build_project_payload(
                    household["id"],
                    assessment["id"],
                    contractor["id"],
                    verified["income_verification"]["id"],
                    [
                        build_project_measure(MEASURE_HP_HVAC, 1, 1000000),
                        build_project_measure(MEASURE_HPWH, 1, 400000),
                    ],
                    estimated_project_cost_cents=1400000,
                ),
                make_contractor_headers(contractor["id"]),
            ),
            ApiErrorId.ERR_MEASURE_NOT_ELIGIBLE,
        )

        #  The water heater is a live catalog item, so this is not a catalog miss.
        _items, catalog_meta = validate_paginated(
            api.list_catalog_items(program["id"], REVIEWER_HEADERS)
        )
        assert_pagination_meta(catalog_meta, total_count=2)

        #  The create is atomic across all lines, so nothing was written.
        _rows, project_meta = validate_paginated(
            api.list_rebate_projects(REVIEWER_HEADERS, {"household_id": household["id"]})
        )
        assert_pagination_meta(project_meta, total_count=0)

        eligible = read_eligible_measures(api, assessment["id"])
        assert len(eligible) == 1
        assert eligible[0]["measure_code"] == MEASURE_HP_HVAC

        project = create_project(
            api,
            household["id"],
            assessment["id"],
            contractor["id"],
            verified["income_verification"]["id"],
            [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
            estimated_project_cost_cents=1000000,
        )
        assert project["provisional_total_incentive_cents"] == 800000
        assert len(read_project_measures(api, project["id"])) == 1


class TestFiscalGates:
    def test_a_reservation_equal_to_the_remaining_appropriation_is_admitted(self, api):
        """The appropriation rung compares with `at least`, so equality passes.

        PRD §2.10: "**Appropriation available.** `budget_available_cents` is at
        least the amount to be reserved → otherwise `ERR_PROGRAM_BUDGET_EXHAUSTED`
        (422)."

        PRD §3.6: "Its `reserved_amount_cents` and its immutable
        `initial_reserved_amount_cents` are both set to the project's
        `provisional_total_incentive_cents`"

        Design: Corner/validations/reservation_succeeds_when_budget_exactly_equals_the_request
        """
        world = build_world(
            api,
            stage="approved",
            program_overrides={"name": "HEEHRA 2026 Exact Budget", "budget_total_cents": 800000},
            catalog=[build_hvac_heat_pump_payload()],
        )
        program_id = world["program_id"]

        before = read_program(api, program_id)
        assert before["budget_available_cents"] == 800000
        assert world["project"]["provisional_total_incentive_cents"] == 800000

        reservation = reserve_project(api, world["project_id"], program_id)
        assert reservation["status"] == ReservationStatus.RESERVED
        assert reservation["reserved_amount_cents"] == 800000
        assert reservation["initial_reserved_amount_cents"] == 800000
        assert reservation["extension_count"] == 0
        assert reservation["extension_days_granted"] == 0

        #  The appropriation is exactly consumed rather than overdrawn.
        assert_program_buckets(
            read_program(api, program_id), available=0, reserved=800000, committed=0
        )
        assert_household_cap(
            read_household(api, world["household_id"]),
            remaining=600000,
            encumbered=800000,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )
        assert read_project(api, world["project_id"])["status"] == ProjectStatus.RESERVED

    def test_budget_exhaustion_is_measured_against_the_residual_not_the_appropriation(self, api):
        """Two individually affordable projects cannot both be reserved.

        PRD §2.10: "**Appropriation available.** `budget_available_cents` is at
        least the amount to be reserved → otherwise `ERR_PROGRAM_BUDGET_EXHAUSTED`
        (422). Applies to `POST /rebate-projects/{id}/reservations`."

        PRD §2.7: "After every mutation that touches any of these, the invariant
        holds that `budget_total_cents` equals the sum of `budget_available_cents`,
        `budget_reserved_cents`, and `budget_committed_cents`."

        Design: Corner/validations/budget_exhaustion_is_aggregate_not_per_project
        """
        world = build_world(
            api,
            stage="approved",
            program_overrides={
                "name": "HEEHRA 2026 Aggregate Budget",
                "budget_total_cents": 1000000,
            },
            catalog=[build_hvac_heat_pump_payload()],
            household_overrides={
                "applicant_name": "First Claim",
                "email": "first@example.com",
                "service_address_line1": "130 First Ave",
            },
        )
        program_id = world["program_id"]
        contractor_id = world["contractor_id"]

        second = create_verified_household(
            api,
            program_id,
            applicant_name="Second Claim",
            email="second@example.com",
            service_address_line1="140 Second Ave",
        )
        second_household = second["household"]
        second_assessment = create_approved_assessment(
            api,
            second_household["id"],
            contractor_id,
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
        )
        second_project = create_project(
            api,
            second_household["id"],
            second_assessment["id"],
            contractor_id,
            second["income_verification"]["id"],
            [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
            estimated_project_cost_cents=1000000,
        )
        submit_project(api, second_project["id"], contractor_id)
        review_project(api, second_project["id"])

        first_reservation = reserve_project(api, world["project_id"], program_id)
        assert first_reservation["reserved_amount_cents"] == 800000
        assert read_program(api, program_id)["budget_available_cents"] == 200000

        #  A freshly read version, so nothing but the appropriation can refuse it.
        validate_error(
            api.create_reservation(
                second_project["id"],
                build_reservation_payload(program_version(api, program_id)),
                REVIEWER_TWO_HEADERS,
            ),
            ApiErrorId.ERR_PROGRAM_BUDGET_EXHAUSTED,
        )

        _rows, meta = validate_paginated(
            api.list_reservations(REVIEWER_HEADERS, {"program_id": program_id})
        )
        assert_pagination_meta(meta, total_count=1)
        assert read_project(api, second_project["id"])["status"] == ProjectStatus.APPROVED

        program = read_program(api, program_id)
        assert_program_buckets(program, available=200000, reserved=800000, committed=0)
        assert program["budget_total_cents"] == (
            program["budget_available_cents"]
            + program["budget_reserved_cents"]
            + program["budget_committed_cents"]
        )
        assert_household_cap(
            read_household(api, second_household["id"]),
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )


class TestLadderOrdering:
    def test_pagination_arguments_are_judged_before_the_path_is_resolved(self, api):
        """Rung 4 answers first even though the addressed program does not exist.

        PRD §2.10: "**Pagination arguments.** When supplied, `limit` lies within 1
        through 100 inclusive and `offset` is at least 0 → otherwise
        `ERR_INVALID_PAGINATION` (400). Applies to every list endpoint, and is
        checked separately from the rest of the request so the caller can tell the
        two apart."

        PRD §2.10: "**Path entities exist,** resolved strictly left to right along
        the path."

        Design: Corner/validations/pagination_validation_precedes_path_existence_check
        """
        program = create_open_program(api, name="HEEHRA 2026 Ordering")

        #  Both rungs are violated at once; the lower-numbered one answers.
        validate_error(
            api.list_catalog_items(NON_EXISTENT_UUID, REVIEWER_HEADERS, {"limit": 0}),
            ApiErrorId.ERR_INVALID_PAGINATION,
        )

        #  Repairing only the pagination exposes the path violation underneath.
        validate_error(
            api.list_catalog_items(NON_EXISTENT_UUID, REVIEWER_HEADERS, {"limit": 20}),
            ApiErrorId.ERR_PROGRAM_NOT_FOUND,
        )

        #  And the pagination violation was real on a program that does exist.
        validate_error(
            api.list_catalog_items(program["id"], REVIEWER_HEADERS, {"limit": 0}),
            ApiErrorId.ERR_INVALID_PAGINATION,
        )

        rows, meta = validate_paginated(
            api.list_catalog_items(program["id"], REVIEWER_HEADERS, {"limit": 20})
        )
        assert rows == []
        assert_pagination_meta(meta, total_count=0, limit=20, offset=0)


class TestCredentialCurrency:
    def test_a_license_covers_its_own_expiry_date_and_nothing_after_it(self, api):
        """Rung 11 compares the credential date against the logical clock's date.

        PRD §2.10: "**Installer fitness.** The contractor attached to the operation
        is `ENROLLED_ACTIVE`, and both `license_expires_on` and
        `insurance_expires_on` fall on or after the logical clock's date."

        PRD §2.5: "Setting the clock changes no entity — it only changes what every
        subsequent read of \"now\" returns."

        Design: Corner/validations/expired_contractor_license_blocks_assessment_only_after_the_expiry_date
        """
        set_clock(api, "2026-08-01T00:00:00Z")
        program = create_open_program(api, name="HEEHRA 2026 Credentials")
        add_catalog(api, program["id"], [build_hvac_heat_pump_payload()])
        verified = create_verified_household(api, program["id"])
        household_id = verified["household"]["id"]
        contractor = create_enrolled_contractor(
            api,
            program["id"],
            business_name="Lapsing License Mechanical",
            license_number="MC-9601",
            license_expires_on="2026-08-31",
        )
        assert contractor["status"] == ContractorStatus.ENROLLED_ACTIVE

        measures = [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)]

        #  On the expiry date itself the licence is still current.
        set_clock(api, "2026-08-31T12:00:00Z")
        version_before = household_version(api, household_id)
        accepted = create_assessment(api, household_id, contractor["id"], measures)
        assert accepted["status"] == AssessmentStatus.PENDING_REVIEW
        version_after = household_version(api, household_id)
        assert version_after == version_before + 1

        #  One day later the byte-identical request is refused.
        set_clock(api, "2026-09-01T00:00:00Z")
        validate_error(
            api.create_assessment(
                build_assessment_payload(
                    household_id, contractor["id"], version_after, measures
                ),
                make_contractor_headers(contractor["id"]),
            ),
            ApiErrorId.ERR_CONTRACTOR_CREDENTIAL_EXPIRED,
        )

        #  Expiry is a validation, not a state change, and it ran no side effects.
        lapsed = read_contractor(api, contractor["id"])
        assert lapsed["status"] == ContractorStatus.ENROLLED_ACTIVE
        assert lapsed["suspension_reason"] is None
        assert read_assessment(api, accepted["id"])["status"] == AssessmentStatus.PENDING_REVIEW
        assert household_version(api, household_id) == version_after


class TestStagedQualification:
    def test_the_standard_tier_flag_is_inert_outside_the_standard_tier(self, api):
        """One catalog item, two households, two different Stage A verdicts.

        PRD §3.4: "Otherwise, if the household's `income_tier` is `STANDARD` and
        the item's `standard_tier_eligible` is false, the line is disqualified with
        `TIER_INELIGIBLE`."

        PRD §3.5: "It computes a cost-share ceiling as the line's cost multiplied
        by the household's tier cost-share fraction, floored to whole cents."

        Design: Corner/validations/standard_tier_eligibility_flag_gates_only_standard_tier_households
        """
        program = create_open_program(api, name="HEEHRA 2026 Tier Flag")
        add_catalog(
            api,
            program["id"],
            [build_hvac_heat_pump_payload(), build_insulation_payload()],
        )
        contractor = create_enrolled_contractor(api, program["id"])

        standard = create_verified_household(
            api,
            program["id"],
            income_overrides={
                "annual_household_income_cents": 20000000,
                "county_median_income_cents": 10000000,
                "household_size_attested": 4,
            },
            applicant_name="Standard Tier",
            email="std@example.com",
            service_address_line1="150 Standard St",
        )
        standard_household = standard["household"]
        assert standard_household["ami_percent"] == 200.0
        assert standard_household["income_tier"] == IncomeTier.STANDARD
        assert standard_household["rebate_cap_cents"] == DEFAULT_STANDARD_TIER_CAP_CENTS

        low = create_verified_household(
            api,
            program["id"],
            applicant_name="Low Tier",
            email="low@example.com",
            service_address_line1="160 Low St",
        )
        low_household = low["household"]
        assert low_household["income_tier"] == IncomeTier.LOW

        proposed = [
            build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
            build_assessment_measure(MEASURE_ENV_INS, 1, 200000),
        ]

        standard_assessment = create_assessment(
            api, standard_household["id"], contractor["id"], proposed
        )
        standard_rows = read_eligible_measures(api, standard_assessment["id"])
        assert len(standard_rows) == 2
        blocked = find_by(standard_rows, "measure_code", MEASURE_HP_HVAC)
        assert blocked["qualified"] is False
        assert blocked["disqualification_reason"] == DisqualificationReason.TIER_INELIGIBLE
        assert blocked["evaluation_order"] == 1
        allowed = find_by(standard_rows, "measure_code", MEASURE_ENV_INS)
        assert allowed["qualified"] is True
        assert allowed["disqualification_reason"] is None
        assert allowed["evaluation_order"] == 2

        assert read_assessment(api, standard_assessment["id"])["qualified_measure_count"] == 1
        approved = decide_assessment(api, standard_assessment["id"])
        assert approved["status"] == AssessmentStatus.APPROVED

        standard_project = create_project(
            api,
            standard_household["id"],
            standard_assessment["id"],
            contractor["id"],
            standard["income_verification"]["id"],
            [build_project_measure(MEASURE_ENV_INS, 1, 200000)],
            estimated_project_cost_cents=200000,
        )
        #  min(100000, 100000, floor(200000 * 0.30)) == 60000 at the standard share.
        line = find_measure_line(
            read_project_measures(api, standard_project["id"]), MEASURE_ENV_INS
        )
        assert line["provisional_incentive_cents"] == 60000
        assert standard_project["provisional_total_incentive_cents"] == 60000

        low_assessment = create_assessment(api, low_household["id"], contractor["id"], proposed)
        low_rows = read_eligible_measures(api, low_assessment["id"])
        assert len(low_rows) == 2
        assert all(row["qualified"] is True for row in low_rows)
        assert all(row["disqualification_reason"] is None for row in low_rows)

        #  The catalog item itself never changed between the two evaluations.
        items, _meta = validate_paginated(
            api.list_catalog_items(program["id"], REVIEWER_HEADERS)
        )
        assert find_by(items, "measure_code", MEASURE_HP_HVAC)["standard_tier_eligible"] is False

    def test_the_prerequisite_stage_reads_the_capacity_stage_verdict(self, api):
        """A prerequisite that is proposed but capacity-disqualified is still missing.

        PRD §3.4: "**Stage E — prerequisites by business key.** For each line still
        surviving whose item declares a non-null `prerequisite_measure_code`, if
        that code is absent from this assessment, or if its line did not survive
        Stage D, the dependent line is disqualified with `PREREQUISITE_MISSING`."

        PRD §3.4: "Approving moves the assessment `PENDING_REVIEW → APPROVED`,
        permitted only when `qualified_measure_count` is at least 1 and the
        assessment's contractor is `ENROLLED_ACTIVE`; an assessment with no
        qualified lines is refused with `ERR_NO_ELIGIBLE_MEASURES`."

        Design: Corner/validations/prerequisite_check_consumes_the_capacity_check_result
        """
        program = create_open_program(api, name="HEEHRA 2026 Cascading Checks")
        add_catalog(
            api, program["id"], [build_hvac_heat_pump_payload(), build_duct_payload()]
        )
        verified = create_verified_household(
            api,
            program["id"],
            applicant_name="Small Panel",
            email="smallpanel@example.com",
            service_address_line1="170 Small St",
            existing_panel_amps=100,
        )
        contractor = create_enrolled_contractor(api, program["id"])

        #  No panel-upgrade line is proposed, so the effective capacity stays 100 A.
        assessment = create_assessment(
            api,
            verified["household"]["id"],
            contractor["id"],
            [
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HP_DUCT, 1, 300000),
            ],
            assessed_panel_amps=100,
        )
        assert assessment["status"] == AssessmentStatus.PENDING_REVIEW
        assert assessment["effective_panel_amps"] == 100

        rows = read_eligible_measures(api, assessment["id"])
        anchor = find_by(rows, "measure_code", MEASURE_HP_HVAC)
        assert anchor["evaluation_order"] == 1
        assert anchor["qualified"] is False
        assert (
            anchor["disqualification_reason"]
            == DisqualificationReason.PANEL_CAPACITY_INSUFFICIENT
        )
        dependent = find_by(rows, "measure_code", MEASURE_HP_DUCT)
        assert dependent["evaluation_order"] == 2
        assert dependent["qualified"] is False
        #  Its own 100 A requirement is met, so this is not a capacity failure.
        assert (
            dependent["disqualification_reason"]
            == DisqualificationReason.PREREQUISITE_MISSING
        )

        stored = read_assessment(api, assessment["id"])
        assert stored["qualified_measure_count"] == 0
        assert stored["estimated_total_incentive_cents"] == 0

        validate_error(
            api.review_assessment(
                assessment["id"], {"decision": "APPROVE"}, REVIEWER_HEADERS
            ),
            ApiErrorId.ERR_NO_ELIGIBLE_MEASURES,
        )
        assert read_assessment(api, assessment["id"])["status"] == AssessmentStatus.PENDING_REVIEW
