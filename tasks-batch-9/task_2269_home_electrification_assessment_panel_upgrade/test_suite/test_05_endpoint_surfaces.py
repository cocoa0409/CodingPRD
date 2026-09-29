"""Creation and listing surfaces, action endpoints, bulk writes and computed reads."""

from test_helpers import (
    ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    AssessmentStatus,
    ContractorStatus,
    DEFAULT_CREW_CAPACITY,
    DEFAULT_LOW_TIER_CAP_CENTS,
    DisqualificationReason,
    InspectionStatus,
    InstallStatus,
    MEASURE_ENV_INS,
    MEASURE_HP_HVAC,
    MEASURE_HPWH,
    ProjectStatus,
    QuoteVariant,
    REVIEWER_HEADERS,
    REVIEWER_ONE,
    ReservationStatus,
    VerificationStatus,
    assert_household_cap,
    assert_pagination_meta,
    assert_program_buckets,
    build_assessment_measure,
    build_contractor_payload,
    build_hvac_heat_pump_payload,
    build_inspection_payload,
    build_installation_payload,
    build_insulation_payload,
    build_measure_result,
    build_retirement_payload,
    build_water_heater_payload,
    build_world,
    create_assessment,
    create_contractor,
    create_inspector,
    create_open_program,
    decide_enrollment,
    find_by,
    find_measure_line,
    make_contractor_headers,
    read_assessment,
    read_contractor,
    read_eligible_measures,
    read_household,
    read_inspection,
    read_program,
    read_project,
    read_project_measures,
    read_quote,
    read_reservation,
    report_installation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestContractorSurface:
    def test_contractors_are_created_read_and_listed_within_their_own_program(self, api):
        """Create, read and a program-scoped list, with a defaulted crew capacity.

        PRD §3.3: "Installers apply for enrollment by naming their `program_id`,
        `business_name`, `license_number`, a `license_expires_on` date in
        `YYYY-MM-DD` form, an `insurance_expires_on` date in the same form, and
        optionally a `crew_capacity` of at least 1, defaulting to 2 — the number of
        install windows the contractor may have open on overlapping calendar
        dates."

        PRD §3.3: "An application is created in `PENDING_ENROLLMENT` with
        `quality_score_rolling` at 100, `completed_inspection_count` at 0, and
        `suspension_reason` null."

        PRD §3.1: "the contractors list accepts a `status` filter"

        Design: Corner/endpoints/contractor_create_read_and_program_scoped_listing
        """
        program_a = create_open_program(api, name="HEEHRA 2026 Program A")
        program_b = create_open_program(api, name="HEEHRA 2026 Program B", state_code="NM")

        alpha = validate_success(
            api.create_contractor(
                build_contractor_payload(
                    program_a["id"],
                    business_name="Alpha Electrification",
                    license_number="MC-1201",
                    insurance_expires_on="2027-05-31",
                    crew_capacity=3,
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert alpha["crew_capacity"] == 3

        #  Omit `crew_capacity` entirely so the declared default is what answers.
        beta_payload = build_contractor_payload(
            program_a["id"],
            business_name="Beta Electrification",
            license_number="MC-1202",
        )
        del beta_payload["crew_capacity"]
        beta = validate_success(
            api.create_contractor(beta_payload, ADMIN_HEADERS), expected_status=201
        )
        assert beta["crew_capacity"] == DEFAULT_CREW_CAPACITY
        assert beta["status"] == ContractorStatus.PENDING_ENROLLMENT
        assert beta["quality_score_rolling"] == 100
        assert beta["completed_inspection_count"] == 0
        assert beta["suspension_reason"] is None

        gamma = create_contractor(
            api,
            program_b["id"],
            business_name="Gamma Electrification",
            license_number="MC-1203",
        )

        decide_enrollment(api, alpha["id"])
        enrolled = read_contractor(api, alpha["id"])
        assert enrolled["status"] == ContractorStatus.ENROLLED_ACTIVE
        assert enrolled["quality_score_rolling"] == 100
        assert enrolled["completed_inspection_count"] == 0
        #  One create plus one enrollment decision.
        assert enrolled["version"] == 2

        rows, meta = validate_paginated(
            api.list_program_contractors(program_a["id"], REVIEWER_HEADERS)
        )
        assert_pagination_meta(meta, total_count=2, has_more=False)
        assert {row["id"] for row in rows} == {alpha["id"], beta["id"]}

        active_rows, active_meta = validate_paginated(
            api.list_program_contractors(
                program_a["id"], REVIEWER_HEADERS, {"status": ContractorStatus.ENROLLED_ACTIVE}
            )
        )
        assert_pagination_meta(active_meta, total_count=1)
        assert active_rows[0]["id"] == alpha["id"]

        page_rows, page_meta = validate_paginated(
            api.list_program_contractors(
                program_a["id"], REVIEWER_HEADERS, {"limit": 1, "offset": 1}
            )
        )
        assert len(page_rows) == 1
        assert_pagination_meta(page_meta, total_count=2, limit=1, offset=1, has_more=False)

        other_rows, other_meta = validate_paginated(
            api.list_program_contractors(program_b["id"], REVIEWER_HEADERS)
        )
        assert_pagination_meta(other_meta, total_count=1)
        assert other_rows[0]["id"] == gamma["id"]


class TestCatalogRetirement:
    def test_retirement_disqualifies_new_assessments_and_leaves_pinned_lines_alone(self, api):
        """Retirement is forward-only: pinned project lines keep their rates.

        PRD §3.1: "An administrator retires an item — optionally recording a
        `retirement_note` — which sets `active` to false and increments that item's
        version. Retirement deliberately touches no existing project measure line:
        already-pinned rates survive untouched, while new assessments now disqualify
        the measure with the reason `RETIRED_CATALOG_ITEM`."

        PRD §2.10: "a catalog item identifier that matches no item of the addressed
        program yields `ERR_MEASURE_CATALOG_ITEM_NOT_FOUND` (404)."

        Design: Corner/endpoints/catalog_retirement_affects_new_assessments_not_pinned_projects
        """
        world = build_world(api, stage="project", catalog=[build_hvac_heat_pump_payload()])
        program_id = world["program_id"]
        item = world["catalog"][MEASURE_HP_HVAC]

        validate_error(
            api.retire_catalog_item(
                program_id,
                NON_EXISTENT_UUID,
                ADMIN_HEADERS,
                build_retirement_payload(retirement_note="Typo in the item id"),
            ),
            ApiErrorId.ERR_MEASURE_CATALOG_ITEM_NOT_FOUND,
        )
        items, _meta = validate_paginated(api.list_catalog_items(program_id, REVIEWER_HEADERS))
        assert find_by(items, "measure_code", MEASURE_HP_HVAC)["active"] is True

        retired = validate_success(
            api.retire_catalog_item(
                program_id,
                item["id"],
                ADMIN_HEADERS,
                build_retirement_payload(),
            )
        )
        assert retired["active"] is False
        assert retired["version"] == item["version"] + 1

        _inactive, inactive_meta = validate_paginated(
            api.list_catalog_items(program_id, REVIEWER_HEADERS, {"active": "false"})
        )
        assert_pagination_meta(inactive_meta, total_count=1)
        _active, active_meta = validate_paginated(
            api.list_catalog_items(program_id, REVIEWER_HEADERS, {"active": "true"})
        )
        assert_pagination_meta(active_meta, total_count=0)

        #  A brand-new assessment now disqualifies the retired measure.
        second = create_assessment(
            api,
            world["household_id"],
            world["contractor_id"],
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
        )
        rows = read_eligible_measures(api, second["id"])
        assert len(rows) == 1
        assert rows[0]["qualified"] is False
        assert rows[0]["disqualification_reason"] == DisqualificationReason.RETIRED_CATALOG_ITEM
        assert read_assessment(api, second["id"])["qualified_measure_count"] == 0
        assert read_assessment(api, world["assessment_id"])["status"] == AssessmentStatus.SUPERSEDED

        #  The project that already pinned the item is untouched.
        line = find_measure_line(read_project_measures(api, world["project_id"]), MEASURE_HP_HVAC)
        assert line["pinned_unit_incentive_cents"] == 800000
        assert line["pinned_measure_cap_cents"] == 800000
        assert line["provisional_incentive_cents"] == 800000
        assert read_project(api, world["project_id"])["provisional_total_incentive_cents"] == 800000


class TestInstallationBulkWrite:
    def test_an_unknown_measure_code_rejects_the_whole_installation_report(self, api):
        """The bulk write is all-or-nothing across `measure_results`.

        PRD §3.7: "Each entry of `measure_results` names a `measure_code` together
        with the `verified_quantity` and `actual_cost_cents` for that line. A code
        that is not one of the project's own lines is refused with
        `ERR_MEASURE_NOT_ON_PROJECT`."

        PRD §3.7: "On success the project records `actual_project_cost_cents`,
        `install_start_date`, `install_end_date`, and `installed_panel_amps`; each
        reported line moves `install_status` from `PLANNED` to `INSTALLED` and
        stores its `actual_cost_cents`, with each line's version incremented"

        Design: Corner/endpoints/installation_report_rejects_an_unknown_measure_code_atomically
        """
        world = build_world(
            api,
            stage="reserved",
            catalog=[build_hvac_heat_pump_payload(), build_water_heater_payload()],
            assessment_measures=[build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
        )
        project_id = world["project_id"]
        contractor_headers = make_contractor_headers(world["contractor_id"])

        #  The first entry is a real project line; the second is only in the catalog.
        validate_error(
            api.report_installation(
                project_id,
                build_installation_payload(
                    [
                        build_measure_result(MEASURE_HP_HVAC, 1, 700000),
                        build_measure_result(MEASURE_HPWH, 1, 400000),
                    ],
                    actual_project_cost_cents=1100000,
                ),
                contractor_headers,
            ),
            ApiErrorId.ERR_MEASURE_NOT_ON_PROJECT,
        )

        untouched = find_measure_line(read_project_measures(api, project_id), MEASURE_HP_HVAC)
        assert untouched["install_status"] == InstallStatus.PLANNED
        assert untouched["verification_status"] == VerificationStatus.PENDING
        assert untouched["verified_quantity"] is None
        assert untouched["actual_cost_cents"] is None

        held = read_project(api, project_id)
        assert held["status"] == ProjectStatus.RESERVED
        assert held["install_start_date"] is None
        assert held["install_end_date"] is None
        assert held["actual_project_cost_cents"] is None

        installed = report_installation(
            api,
            project_id,
            world["contractor_id"],
            [build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
            actual_project_cost_cents=700000,
        )
        assert installed["status"] == ProjectStatus.INSTALLED
        assert installed["actual_project_cost_cents"] == 700000
        applied = find_measure_line(read_project_measures(api, project_id), MEASURE_HP_HVAC)
        assert applied["install_status"] == InstallStatus.INSTALLED
        assert applied["verified_quantity"] == 1
        assert applied["actual_cost_cents"] == 700000

        #  Installation never touches the encumbrance.
        assert read_reservation(api, world["reservation_id"])["reserved_amount_cents"] == 800000


class TestIncentiveQuoteRead:
    def test_the_incentive_quote_derives_the_stored_totals_without_writing(self, api):
        """Three replays of the waterfall agree with each other and change nothing.

        PRD §3.5: "Because both cap stages are invisible in the stored totals
        alone, a computed read replays the whole waterfall over the project's
        current lines and exposes each stage without changing any state."

        PRD §3.5: "Each entry of `lines` reports a `measure_code`, its
        `raw_incentive_cents`, its `cost_share_cap_cents`, its `capped_line_cents`
        after the per-line ceilings, and its `allocated_cents` after both cap
        stages, in `pinned_sort_order` ascending then `created_at` ascending order."

        Design: Corner/endpoints/incentive_quote_is_a_side_effect_free_computed_read
        """
        measures = [
            build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
            build_assessment_measure(MEASURE_ENV_INS, 1, 200000),
        ]
        world = build_world(
            api,
            stage="project",
            catalog=[build_hvac_heat_pump_payload(), build_insulation_payload()],
            assessment_measures=measures,
        )
        project_id = world["project_id"]

        before = read_project(api, project_id)
        assert before["provisional_total_incentive_cents"] == 900000

        default_quote = read_quote(api, project_id)
        assert default_quote["project_id"] == project_id
        assert default_quote["variant"] == QuoteVariant.PROVISIONAL
        assert default_quote["total_incentive_cents"] == 900000
        assert default_quote["group_capped_total_cents"] == 900000
        assert default_quote["household_cap_limit_cents"] == DEFAULT_LOW_TIER_CAP_CENTS
        assert default_quote["group_cap_applied"] is False
        assert default_quote["household_cap_applied"] is False
        assert default_quote["residual_cents_assigned_to_measure_code"] is None
        assert [line["measure_code"] for line in default_quote["lines"]] == [
            MEASURE_HP_HVAC,
            MEASURE_ENV_INS,
        ]
        assert find_measure_line(default_quote["lines"], MEASURE_HP_HVAC)["allocated_cents"] == 800000
        assert find_measure_line(default_quote["lines"], MEASURE_ENV_INS)["allocated_cents"] == 100000

        #  The quote never disagrees with the persisted per-line figures.
        stored_lines = read_project_measures(api, project_id)
        for line in default_quote["lines"]:
            persisted = find_measure_line(stored_lines, line["measure_code"])
            assert line["allocated_cents"] == persisted["provisional_incentive_cents"]
        assert default_quote["total_incentive_cents"] == before["provisional_total_incentive_cents"]

        explicit_quote = read_quote(api, project_id, QuoteVariant.PROVISIONAL)
        assert explicit_quote == default_quote
        third_quote = read_quote(api, project_id)
        assert third_quote == default_quote

        after = read_project(api, project_id)
        assert after["version"] == before["version"]
        assert after["status"] == ProjectStatus.DRAFT
        for line in read_project_measures(api, project_id):
            assert line["install_status"] == InstallStatus.PLANNED
            assert line["verification_status"] == VerificationStatus.PENDING


class TestExpirySweepBoundary:
    def test_the_sweep_is_a_no_op_before_expiry_and_releases_at_the_exact_instant(self, api):
        """`expires_at <= now` is inclusive, and an expired row is never re-released.

        PRD §3.6: "A `ProgramAdmin` runs the expiry sweep for a program, which
        collects that program's reservations in status `RESERVED` whose `expires_at`
        is less than or equal to the logical clock — the comparison is inclusive, so
        a reservation expiring exactly now does expire"

        PRD §3.6: "Reservations in `COMMITTED`, `RELEASED`, `EXPIRED`, or
        `CLAWED_BACK` are skipped, and a `SUSPENDED` or `CLOSED` program is still
        swept."

        Design: Corner/endpoints/sweep_skips_not_yet_due_reservations_then_expires_at_the_inclusive_boundary
        """
        world = build_world(api, stage="reserved", catalog=[build_hvac_heat_pump_payload()])
        program_id = world["program_id"]
        project_id = world["project_id"]
        reservation_id = world["reservation_id"]

        #  Reserved at 2026-08-01 with the default 120-day term.
        assert world["reservation"]["expires_at"].startswith("2026-11-29")
        assert_program_buckets(
            read_program(api, program_id), available=49200000, reserved=800000, committed=0
        )

        set_clock(api, "2026-11-28T23:59:00Z")
        early = validate_success(
            api.sweep_program(program_id, ADMIN_HEADERS)
        )
        assert early["swept_reservation_count"] == 0
        assert early["released_cents"] == 0
        assert early["expired_project_ids"] == []
        assert early["program_budget_available_cents"] == 49200000
        assert read_reservation(api, reservation_id)["status"] == ReservationStatus.RESERVED
        assert read_project(api, project_id)["status"] == ProjectStatus.RESERVED

        set_clock(api, "2026-11-29T00:00:00Z")
        due = validate_success(
            api.sweep_program(program_id, ADMIN_HEADERS)
        )
        assert due["swept_reservation_count"] == 1
        assert due["released_cents"] == 800000
        assert due["expired_project_ids"] == [project_id]
        assert due["program_budget_available_cents"] == 50000000

        assert read_reservation(api, reservation_id)["status"] == ReservationStatus.EXPIRED
        assert read_project(api, project_id)["status"] == ProjectStatus.EXPIRED
        line = find_measure_line(read_project_measures(api, project_id), MEASURE_HP_HVAC)
        assert line["install_status"] == InstallStatus.VOID
        assert_household_cap(
            read_household(api, world["household_id"]),
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

        #  An already-expired reservation is no longer due, so nothing double-releases.
        again = validate_success(
            api.sweep_program(program_id, ADMIN_HEADERS)
        )
        assert again["swept_reservation_count"] == 0
        assert again["released_cents"] == 0
        assert_program_buckets(
            read_program(api, program_id), available=50000000, reserved=0, committed=0
        )


class TestInspectionLinking:
    def test_scheduling_an_inspection_resolves_both_body_references(self, api):
        """Either missing reference is a 404 naming that entity, and neither writes a row.

        PRD §2.10: "**Body-referenced entities exist and belong to the same
        program.** This covers `program_id`, `household_id`, `contractor_id`,
        `inspector_id`, `assessment_id`, `income_verification_id`, `project_id`, and
        every `measure_code` that must resolve to a catalog item of that program."

        PRD §3.8: "The inspection is created in `SCHEDULED` with
        `scheduled_by_user_id` stamped, `result_recorded_at` and
        `recorded_by_user_id` null, `deficiency_count` at 0,
        `deficiency_severity_max` at 0, `rejected_measure_codes` an empty array, and
        `notes` null."

        Design: Corner/endpoints/inspection_requires_both_the_project_and_the_inspector_to_exist
        """
        world = build_world(
            api,
            stage="installed",
            catalog=[build_hvac_heat_pump_payload()],
            measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
        )
        project_id = world["project_id"]
        inspector = create_inspector(api, world["program_id"])

        validate_error(
            api.create_inspection(
                build_inspection_payload(NON_EXISTENT_UUID, inspector["id"]), REVIEWER_HEADERS
            ),
            ApiErrorId.ERR_PROJECT_NOT_FOUND,
        )
        validate_error(
            api.create_inspection(
                build_inspection_payload(project_id, NON_EXISTENT_UUID), REVIEWER_HEADERS
            ),
            ApiErrorId.ERR_INSPECTOR_NOT_FOUND,
        )

        created = validate_success(
            api.create_inspection(
                build_inspection_payload(project_id, inspector["id"]), REVIEWER_HEADERS
            ),
            expected_status=201,
        )
        assert created["status"] == InspectionStatus.SCHEDULED
        assert created["project_id"] == project_id
        assert created["inspector_id"] == inspector["id"]
        assert created["scheduled_by_user_id"] == REVIEWER_ONE
        assert created["result_recorded_at"] is None
        assert created["recorded_by_user_id"] is None
        assert created["deficiency_count"] == 0
        assert created["deficiency_severity_max"] == 0
        assert created["rejected_measure_codes"] == []
        assert created["notes"] is None

        #  Neither refused call left a row behind, and the link reads from both sides.
        _by_project, project_meta = validate_paginated(
            api.list_inspections(REVIEWER_HEADERS, {"project_id": project_id})
        )
        assert_pagination_meta(project_meta, total_count=1)
        by_inspector, inspector_meta = validate_paginated(
            api.list_inspections(
                REVIEWER_HEADERS,
                {"inspector_id": inspector["id"], "status": InspectionStatus.SCHEDULED},
            )
        )
        assert_pagination_meta(inspector_meta, total_count=1)
        assert by_inspector[0]["id"] == created["id"]
        assert read_inspection(api, created["id"])["status"] == InspectionStatus.SCHEDULED

        #  Scheduling is not itself a project transition.
        assert read_project(api, project_id)["status"] == ProjectStatus.INSTALLED
