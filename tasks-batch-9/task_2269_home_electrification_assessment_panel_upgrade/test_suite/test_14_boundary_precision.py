"""Four metrics at their exact edges: the AMI decimal, the group cap, the extension window, the conditional floor."""

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_AMI_LOW_THRESHOLD_PCT,
    DEFAULT_EXTENSION_WINDOW_DAYS,
    DEFAULT_GROUP_CAP_CENTS,
    DEFAULT_LOW_TIER_CAP_CENTS,
    DEFAULT_MAX_EXTENSION_DAYS,
    DEFAULT_MODERATE_TIER_CAP_CENTS,
    DEFAULT_RESERVATION_TTL_DAYS,
    IncomeTier,
    InspectionStatus,
    MEASURE_HP_DUCT,
    MEASURE_HP_HVAC,
    ProjectReviewDecision,
    ProjectStatus,
    QuoteVariant,
    assert_household_cap,
    assert_quote_line,
    assert_quote_totals_match_lines,
    build_assessment_measure,
    build_conditional_pass_result_payload,
    build_duct_payload,
    build_extension_payload,
    build_hvac_heat_pump_payload,
    build_measure_result,
    build_project_measure,
    build_world,
    create_open_program,
    create_project,
    create_verified_household,
    find_measure_line,
    read_household,
    read_project,
    read_project_measures,
    read_quote,
    read_reservation,
    record_result,
    review_project,
    set_clock,
    submit_project,
    validate_error,
    validate_success,
)


