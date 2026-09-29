"""Nested per-line minima, the floored group proration with its residual, and the single-pass stacking order."""

from test_helpers import (
    CombinedCapGroup,
    DEFAULT_GROUP_CAP_CENTS,
    DEFAULT_LOW_TIER_CAP_CENTS,
    DEFAULT_PANEL_UPGRADE_CAP_CENTS,
    IncomeTier,
    MEASURE_HPWH,
    MEASURE_HP_DUCT,
    MEASURE_HP_HVAC,
    MEASURE_PANEL_400A,
    MEASURE_STOVE,
    ProjectStatus,
    REVIEWER_HEADERS,
    ReservationStatus,
    StackingDeclarationStatus,
    assert_household_cap,
    assert_measure_codes_in_order,
    assert_program_buckets,
    assert_quote_line,
    assert_quote_totals_match_lines,
    build_assessment_measure,
    build_duct_payload,
    build_hvac_heat_pump_payload,
    build_induction_stove_payload,
    build_measure_result,
    build_panel_400a_payload,
    build_pass_result_payload,
    build_project_measure,
    build_project_payload,
    build_water_heater_payload,
    build_world,
    create_inspector,
    declare_stacking,
    find_measure_line,
    read_eligible_measures,
    read_household,
    read_program,
    read_project,
    read_project_measures,
    read_quote,
    read_reservation,
    record_result,
    report_installation,
    reserve_project,
    review_project,
    schedule_inspection,
    submit_project,
    validate_paginated,
    validate_success,
)