class TestAmiPercentRoundedBeforeTheTierTest:
    def test_four_thousand_cents_vanish_in_the_rounding_and_five_thousand_do_not(self, api):
        """80.04 rounds down and stays LOW; 80.05 rounds half up and falls to MODERATE.

        PRD §2.6: "**Percent-of-income arithmetic** rounds half up to one decimal place,
        and it rounds **before** any threshold comparison is made. The tier test therefore
        reads the rounded percentage, never the unrounded quotient."

        PRD §3.2: "Round that raw percentage half up to one decimal place. This rounded
        value is what gets stored and what the tier test reads — the comparison is never
        made against the unrounded quotient."

        PRD §3.2: "If the rounded percentage is less than or equal to the program's
        `ami_low_threshold_pct`, the tier is `LOW`. Otherwise, if it is less than or equal
        to `ami_moderate_threshold_pct`, the tier is `MODERATE`. Otherwise the tier is
        `STANDARD`."

        PRD §3.2: "The decision writes `computed_ami_percent`, `assigned_income_tier`, and
        `assigned_cap_cents` onto the verification, along with `verified_by_user_id` and a
        `verified_at` stamped from the logical clock. It also writes the household's
        `ami_percent`, `income_tier`, and `rebate_cap_cents`, and sets
        `lifetime_cap_remaining_cents` to the assigned cap minus whatever the household
        already has in `encumbered_cents`."

        Design: Difficulty/boundary_precision_check/ami_percent_rounds_to_one_decimal_before_tier_comparison
        """
        program = create_open_program(api)
        assert program["ami_low_threshold_pct"] == pytest.approx(
            DEFAULT_AMI_LOW_THRESHOLD_PCT, abs=0.01
        )

        exact = create_verified_household(
            api,
            program["id"],
            income_overrides={"annual_household_income_cents": 8000000},
            applicant_name="Boundary One",
            email="b1@example.com",
            service_address_line1="1 Birch St",
        )
        just_under = create_verified_household(
            api,
            program["id"],
            income_overrides={"annual_household_income_cents": 8004000},
            applicant_name="Boundary Two",
            email="b2@example.com",
            service_address_line1="2 Birch St",
        )
        just_over = create_verified_household(
            api,
            program["id"],
            income_overrides={"annual_household_income_cents": 8005000},
            applicant_name="Boundary Three",
            email="b3@example.com",
            service_address_line1="3 Birch St",
        )

        #  Exactly at the threshold: the comparison is inclusive.
        assert exact["income_verification"]["computed_ami_percent"] == pytest.approx(
            80.0, abs=0.01
        )
        assert exact["income_verification"]["assigned_income_tier"] == IncomeTier.LOW
        assert exact["income_verification"]["assigned_cap_cents"] == DEFAULT_LOW_TIER_CAP_CENTS

        #  Raw 80.04 rounds down to 80.0, so 4000 cents of income change nothing.
        assert just_under["income_verification"]["computed_ami_percent"] == pytest.approx(
            80.0, abs=0.01
        )
        assert just_under["income_verification"]["assigned_income_tier"] == IncomeTier.LOW
        assert (
            just_under["income_verification"]["assigned_cap_cents"] == DEFAULT_LOW_TIER_CAP_CENTS
        )

        #  Raw 80.05 rounds half up to 80.1, which is no longer <= 80.0.
        assert just_over["income_verification"]["computed_ami_percent"] == pytest.approx(
            80.1, abs=0.01
        )
        assert just_over["income_verification"]["assigned_income_tier"] == IncomeTier.MODERATE
        assert (
            just_over["income_verification"]["assigned_cap_cents"]
            == DEFAULT_MODERATE_TIER_CAP_CENTS
        )

        #  1000 cents of income separate the last two households and 600000 cents of cap.
        low_household = read_household(api, just_under["household"]["id"])
        moderate_household = read_household(api, just_over["household"]["id"])
        assert low_household["income_tier"] == IncomeTier.LOW
        assert moderate_household["income_tier"] == IncomeTier.MODERATE
        assert (
            low_household["rebate_cap_cents"] - moderate_household["rebate_cap_cents"] == 600000
        )
        assert_household_cap(
            low_household,
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )
        assert_household_cap(
            moderate_household,
            remaining=DEFAULT_MODERATE_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_MODERATE_TIER_CAP_CENTS,
        )

    def test_the_size_factor_adjusts_the_median_and_comes_from_the_attested_count(self, api):
        """One income, two attested counts, two tiers — and the household's own size is ignored.

        PRD §3.2: "A decision of `VERIFY` moves it `SUBMITTED → VERIFIED` and runs the tier
        assignment, which is computed from **exactly** the packet being verified — the
        household's own `household_size` field is never used, only
        `household_size_attested`:"

        PRD §3.2: "Take the attested occupant count, and if it exceeds 7 treat it as 7. Look
        up the size adjustment factor for that count: 0.70 for one occupant, 0.80 for two,
        0.90 for three, 1.00 for four, 1.08 for five, 1.16 for six, and 1.24 for seven or
        more."

        PRD §3.2: "Multiply `county_median_income_cents` by that factor to obtain the
        size-adjusted median income."

        PRD §3.2: "Divide `annual_household_income_cents` by the size-adjusted median and
        multiply by 100 to obtain the raw percent of area median income."

        Design: Difficulty/boundary_precision_check/ami_percent_rounds_to_one_decimal_before_tier_comparison
        """
        program = create_open_program(api)

        #  9280000 against the 1.16-adjusted median 11600000 is exactly 80.0 percent.
        attests_six = create_verified_household(
            api,
            program["id"],
            income_overrides={
                "annual_household_income_cents": 9280000,
                "household_size_attested": 6,
            },
            applicant_name="Boundary Four",
            email="b4@example.com",
            service_address_line1="4 Birch St",
            household_size=4,
        )
        assert attests_six["income_verification"]["computed_ami_percent"] == pytest.approx(
            80.0, abs=0.01
        )
        assert attests_six["income_verification"]["assigned_income_tier"] == IncomeTier.LOW
        assert (
            attests_six["income_verification"]["assigned_cap_cents"] == DEFAULT_LOW_TIER_CAP_CENTS
        )

        #  The identical income attested for four occupants divides by the unadjusted
        #  median and lands at 92.8 percent instead.
        attests_four = create_verified_household(
            api,
            program["id"],
            income_overrides={
                "annual_household_income_cents": 9280000,
                "household_size_attested": 4,
            },
            applicant_name="Boundary Five",
            email="b5@example.com",
            service_address_line1="5 Birch St",
            household_size=6,
        )
        assert attests_four["income_verification"]["computed_ami_percent"] == pytest.approx(
            92.8, abs=0.01
        )
        assert attests_four["income_verification"]["assigned_income_tier"] == IncomeTier.MODERATE
        assert (
            attests_four["income_verification"]["assigned_cap_cents"]
            == DEFAULT_MODERATE_TIER_CAP_CENTS
        )

        #  The stored household sizes are the mirror image of the attested ones, so the
        #  tier can only have come from the packet.
        low_household = read_household(api, attests_six["household"]["id"])
        moderate_household = read_household(api, attests_four["household"]["id"])
        assert low_household["household_size"] == 4
        assert low_household["income_tier"] == IncomeTier.LOW
        assert low_household["ami_percent"] == pytest.approx(80.0, abs=0.01)
        assert moderate_household["household_size"] == 6
        assert moderate_household["income_tier"] == IncomeTier.MODERATE
        assert moderate_household["ami_percent"] == pytest.approx(92.8, abs=0.01)


class TestGroupCapStrictInequality:
    def test_a_group_sum_at_the_cap_is_untouched_and_one_cent_over_prorates(self, api):
        """Two projects one cent apart: same total, different split and flag.

        PRD §3.5: "*Stage 2* applies the combined-measure cap group by group, taking the
        groups in the fixed order `HVAC_GROUP`, then `WATER_GROUP`, then `APPLIANCE_GROUP`,
        then `ELECTRICAL_GROUP`. Lines whose `pinned_combined_cap_group` is `NONE` are never
        prorated. Within a group, members are ordered by `pinned_sort_order` ascending and
        then `created_at` ascending, and their amounts are summed. If that sum is **strictly
        greater** than the program's `group_cap_cents` — a sum exactly equal to the cap does
        not prorate — then every member except the last in that order is reduced to its
        amount multiplied by the group cap divided by the sum, floored to whole cents, and
        the last member receives the group cap minus the sum of those floored members."

        PRD §3.5: "and returns the `project_id`, the `variant` it ran, a `lines` array, and
        the aggregates `group_capped_total_cents`, `household_cap_limit_cents`,
        `total_incentive_cents`, the booleans `group_cap_applied` and
        `household_cap_applied`, and `residual_cents_assigned_to_measure_code` naming the
        line that absorbed the residual."

        PRD §3.5: "The project total is the sum of the resulting line amounts, which
        therefore equals the binding cap exactly whenever a cap bound."

        Design: Difficulty/boundary_precision_check/group_cap_strict_inequality_at_one_cent_over
        """
        world = build_world(
            api,
            stage="assessment",
            catalog=[build_hvac_heat_pump_payload(), build_duct_payload()],
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 550000),
                build_assessment_measure(MEASURE_HP_DUCT, 1, 250000),
            ],
        )
        assert world["program"]["group_cap_cents"] == DEFAULT_GROUP_CAP_CENTS

        #  Exactly at the cap: 550000 + 250000 == 800000.
        at_cap = create_project(
            api,
            world["household_id"],
            world["assessment_id"],
            world["contractor_id"],
            world["income_verification"]["id"],
            [
                build_project_measure(MEASURE_HP_HVAC, 1, 550000),
                build_project_measure(MEASURE_HP_DUCT, 1, 250000),
            ],
            estimated_project_cost_cents=800000,
        )
        at_cap_lines = read_project_measures(api, at_cap["id"])
        assert [line["provisional_incentive_cents"] for line in at_cap_lines] == [550000, 250000]
        assert at_cap["provisional_total_incentive_cents"] == DEFAULT_GROUP_CAP_CENTS
        at_cap_quote = read_quote(api, at_cap["id"])
        assert at_cap_quote["group_cap_applied"] is False
        assert at_cap_quote["residual_cents_assigned_to_measure_code"] is None
        assert at_cap_quote["group_capped_total_cents"] == DEFAULT_GROUP_CAP_CENTS
        assert_quote_line(at_cap_quote, MEASURE_HP_HVAC, 800000, 550000, 550000, 550000)
        assert_quote_line(at_cap_quote, MEASURE_HP_DUCT, 250000, 250000, 250000, 250000)

        #  One cent over: 550001 + 250000 == 800001 and the proration engages.
        over_cap = create_project(
            api,
            world["household_id"],
            world["assessment_id"],
            world["contractor_id"],
            world["income_verification"]["id"],
            [
                build_project_measure(MEASURE_HP_HVAC, 1, 550001),
                build_project_measure(MEASURE_HP_DUCT, 1, 250000),
            ],
            estimated_project_cost_cents=800001,
        )
        over_cap_lines = read_project_measures(api, over_cap["id"])
        assert [line["provisional_incentive_cents"] for line in over_cap_lines] == [
            550000,
            250000,
        ]
        assert over_cap["provisional_total_incentive_cents"] == DEFAULT_GROUP_CAP_CENTS
        over_cap_quote = read_quote(api, over_cap["id"])
        assert over_cap_quote["group_cap_applied"] is True
        assert over_cap_quote["residual_cents_assigned_to_measure_code"] == MEASURE_HP_DUCT
        assert_quote_line(over_cap_quote, MEASURE_HP_HVAC, 800000, 550001, 550001, 550000)
        assert_quote_line(over_cap_quote, MEASURE_HP_DUCT, 250000, 250000, 250000, 250000)
        assert_quote_totals_match_lines(over_cap_quote)

        #  The stored total is identical on both sides of the boundary.
        assert (
            at_cap["provisional_total_incentive_cents"]
            == over_cap["provisional_total_incentive_cents"]
        )

    def test_the_same_edge_is_crossed_by_a_resubmitted_measure_set(self, api):
        """The re-run allocation moves one cent of one line and raises the flag.

        PRD §3.5: "*Stage 2* applies the combined-measure cap group by group, taking the
        groups in the fixed order `HVAC_GROUP`, then `WATER_GROUP`, then `APPLIANCE_GROUP`,
        then `ELECTRICAL_GROUP`. Lines whose `pinned_combined_cap_group` is `NONE` are never
        prorated. Within a group, members are ordered by `pinned_sort_order` ascending and
        then `created_at` ascending, and their amounts are summed. If that sum is **strictly
        greater** than the program's `group_cap_cents` — a sum exactly equal to the cap does
        not prorate — then every member except the last in that order is reduced to its
        amount multiplied by the group cap divided by the sum, floored to whole cents, and
        the last member receives the group cap minus the sum of those floored members."

        PRD §3.5: "Resubmitting a project that was returned incomplete moves it `INCOMPLETE
        → SUBMITTED` under the same ownership rule, increments `submission_count`, clears
        the stored `incomplete_reason`, and re-runs the provisional allocation over every
        line against the household's *current* `lifetime_cap_remaining_cents`. When
        `measures` is supplied, the line set is replaced and the pinned rates are re-pinned
        from the catalog as it stands at that moment."

        Design: Difficulty/boundary_precision_check/group_cap_strict_inequality_at_one_cent_over
        """
        world = build_world(
            api,
            stage="submitted",
            catalog=[build_hvac_heat_pump_payload(), build_duct_payload()],
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 550000),
                build_assessment_measure(MEASURE_HP_DUCT, 1, 250000),
            ],
        )
        project_id = world["project_id"]

        #  The submitted set sits exactly on the cap.
        assert world["project"]["provisional_total_incentive_cents"] == DEFAULT_GROUP_CAP_CENTS
        first_quote = read_quote(api, project_id)
        assert first_quote["group_cap_applied"] is False
        assert first_quote["residual_cents_assigned_to_measure_code"] is None

        returned = review_project(
            api,
            project_id,
            ProjectReviewDecision.RETURN_INCOMPLETE,
            incomplete_reason="Confirm the duct scope pricing",
        )
        assert returned["status"] == ProjectStatus.INCOMPLETE

        resubmitted = submit_project(
            api,
            project_id,
            world["contractor_id"],
            {
                "measures": [
                    build_project_measure(MEASURE_HP_HVAC, 1, 550001),
                    build_project_measure(MEASURE_HP_DUCT, 1, 250000),
                ],
                "estimated_project_cost_cents": 800001,
            },
        )
        assert resubmitted["status"] == ProjectStatus.SUBMITTED
        assert resubmitted["provisional_total_incentive_cents"] == DEFAULT_GROUP_CAP_CENTS

        #  One cent more of estimated cost, one cent less on the first line.
        lines = read_project_measures(api, project_id)
        assert [line["provisional_incentive_cents"] for line in lines] == [550000, 250000]
        assert find_measure_line(lines, MEASURE_HP_HVAC)["estimated_cost_cents"] == 550001
        second_quote = read_quote(api, project_id)
        assert second_quote["group_cap_applied"] is True
        assert second_quote["residual_cents_assigned_to_measure_code"] == MEASURE_HP_DUCT
        assert_quote_line(second_quote, MEASURE_HP_HVAC, 800000, 550001, 550001, 550000)
        assert_quote_line(second_quote, MEASURE_HP_DUCT, 250000, 250000, 250000, 250000)