class TestNestedPerLineMinimum:
    def test_four_lines_of_one_project_are_each_bound_by_a_different_arm(self, api):
        """Measure cap, cost share, panel cap and quantity clamp each bind exactly once.

        PRD §3.5: "For one line at a time, the system computes a raw amount as the
        pinned unit incentive multiplied by the smaller of the line's quantity and its
        `pinned_max_quantity` — quantity above the pinned maximum is clamped, not
        rejected."

        PRD §3.5: "It computes a cost-share ceiling as the line's cost multiplied by the
        household's tier cost-share fraction, floored to whole cents."

        PRD §3.5: "The line amount is then the smallest of three values: the raw amount,
        the `pinned_measure_cap_cents`, and the cost-share ceiling."

        PRD §3.5: "If `pinned_is_panel_upgrade` is true, the line amount is further
        reduced to the smaller of itself and the program's `panel_upgrade_cap_cents`."

        PRD §3.4: "If any line whose item has `is_panel_upgrade` true survived Stage B,
        the effective capacity becomes the greater of the assessed capacity and the
        largest `upgraded_capacity_amps` among those surviving panel-upgrade lines."

        Design: Difficulty/combinatorial_formula/measure_line_nested_min_four_distinct_binding_arms
        """
        world = build_world(
            api,
            stage="assessment",
            program_overrides={"moderate_tier_cap_cents": 2000000},
            catalog=[
                build_hvac_heat_pump_payload(measure_cap_cents=700000),
                build_water_heater_payload(unit_incentive_cents=200000),
                build_panel_400a_payload(measure_cap_cents=950000),
                build_induction_stove_payload(measure_cap_cents=120000),
            ],
            household_overrides={"existing_panel_amps": 100},
            income_overrides={"annual_household_income_cents": 12000000},
            assessed_panel_amps=100,
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 2000000),
                build_assessment_measure(MEASURE_HPWH, 1, 300000),
                build_assessment_measure(MEASURE_PANEL_400A, 1, 2000000),
                build_assessment_measure(MEASURE_STOVE, 3, 400000),
            ],
        )

        #  120.0 percent of the size-adjusted median puts the household in MODERATE, so
        #  every cost-share ceiling below is half of the line's cost.
        household = read_household(api, world["household_id"])
        assert household["income_tier"] == IncomeTier.MODERATE
        assert household["rebate_cap_cents"] == 2000000

        #  The 400 A upgrade line raises the effective capacity from 100 A, which is what
        #  lets the 200 A heat pump and the 150 A range through the capacity gate.
        assessment = world["assessment"]
        assert assessment["effective_panel_amps"] == 400
        assert assessment["qualified_measure_count"] == 4
        assert assessment["estimated_total_incentive_cents"] == 1334000

        project = validate_success(
            api.create_rebate_project(
                build_project_payload(
                    world["household_id"],
                    world["assessment_id"],
                    world["contractor_id"],
                    world["income_verification"]["id"],
                    [
                        build_project_measure(MEASURE_HP_HVAC, 1, 2000000),
                        build_project_measure(MEASURE_HPWH, 1, 300000),
                        build_project_measure(MEASURE_PANEL_400A, 1, 2000000),
                        build_project_measure(MEASURE_STOVE, 3, 400000),
                    ],
                    estimated_project_cost_cents=4700000,
                ),
                world["contractor_headers"],
            ),
            expected_status=201,
        )
        project_id = project["id"]

        lines = read_project_measures(api, project_id)

        #  Arm 1 — the per-measure cap: raw 800000, cost share 1000000, cap 700000.
        assert find_measure_line(lines, MEASURE_HP_HVAC)["provisional_incentive_cents"] == 700000

        #  Arm 2 — the tier cost-share ceiling: raw 200000, cap 175000, floor(300000 *
        #  0.50) = 150000.
        assert find_measure_line(lines, MEASURE_HPWH)["provisional_incentive_cents"] == 150000

        #  Arm 3 — the program panel-upgrade cap, applied after the ordinary minimum has
        #  already settled on 900000.
        assert (
            find_measure_line(lines, MEASURE_PANEL_400A)["provisional_incentive_cents"]
            == DEFAULT_PANEL_UPGRADE_CAP_CENTS
        )

        #  Arm 4 — the quantity clamp: 3 becomes min(3, 1), so the raw amount is a single
        #  84000 unit. Ignoring the clamp would let the 120000 measure cap bind instead.
        assert find_measure_line(lines, MEASURE_STOVE)["provisional_incentive_cents"] == 84000

        assert read_project(api, project_id)["provisional_total_incentive_cents"] == 1334000

        #  No proration anywhere: every group sum and the 2000000 household cap are
        #  comfortably above what the four lines add up to.
        quote = read_quote(api, project_id)
        assert len(quote["lines"]) == 4
        assert_measure_codes_in_order(
            quote["lines"],
            [MEASURE_HP_HVAC, MEASURE_HPWH, MEASURE_PANEL_400A, MEASURE_STOVE],
        )
        assert_quote_line(quote, MEASURE_HP_HVAC, 800000, 1000000, 700000, 700000)
        assert_quote_line(quote, MEASURE_HPWH, 200000, 150000, 150000, 150000)
        assert_quote_line(quote, MEASURE_PANEL_400A, 900000, 1000000, 400000, 400000)
        assert_quote_line(quote, MEASURE_STOVE, 84000, 200000, 84000, 84000)
        assert quote["total_incentive_cents"] == 1334000
        assert quote["group_cap_applied"] is False
        assert quote["household_cap_applied"] is False
        assert_quote_totals_match_lines(quote)

    def test_a_quantity_over_the_maximum_is_clamped_and_the_panel_cap_never_raises_a_line(
        self, api
    ):
        """Cheap invoices make the cost-share arm bind on all four lines at once.

        PRD §3.5: "For one line at a time, the system computes a raw amount as the
        pinned unit incentive multiplied by the smaller of the line's quantity and its
        `pinned_max_quantity` — quantity above the pinned maximum is clamped, not
        rejected."

        PRD §3.5: "If `pinned_is_panel_upgrade` is true, the line amount is further
        reduced to the smaller of itself and the program's `panel_upgrade_cap_cents`."

        PRD §3.5: "Crucially, creation **pins** six values from the live catalog item
        onto the line: `pinned_unit_incentive_cents`, `pinned_measure_cap_cents`,
        `pinned_max_quantity`, `pinned_sort_order`, `pinned_combined_cap_group`, and
        `pinned_is_panel_upgrade`."

        PRD §3.5: "Each entry of `measures` is a `measure_code`, a `planned_quantity` of
        at least 1, and an `estimated_cost_cents` of zero or more."

        Design: Difficulty/combinatorial_formula/measure_line_nested_min_four_distinct_binding_arms
        """
        world = build_world(
            api,
            stage="assessment",
            program_overrides={"moderate_tier_cap_cents": 2000000},
            catalog=[
                build_hvac_heat_pump_payload(measure_cap_cents=700000),
                build_water_heater_payload(unit_incentive_cents=200000),
                build_panel_400a_payload(measure_cap_cents=950000),
                build_induction_stove_payload(measure_cap_cents=120000),
            ],
            household_overrides={"existing_panel_amps": 100},
            income_overrides={"annual_household_income_cents": 12000000},
            assessed_panel_amps=100,
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 2000000),
                build_assessment_measure(MEASURE_HPWH, 1, 300000),
                build_assessment_measure(MEASURE_PANEL_400A, 1, 2000000),
                build_assessment_measure(MEASURE_STOVE, 3, 400000),
            ],
        )

        #  A range quantity of 5 against a pinned maximum of 1 is accepted, not refused.
        project = validate_success(
            api.create_rebate_project(
                build_project_payload(
                    world["household_id"],
                    world["assessment_id"],
                    world["contractor_id"],
                    world["income_verification"]["id"],
                    [
                        build_project_measure(MEASURE_HP_HVAC, 1, 1000000),
                        build_project_measure(MEASURE_HPWH, 1, 100000),
                        build_project_measure(MEASURE_PANEL_400A, 1, 600000),
                        build_project_measure(MEASURE_STOVE, 5, 100000),
                    ],
                    estimated_project_cost_cents=1800000,
                ),
                world["contractor_headers"],
            ),
            expected_status=201,
        )
        project_id = project["id"]

        lines = read_project_measures(api, project_id)

        #  Half of each invoice now sits below every other arm: 500000, 50000, 300000 and
        #  50000 respectively.
        heat_pump = find_measure_line(lines, MEASURE_HP_HVAC)
        assert heat_pump["provisional_incentive_cents"] == 500000
        assert find_measure_line(lines, MEASURE_HPWH)["provisional_incentive_cents"] == 50000
        stove = find_measure_line(lines, MEASURE_STOVE)
        assert stove["planned_quantity"] == 5
        assert stove["pinned_max_quantity"] == 1
        assert stove["provisional_incentive_cents"] == 50000

        #  The panel cap is a ceiling, never a floor: 300000 stays 300000 even though the
        #  400000 panel cap is larger.
        panel = find_measure_line(lines, MEASURE_PANEL_400A)
        assert panel["pinned_is_panel_upgrade"] is True
        assert panel["pinned_unit_incentive_cents"] == 900000
        assert panel["pinned_measure_cap_cents"] == 950000
        assert panel["pinned_sort_order"] == 35
        assert panel["pinned_combined_cap_group"] == CombinedCapGroup.ELECTRICAL_GROUP
        assert panel["provisional_incentive_cents"] == 300000
        assert panel["provisional_incentive_cents"] < DEFAULT_PANEL_UPGRADE_CAP_CENTS

        assert heat_pump["pinned_unit_incentive_cents"] == 800000
        assert heat_pump["pinned_measure_cap_cents"] == 700000
        assert heat_pump["pinned_combined_cap_group"] == CombinedCapGroup.HVAC_GROUP
        assert heat_pump["pinned_is_panel_upgrade"] is False

        assert read_project(api, project_id)["provisional_total_incentive_cents"] == 900000

        quote = read_quote(api, project_id)
        assert_quote_line(quote, MEASURE_HP_HVAC, 800000, 500000, 500000, 500000)
        assert_quote_line(quote, MEASURE_HPWH, 200000, 50000, 50000, 50000)
        assert_quote_line(quote, MEASURE_PANEL_400A, 900000, 300000, 300000, 300000)
        assert_quote_line(quote, MEASURE_STOVE, 84000, 50000, 50000, 50000)
        assert quote["total_incentive_cents"] == 900000
        assert quote["group_cap_applied"] is False
        assert quote["household_cap_applied"] is False