class TestExtensionWindowAndDayLimits:
    def test_one_second_early_is_refused_and_the_opening_instant_is_accepted(self, api):
        """The window's lower bound is inclusive, and the day limit is checked after it.

        PRD §3.6: "The extension window opens at the reservation's `expires_at` minus the
        program's `extension_window_days` days, and the lower bound is inclusive: a request
        made exactly `extension_window_days` before expiry is accepted, while a request made
        earlier than that is refused with `ERR_EXTENSION_WINDOW_NOT_OPEN`."

        PRD §3.6: "The reservation's `extension_count` must be strictly below the program's
        `max_extensions_per_reservation`, or the request is refused with
        `ERR_EXTENSION_LIMIT_REACHED`. And `additional_days` must be at least 1 and no more
        than the program's `max_extension_days`, or the request is refused with
        `ERR_EXTENSION_DAYS_EXCEEDED`. The three checks run in exactly that inner order."

        PRD §3.6: "A granted extension pushes `expires_at` out by `additional_days` days,
        increments `extension_count` by one, adds `additional_days` to
        `extension_days_granted`, and increments the reservation's version."

        PRD §2.6: "Before any clock manipulation the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time."

        Design: Difficulty/boundary_precision_check/extension_window_inclusive_lower_bound_and_day_limits
        """
        world = build_world(api, stage="reserved", catalog=[build_hvac_heat_pump_payload()])
        reservation_id = world["reservation_id"]
        contractor_headers = world["contractor_headers"]
        assert world["program"]["reservation_ttl_days"] == DEFAULT_RESERVATION_TTL_DAYS
        assert world["program"]["extension_window_days"] == DEFAULT_EXTENSION_WINDOW_DAYS
        assert world["program"]["max_extension_days"] == DEFAULT_MAX_EXTENSION_DAYS

        #  2026-08-01 plus 120 days, so the window opens on 2026-10-30T00:00:00Z.
        assert world["reservation"]["expires_at"].startswith("2026-11-29T00:00:00")
        assert world["reservation"]["extension_count"] == 0
        assert world["reservation"]["extension_days_granted"] == 0

        set_clock(api, "2026-10-29T23:59:59Z")
        validate_error(
            api.create_reservation_extension(
                reservation_id, build_extension_payload(60), contractor_headers
            ),
            ApiErrorId.ERR_EXTENSION_WINDOW_NOT_OPEN,
            expected_status=422,
        )
        early = read_reservation(api, reservation_id)
        assert early["extension_count"] == 0
        assert early["expires_at"].startswith("2026-11-29T00:00:00")

        #  One second later the window is open, so only the day count can fail.
        set_clock(api, "2026-10-30T00:00:00Z")
        validate_error(
            api.create_reservation_extension(
                reservation_id, build_extension_payload(61), contractor_headers
            ),
            ApiErrorId.ERR_EXTENSION_DAYS_EXCEEDED,
            expected_status=422,
        )
        assert read_reservation(api, reservation_id)["extension_count"] == 0

        granted = validate_success(
            api.create_reservation_extension(
                reservation_id, build_extension_payload(60), contractor_headers
            ),
            200,
        )
        assert granted["expires_at"].startswith("2027-01-28T00:00:00")
        assert granted["extension_count"] == 1
        assert granted["extension_days_granted"] == 60

        #  The grant pushed expiry to 2027-01-28, so the window it will be measured
        #  against next opens 30 days before that. Step onto that opening instant, or
        #  window membership — the first of the three checks — would answer instead.
        set_clock(api, "2026-12-29T00:00:00Z")

        #  The count limit is now the binding check, and it is tested before the days.
        validate_error(
            api.create_reservation_extension(
                reservation_id, build_extension_payload(1), contractor_headers
            ),
            ApiErrorId.ERR_EXTENSION_LIMIT_REACHED,
            expected_status=422,
        )
        final = read_reservation(api, reservation_id)
        assert final["expires_at"].startswith("2027-01-28T00:00:00")
        assert final["extension_count"] == 1
        assert final["extension_days_granted"] == 60

        #  An extension moves time, never money.
        assert final["reserved_amount_cents"] == 800000
        assert final["initial_reserved_amount_cents"] == 800000
        assert_household_cap(
            read_household(api, world["household_id"]), remaining=600000, encumbered=800000
        )

    def test_the_window_is_recomputed_from_the_extended_expiry_each_time(self, api):
        """A granted extension moves the window it will be measured against next.

        PRD §3.6: "The extension window opens at the reservation's `expires_at` minus the
        program's `extension_window_days` days, and the lower bound is inclusive: a request
        made exactly `extension_window_days` before expiry is accepted, while a request made
        earlier than that is refused with `ERR_EXTENSION_WINDOW_NOT_OPEN`."

        PRD §3.6: "A granted extension pushes `expires_at` out by `additional_days` days,
        increments `extension_count` by one, adds `additional_days` to
        `extension_days_granted`, and increments the reservation's version."

        PRD §3.6: "The reservation's `extension_count` must be strictly below the program's
        `max_extensions_per_reservation`, or the request is refused with
        `ERR_EXTENSION_LIMIT_REACHED`."

        Design: Difficulty/boundary_precision_check/extension_window_inclusive_lower_bound_and_day_limits
        """
        world = build_world(
            api,
            stage="reserved",
            program_overrides={"max_extensions_per_reservation": 2},
            catalog=[build_hvac_heat_pump_payload()],
        )
        reservation_id = world["reservation_id"]
        contractor_headers = world["contractor_headers"]
        assert world["reservation"]["expires_at"].startswith("2026-11-29T00:00:00")

        #  First extension at the original opening instant, for 30 days.
        set_clock(api, "2026-10-30T00:00:00Z")
        first = validate_success(
            api.create_reservation_extension(
                reservation_id, build_extension_payload(30), contractor_headers
            ),
            200,
        )
        assert first["expires_at"].startswith("2026-12-29T00:00:00")
        assert first["extension_count"] == 1
        assert first["extension_days_granted"] == 30

        #  The window now opens 30 days before the *new* expiry, on 2026-11-29T00:00:00Z,
        #  so the instant that was inside the old window is outside the new one.
        set_clock(api, "2026-11-28T23:59:59Z")
        validate_error(
            api.create_reservation_extension(
                reservation_id, build_extension_payload(30), contractor_headers
            ),
            ApiErrorId.ERR_EXTENSION_WINDOW_NOT_OPEN,
            expected_status=422,
        )
        assert read_reservation(api, reservation_id)["extension_count"] == 1

        set_clock(api, "2026-11-29T00:00:00Z")
        second = validate_success(
            api.create_reservation_extension(
                reservation_id, build_extension_payload(30), contractor_headers
            ),
            200,
        )
        assert second["expires_at"].startswith("2027-01-28T00:00:00")
        assert second["extension_count"] == 2
        assert second["extension_days_granted"] == 60

        #  The second grant moved the window again, to 30 days before 2027-01-28. Step
        #  onto that instant so window membership passes and the count check answers.
        set_clock(api, "2026-12-29T00:00:00Z")

        #  Two is the configured ceiling, so the third request stops at the count check.
        validate_error(
            api.create_reservation_extension(
                reservation_id, build_extension_payload(30), contractor_headers
            ),
            ApiErrorId.ERR_EXTENSION_LIMIT_REACHED,
            expected_status=422,
        )
        final = read_reservation(api, reservation_id)
        assert final["expires_at"].startswith("2027-01-28T00:00:00")
        assert final["extension_count"] == 2
        assert final["extension_days_granted"] == 60


class TestConditionalPassReductionFloor:
    def test_the_ten_percent_reduction_floors_a_seven_hundred_thousand_and_one_cent_line(
        self, api
    ):
        """630000.9 becomes 630000, not 630001.

        PRD §3.5: "If the project's `conditional_pass_flag` is true *and* this is the final
        computation, the line amount is then multiplied by one minus the ten-percent
        conditional reduction — that is, by 0.90 — and floored to whole cents."

        PRD §3.8: "**The conditional-pass branch** moves the inspection `SCHEDULED →
        CONDITIONAL_PASS` and is permitted only when `deficiency_severity_max` is no greater
        than 2. It drives the same project transition `INSTALLED → VERIFIED` with the same
        line-level verification, the same final allocation, and the same stacking
        recomputation — but it additionally sets the project's `conditional_pass_flag` to
        true, which means every final line amount is reduced by the ten-percent conditional
        reduction before the cap stages run."

        PRD §3.5: "The final variant runs at post-installation verification and on the
        anchor-rejection cascade hop; it uses verified quantities and actual costs, its Stage
        3 ceiling adds this project's own `reserved_amount_cents` back, it applies the
        conditional reduction in Stage 1 when a conditional pass is in force, and it writes
        `final_incentive_cents` on each line and `final_total_incentive_cents` on the
        project."

        Design: Difficulty/boundary_precision_check/conditional_pass_reduction_floors_each_final_line
        """
        world = build_world(
            api,
            stage="inspection_scheduled",
            program_overrides={"quality_suspension_threshold": 0},
            catalog=[build_hvac_heat_pump_payload()],
            measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700001)],
            installation_overrides={"actual_project_cost_cents": 700001},
        )
        project_id = world["project_id"]
        assert world["reservation"]["reserved_amount_cents"] == 800000

        recorded = record_result(
            api,
            world["inspection_id"],
            world["inspector_id"],
            build_conditional_pass_result_payload(
                deficiency_count=1,
                deficiency_severity_max=2,
                notes="Minor labelling deficiency, corrected on site",
            ),
        )
        assert recorded["status"] == InspectionStatus.CONDITIONAL_PASS
        assert recorded["deficiency_severity_max"] == 2

        #  Pre-reduction the line is min(800000, 800000, floor(700001 * 1.00)) = 700001.
        line = read_project_measures(api, project_id)[0]
        assert line["actual_cost_cents"] == 700001
        assert line["final_incentive_cents"] == 630000

        project = read_project(api, project_id)
        assert project["status"] == ProjectStatus.VERIFIED
        assert project["conditional_pass_flag"] is True
        assert project["final_total_incentive_cents"] == 630000
        assert project["provisional_total_incentive_cents"] == 800000

        #  The replay agrees, line by line.
        quote = read_quote(api, project_id, QuoteVariant.FINAL)
        assert quote["variant"] == QuoteVariant.FINAL
        assert_quote_line(quote, MEASURE_HP_HVAC, 800000, 700001, 630000, 630000)
        assert quote["total_incentive_cents"] == 630000
        assert quote["group_cap_applied"] is False

        #  Verification never reconciles the encumbrance; payment does.
        assert_household_cap(
            read_household(api, world["household_id"]), remaining=600000, encumbered=800000
        )

    def test_the_reduction_lands_before_the_group_cap_and_not_after_it(self, api):
        """Reduce then prorate gives 800000; prorate then reduce would give 720000.

        PRD §3.8: "**The conditional-pass branch** moves the inspection `SCHEDULED →
        CONDITIONAL_PASS` and is permitted only when `deficiency_severity_max` is no greater
        than 2. It drives the same project transition `INSTALLED → VERIFIED` with the same
        line-level verification, the same final allocation, and the same stacking
        recomputation — but it additionally sets the project's `conditional_pass_flag` to
        true, which means every final line amount is reduced by the ten-percent conditional
        reduction before the cap stages run. The reduction therefore lands *before* group
        and household proration, not after."

        PRD §3.5: "If that sum is **strictly greater** than the program's `group_cap_cents`
        — a sum exactly equal to the cap does not prorate — then every member except the
        last in that order is reduced to its amount multiplied by the group cap divided by
        the sum, floored to whole cents, and the last member receives the group cap minus
        the sum of those floored members."

        PRD §3.5: "The project total is the sum of the resulting line amounts, which
        therefore equals the binding cap exactly whenever a cap bound."

        Design: Difficulty/boundary_precision_check/conditional_pass_reduction_floors_each_final_line
        """
        world = build_world(
            api,
            stage="inspection_scheduled",
            program_overrides={"quality_suspension_threshold": 0},
            catalog=[build_hvac_heat_pump_payload(), build_duct_payload()],
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HP_DUCT, 1, 300000),
            ],
            measure_results=[
                build_measure_result(MEASURE_HP_HVAC, 1, 1000000),
                build_measure_result(MEASURE_HP_DUCT, 1, 300000),
            ],
            installation_overrides={"actual_project_cost_cents": 1300000},
        )
        project_id = world["project_id"]
        assert world["reservation"]["reserved_amount_cents"] == DEFAULT_GROUP_CAP_CENTS

        record_result(
            api,
            world["inspection_id"],
            world["inspector_id"],
            build_conditional_pass_result_payload(deficiency_count=2, deficiency_severity_max=1),
        )

        #  Stage 1 reduces 800000 and 250000 to 720000 and 225000; their sum 945000 is
        #  still over the 800000 group cap, so Stage 2 prorates the reduced amounts.
        lines = read_project_measures(api, project_id)
        assert [line["final_incentive_cents"] for line in lines] == [609523, 190477]
        project = read_project(api, project_id)
        assert project["conditional_pass_flag"] is True
        assert project["final_total_incentive_cents"] == DEFAULT_GROUP_CAP_CENTS
        assert project["status"] == ProjectStatus.VERIFIED

        quote = read_quote(api, project_id, QuoteVariant.FINAL)
        assert_quote_line(quote, MEASURE_HP_HVAC, 800000, 1000000, 720000, 609523)
        assert_quote_line(quote, MEASURE_HP_DUCT, 250000, 300000, 225000, 190477)
        assert quote["group_cap_applied"] is True
        assert quote["residual_cents_assigned_to_measure_code"] == MEASURE_HP_DUCT
        assert quote["total_incentive_cents"] == DEFAULT_GROUP_CAP_CENTS
        assert_quote_totals_match_lines(quote)