class TestGroupCapProration:
    def test_the_group_cap_floors_the_first_line_and_hands_the_residual_to_the_last(self, api):
        """1050000 against an 800000 group cap splits 609523 / 190477, not 609523 / 190476.

        PRD §3.5: "Within a group, members are ordered by `pinned_sort_order` ascending
        and then `created_at` ascending, and their amounts are summed. If that sum is
        **strictly greater** than the program's `group_cap_cents` — a sum exactly equal
        to the cap does not prorate — then every member except the last in that order is
        reduced to its amount multiplied by the group cap divided by the sum, floored to
        whole cents, and the last member receives the group cap minus the sum of those
        floored members."

        PRD §3.5: "The project total is the sum of the resulting line amounts, which
        therefore equals the binding cap exactly whenever a cap bound. Applying the two
        stages in reverse order, or flooring every line including the last, produces a
        different per-line split and a total that falls short of the cap — both are
        wrong."

        PRD §3.5: "It accepts an optional `variant` selecting which computation to
        replay, defaulting to the provisional one, and returns the `project_id`, the
        `variant` it ran, a `lines` array, and the aggregates
        `group_capped_total_cents`, `household_cap_limit_cents`,
        `total_incentive_cents`, the booleans `group_cap_applied` and
        `household_cap_applied`, and `residual_cents_assigned_to_measure_code` naming
        the line that absorbed the residual."

        PRD §3.4: "Each qualified row's `estimated_incentive_cents` is that line's
        estimated incentive after the measure and cost-share ceilings and after cap
        allocation; a row that is not qualified carries 0."

        Design: Difficulty/combinatorial_formula/group_cap_proration_floors_all_but_last_line_and_assigns_residual
        """
        world = build_world(
            api,
            stage="assessment",
            catalog=[build_hvac_heat_pump_payload(), build_duct_payload()],
            assessed_panel_amps=200,
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HP_DUCT, 1, 300000),
            ],
        )

        #  The same proration already ran over the assessment's estimates.
        rows = read_eligible_measures(api, world["assessment_id"])
        assert find_measure_line(rows, MEASURE_HP_HVAC)["estimated_incentive_cents"] == 609523
        assert find_measure_line(rows, MEASURE_HP_DUCT)["estimated_incentive_cents"] == 190477
        assert world["assessment"]["estimated_total_incentive_cents"] == 800000

        project = validate_success(
            api.create_rebate_project(
                build_project_payload(
                    world["household_id"],
                    world["assessment_id"],
                    world["contractor_id"],
                    world["income_verification"]["id"],
                    [
                        build_project_measure(MEASURE_HP_HVAC, 1, 1000000),
                        build_project_measure(MEASURE_HP_DUCT, 1, 300000),
                    ],
                    estimated_project_cost_cents=1300000,
                ),
                world["contractor_headers"],
            ),
            expected_status=201,
        )
        project_id = project["id"]

        #  Stage 1 resolves 800000 and 250000; their 1050000 sum is strictly over the
        #  800000 group cap, so sort_order 10 is floored and sort_order 15 takes the rest.
        lines = read_project_measures(api, project_id)
        heat_pump = find_measure_line(lines, MEASURE_HP_HVAC)
        duct = find_measure_line(lines, MEASURE_HP_DUCT)
        assert heat_pump["pinned_sort_order"] == 10
        assert duct["pinned_sort_order"] == 15
        assert heat_pump["provisional_incentive_cents"] == 609523
        assert duct["provisional_incentive_cents"] == 190477
        assert (
            heat_pump["provisional_incentive_cents"] + duct["provisional_incentive_cents"]
            == DEFAULT_GROUP_CAP_CENTS
        )
        assert read_project(api, project_id)["provisional_total_incentive_cents"] == 800000

        quote = read_quote(api, project_id)
        assert_measure_codes_in_order(quote["lines"], [MEASURE_HP_HVAC, MEASURE_HP_DUCT])
        assert_quote_line(quote, MEASURE_HP_HVAC, 800000, 1000000, 800000, 609523)
        assert_quote_line(quote, MEASURE_HP_DUCT, 250000, 300000, 250000, 190477)
        assert quote["group_capped_total_cents"] == 800000
        assert quote["household_cap_limit_cents"] == DEFAULT_LOW_TIER_CAP_CENTS
        assert quote["total_incentive_cents"] == 800000
        assert quote["group_cap_applied"] is True
        assert quote["household_cap_applied"] is False
        assert quote["residual_cents_assigned_to_measure_code"] == MEASURE_HP_DUCT
        assert_quote_totals_match_lines(quote)

        #  Computing an allocation encumbers nothing at all.
        assert_household_cap(
            read_household(api, world["household_id"]),
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

    def test_the_prorated_total_is_the_money_the_reservation_actually_encumbers(self, api):
        """The residual cent is real: 800000 leaves the appropriation, not 799999.

        PRD §3.5: "The project total is the sum of the resulting line amounts, which
        therefore equals the binding cap exactly whenever a cap bound. Applying the two
        stages in reverse order, or flooring every line including the last, produces a
        different per-line split and a total that falls short of the cap — both are
        wrong."

        PRD §3.6: "Its `reserved_amount_cents` and its immutable
        `initial_reserved_amount_cents` are both set to the project's
        `provisional_total_incentive_cents`"

        PRD §3.6: "The same operation debits the program's `budget_available_cents` and
        credits its `budget_reserved_cents` by the reserved amount, incrementing the
        program's version; debits the household's `lifetime_cap_remaining_cents` and
        credits its `encumbered_cents` by the same amount, incrementing the household's
        version; and moves the project `APPROVED → RESERVED`, incrementing the project's
        version."

        Design: Difficulty/combinatorial_formula/group_cap_proration_floors_all_but_last_line_and_assigns_residual
        """
        world = build_world(
            api,
            stage="assessment",
            catalog=[build_hvac_heat_pump_payload(), build_duct_payload()],
            assessed_panel_amps=200,
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HP_DUCT, 1, 300000),
            ],
        )
        project = validate_success(
            api.create_rebate_project(
                build_project_payload(
                    world["household_id"],
                    world["assessment_id"],
                    world["contractor_id"],
                    world["income_verification"]["id"],
                    [
                        build_project_measure(MEASURE_HP_HVAC, 1, 1000000),
                        build_project_measure(MEASURE_HP_DUCT, 1, 300000),
                    ],
                    estimated_project_cost_cents=1300000,
                ),
                world["contractor_headers"],
            ),
            expected_status=201,
        )
        project_id = project["id"]
        assert project["provisional_total_incentive_cents"] == 800000

        submit_project(api, project_id, world["contractor_id"])
        review_project(api, project_id)
        reservation = reserve_project(api, project_id, world["program_id"])

        assert reservation["status"] == ReservationStatus.RESERVED
        assert reservation["reserved_amount_cents"] == 800000
        assert reservation["initial_reserved_amount_cents"] == 800000
        assert read_project(api, project_id)["status"] == ProjectStatus.RESERVED

        #  Both ledgers moved by the full prorated total, residual cent included.
        assert_program_buckets(
            read_program(api, world["program_id"]),
            available=49200000,
            reserved=800000,
            committed=0,
            clawed_back=0,
        )
        assert_household_cap(
            read_household(api, world["household_id"]),
            remaining=600000,
            encumbered=800000,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

        #  Reserving the money did not re-split the lines.
        lines = read_project_measures(api, project_id)
        assert find_measure_line(lines, MEASURE_HP_HVAC)["provisional_incentive_cents"] == 609523
        assert find_measure_line(lines, MEASURE_HP_DUCT)["provisional_incentive_cents"] == 190477
        assert read_reservation(api, reservation["id"])["reserved_amount_cents"] == 800000


class TestStackingSinglePassOrder:
    def test_the_federal_credit_is_recomputed_once_and_grows_leaving_a_recorded_overage(
        self, api
    ):
        """One pass: F 60000, trim to 640000, F again 78000, and 18000 overage survives.

        PRD §3.9: "The stacking limit is evaluated in a pinned order, exactly once, with
        no iteration:"

        PRD §3.9: "A first federal credit figure is computed as the program's
        `federal_credit_pct` multiplied by the cost basis less the state incentive less
        the utility contribution, floored to whole cents, clamped up to 0 if that came
        out negative, and then clamped down to the program's `federal_credit_cap_cents`."

        PRD §3.9: "If the total benefit exceeds the limit, the allowed state incentive
        becomes the state incentive less the excess, clamped up to 0; otherwise the
        allowed state incentive is the state incentive unchanged. The result is stored as
        `allowed_state_incentive_cents`."

        PRD §3.9: "The federal credit is then recomputed **exactly once** from the
        reduced state incentive: the program's `federal_credit_pct` multiplied by the
        cost basis less the allowed state incentive less the utility contribution,
        floored, clamped up to 0, and clamped down to `federal_credit_cap_cents`. The
        result is stored as `allowed_federal_credit_cents`. Because reducing the state
        incentive raises the net cost, this recomputed credit can legitimately come out
        larger than the first figure, and the system deliberately does **not** loop back
        to step 6 to squeeze it again."

        PRD §3.9: "Whatever overage survives is recorded rather than iterated away:
        `residual_overage_cents` is the allowed state incentive plus the utility
        contribution plus the recomputed federal credit, less the limit, clamped up to
        0."

        PRD §3.9: "The allowed state incentive is also written onto the project as
        `stacking_adjusted_state_incentive_cents`, and the project's version increments."

        Design: Difficulty/combinatorial_formula/stacking_single_pass_order_recomputes_federal_credit_exactly_once
        """
        world = build_world(
            api,
            stage="project",
            program_overrides={
                "federal_credit_cap_cents": 1000000,
                "max_combined_benefit_pct": 0.80,
            },
            catalog=[build_hvac_heat_pump_payload(measure_cap_cents=700000)],
            assessment_measures=[build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
            project_measures=[build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
            project_overrides={"estimated_project_cost_cents": 1000000},
        )
        project_id = world["project_id"]
        assert world["project"]["provisional_total_incentive_cents"] == 700000
        assert world["project"]["actual_project_cost_cents"] is None

        declaration = declare_stacking(api, project_id, world["household_id"], 100000)

        #  Basis 1000000 (the estimate, since no invoice exists yet), S0 700000 from the
        #  provisional total, U 100000. F1 = floor(0.30 * 200000) = 60000, so the total
        #  benefit 860000 overshoots the 800000 limit by 60000.
        assert declaration["computed_state_incentive_before_cents"] == 700000
        assert declaration["combined_benefit_limit_cents"] == 800000
        assert declaration["allowed_state_incentive_cents"] == 640000

        #  F is recomputed once from 640000: floor(0.30 * 260000) = 78000, larger than
        #  the 60000 first pass, and the 18000 that still overshoots is simply recorded.
        assert declaration["allowed_federal_credit_cents"] == 78000
        assert declaration["allowed_federal_credit_cents"] > 60000
        assert declaration["residual_overage_cents"] == 18000
        assert (
            declaration["allowed_state_incentive_cents"]
            + 100000
            + declaration["allowed_federal_credit_cents"]
            - declaration["combined_benefit_limit_cents"]
            == declaration["residual_overage_cents"]
        )
        assert declaration["status"] == StackingDeclarationStatus.ACTIVE

        project = read_project(api, project_id)
        assert project["stacking_adjusted_state_incentive_cents"] == 640000
        assert project["provisional_total_incentive_cents"] == 700000

    def test_verification_re_runs_the_same_single_pass_over_the_invoiced_basis(self, api):
        """A new basis of 900000 re-runs the eight steps once: 590000, 63000, 33000.

        PRD §3.9: "The cost basis is the project's `actual_project_cost_cents` when that
        has been recorded, and its `estimated_project_cost_cents` otherwise."

        PRD §3.9: "The state incentive going in is the project's
        `final_total_incentive_cents` when that is not null, and its
        `provisional_total_incentive_cents` otherwise. This value is stored as the
        declaration's `computed_state_incentive_before_cents`."

        PRD §3.9: "The total benefit is the state incentive plus the utility contribution
        plus that federal credit figure. The limit is the cost basis multiplied by the
        program's `max_combined_benefit_pct`, floored to whole cents, and is stored as
        the declaration's `combined_benefit_limit_cents`."

        PRD §3.9: "The same evaluation is re-run whenever an inspection result changes
        `final_total_incentive_cents` while an `ACTIVE` declaration exists, so the
        declaration and the project stay consistent as the final total moves."

        Design: Difficulty/combinatorial_formula/stacking_single_pass_order_recomputes_federal_credit_exactly_once
        """
        world = build_world(
            api,
            stage="approved",
            program_overrides={
                "federal_credit_cap_cents": 1000000,
                "max_combined_benefit_pct": 0.80,
            },
            catalog=[build_hvac_heat_pump_payload(measure_cap_cents=700000)],
            assessment_measures=[build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
            project_measures=[build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
            project_overrides={"estimated_project_cost_cents": 1000000},
        )
        project_id = world["project_id"]
        contractor_id = world["contractor_id"]

        first = declare_stacking(api, project_id, world["household_id"], 100000)
        assert first["combined_benefit_limit_cents"] == 800000
        assert first["allowed_state_incentive_cents"] == 640000
        assert first["allowed_federal_credit_cents"] == 78000

        reserve_project(api, project_id, world["program_id"])
        report_installation(
            api,
            project_id,
            contractor_id,
            [build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
            actual_project_cost_cents=900000,
        )

        #  Recording the invoice is not one of the re-evaluation triggers.
        filed_rows, _filed_meta = validate_paginated(
            api.list_stacking_declarations(project_id, REVIEWER_HEADERS)
        )
        after_install = filed_rows[0]
        assert after_install["combined_benefit_limit_cents"] == 800000
        assert after_install["allowed_state_incentive_cents"] == 640000
        assert after_install["allowed_federal_credit_cents"] == 78000

        inspector = create_inspector(api, world["program_id"])
        inspection = schedule_inspection(api, project_id, inspector["id"])
        record_result(api, inspection["id"], inspector["id"], build_pass_result_payload())

        project = read_project(api, project_id)
        assert project["final_total_incentive_cents"] == 700000
        assert project["actual_project_cost_cents"] == 900000

        #  Basis 900000 now: limit floor(900000 * 0.80) = 720000, F1 = floor(0.30 *
        #  100000) = 30000, total benefit 830000, excess 110000, S1 = 590000, and F is
        #  recomputed exactly once as floor(0.30 * 210000) = 63000.
        rows, meta = validate_paginated(
            api.list_stacking_declarations(
                project_id, REVIEWER_HEADERS, {"status": StackingDeclarationStatus.ACTIVE}
            )
        )
        assert meta["total_count"] == 1
        recomputed = rows[0]
        assert recomputed["id"] == first["id"]
        assert recomputed["status"] == StackingDeclarationStatus.ACTIVE
        assert recomputed["computed_state_incentive_before_cents"] == 700000
        assert recomputed["combined_benefit_limit_cents"] == 720000
        assert recomputed["allowed_state_incentive_cents"] == 590000
        assert recomputed["allowed_federal_credit_cents"] == 63000
        assert recomputed["residual_overage_cents"] == 33000
        assert project["stacking_adjusted_state_incentive_cents"] == 590000
