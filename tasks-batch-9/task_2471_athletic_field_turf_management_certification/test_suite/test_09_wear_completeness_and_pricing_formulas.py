"""Three multi-factor formulas whose difficulty lives in nesting and ordering."""

from test_helpers import (
    ApiErrorId,
    assert_certification_packet,
    assert_replacement_plan,
    assert_two_decimals,
    assert_usage_booking,
    factories,
    fixtures,
    validate_error,
)


class TestWearLoadCappedCrowdSurcharge:
    def test_crowd_surcharge_stops_growing_inside_the_multiplier_product(
        self, client, roster
    ):
        """A packed stand costs more than a half-full one, but only up to a point.

        "The crowd factor is 1.00 plus a surcharge, where the surcharge is the
        smaller of 0.50 and the product of 0.01 and the number of participants in
        excess of a free allowance of forty — a headcount at or below forty
        contributes no surcharge at all, and the surcharge stops growing once it
        reaches 0.50."

        "The raw load is the base load multiplied by the crowd factor, then by the
        surface factor, then by the weather factor, all at full precision."

        "Rounding happens exactly once, at the very end; the factors are never
        rounded individually."

        Design: Difficulty/combinatorial_formula/wear_load_units_capped_crowd_surcharge_nested_in_multiplier_product
        """
        field = fixtures.register_grass_main_1(client, roster)

        modest = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="GAME",
            window_start_utc="2026-08-02T19:00:00Z",
            window_end_utc="2026-08-02T23:00:00Z",
            expected_participant_count=60,
        )
        packed = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="GAME",
            window_start_utc="2026-08-03T19:00:00Z",
            window_end_utc="2026-08-03T23:00:00Z",
            expected_participant_count=200,
        )
        fixtures.confirm_booking(client, roster, modest["id"])
        fixtures.confirm_booking(client, roster, packed["id"])

        fixtures.set_clock(client, roster, "2026-08-02T23:00:00Z")
        modest_closed = fixtures.close_out_booking(
            client,
            roster,
            modest["id"],
            outcome="PLAYED",
            actual_duration_hours=4.00,
            actual_participant_count=60,
            weather_condition="DRY",
        )
        assert_usage_booking(modest_closed)
        # 4.00 h x 1.50 GAME x (1.00 + 0.01 x 20) x 1.20 grass x 1.00 dry.
        assert_two_decimals(
            modest_closed["wear_load_units"], 8.64, "60-participant wear_load_units"
        )

        fixtures.set_clock(client, roster, "2026-08-03T23:00:00Z")
        packed_closed = fixtures.close_out_booking(
            client,
            roster,
            packed["id"],
            outcome="PLAYED",
            actual_duration_hours=4.00,
            actual_participant_count=200,
            weather_condition="DRY",
        )
        # 160 participants over the allowance would be a surcharge of 1.60, but
        # the surcharge is the smaller of that and 0.50, so the crowd factor is
        # 1.50: 4.00 x 1.50 x 1.50 x 1.20 x 1.00.
        assert_two_decimals(
            packed_closed["wear_load_units"], 10.80, "200-participant wear_load_units"
        )
        assert round(float(packed_closed["wear_load_units"]), 2) != 18.72, (
            "an uncapped surcharge of 1.60 would have produced 18.72"
        )
        # 6.00 units at 0.50 plus the remaining 4.80 units at 1.00.
        assert_two_decimals(
            packed_closed["rest_requirement_hours"],
            7.80,
            "200-participant rest_requirement_hours",
        )

        after = fixtures.read_field(client, roster, field["id"])
        assert_two_decimals(
            after["cumulative_wear_units"], 19.44, "Field.cumulative_wear_units"
        )
        assert_two_decimals(after["usage_hours_ytd"], 8.00, "Field.usage_hours_ytd")
        assert_two_decimals(after["rest_debt_hours"], 7.80, "Field.rest_debt_hours")
        assert after["play_status"] == "RESTRICTED"

    def test_free_allowance_and_cap_onset_bracket_the_surcharge(self, client, roster):
        """Below forty heads the surcharge is absent; above ninety it is frozen.

        "The crowd factor is 1.00 plus a surcharge, where the surcharge is the
        smaller of 0.50 and the product of 0.01 and the number of participants in
        excess of a free allowance of forty — a headcount at or below forty
        contributes no surcharge at all, and the surcharge stops growing once it
        reaches 0.50."

        "The surface factor is keyed on the field's `surface_type`: 1.20 for
        `NATURAL_GRASS`, which bruises, and 0.80 for `SYNTHETIC_TURF`, which does
        not."

        "From those, the base load is the duration multiplied by an intensity
        weight keyed on `activity_type`: 1.00 for `PRACTICE`, 1.50 for `GAME`, 2.00
        for `TOURNAMENT` and 0.75 for `COMMUNITY`."

        Design: Difficulty/combinatorial_formula/wear_load_units_capped_crowd_surcharge_nested_in_multiplier_product
        """
        field = fixtures.register_synthetic_stadium_1(client, roster)

        headcounts = {40: "2026-08-02", 90: "2026-08-03", 200: "2026-08-04"}
        bookings = {}
        for headcount, day in headcounts.items():
            bookings[headcount] = fixtures.request_booking(
                client,
                roster,
                field["id"],
                activity_type="PRACTICE",
                window_start_utc=f"{day}T10:00:00Z",
                window_end_utc=f"{day}T12:00:00Z",
                expected_participant_count=headcount,
            )
            fixtures.confirm_booking(client, roster, bookings[headcount]["id"])

        closed = {}
        for headcount, day in headcounts.items():
            fixtures.set_clock(client, roster, f"{day}T12:00:00Z")
            closed[headcount] = fixtures.close_out_booking(
                client,
                roster,
                bookings[headcount]["id"],
                outcome="PLAYED",
                actual_duration_hours=2.00,
                actual_participant_count=headcount,
                weather_condition="DRY",
            )

        # Exactly at the allowance the crowd factor is a bare 1.00:
        # 2.00 h x 1.00 PRACTICE x 1.00 x 0.80 synthetic x 1.00 dry.
        assert_two_decimals(
            closed[40]["wear_load_units"], 1.60, "40-participant wear_load_units"
        )
        assert_two_decimals(
            closed[40]["rest_requirement_hours"],
            0.32,
            "40-participant rest_requirement_hours",
        )

        # Fifty heads over the allowance is a surcharge of exactly 0.50, which is
        # already the ceiling: 2.00 x 1.00 x 1.50 x 0.80 x 1.00.
        assert_two_decimals(
            closed[90]["wear_load_units"], 2.40, "90-participant wear_load_units"
        )
        assert_two_decimals(
            closed[200]["wear_load_units"], 2.40, "200-participant wear_load_units"
        )
        assert round(float(closed[200]["wear_load_units"]), 2) == round(
            float(closed[90]["wear_load_units"]), 2
        ), "the surcharge is frozen from ninety participants upward"
        assert round(float(closed[200]["wear_load_units"]), 2) != 4.16, (
            "an uncapped surcharge of 1.60 would have produced 4.16"
        )
        assert_two_decimals(
            closed[200]["rest_requirement_hours"],
            0.48,
            "200-participant rest_requirement_hours",
        )

        after = fixtures.read_field(client, roster, field["id"])
        # 1.60 + 2.40 + 2.40, all three on the same surface.
        assert_two_decimals(
            after["cumulative_wear_units"], 6.40, "Field.cumulative_wear_units"
        )
        assert_two_decimals(after["usage_hours_ytd"], 6.00, "Field.usage_hours_ytd")


class TestCompletenessRoundingOrder:
    def test_each_weighted_component_is_rounded_before_the_six_are_summed(
        self, client, roster
    ):
        """Two components land on repeating thirds, and the order of rounding shows.

        "Six components each produce a ratio between 0.00 and 1.00, each ratio is
        multiplied by its weight, each weighted product is rounded half up to two
        decimal places **individually**, the six rounded products are summed, and
        the sum is rounded half up to two decimal places again. Summing at full
        precision and rounding once is a different number and is not what this
        specification asks for."

        "The agronomic-programme component is worth 20 points: the denominator is
        the set of maintenance tasks on the field whose
        `planned_for_certification_window` is true, whose `status` is anything
        other than `CANCELLED`, and whose `scheduled_start_utc` falls inside the
        window, and the ratio is the proportion of that set whose `status` is
        `COMPLETED`"

        "The surface-specification component is worth 10 points and its ratio
        depends on the surface family: on a `SYNTHETIC_TURF` field it is the
        field's `infill_depth_mm` divided by a required depth of 51.0 millimetres,
        capped at 1.00"

        Design: Difficulty/combinatorial_formula/certification_completeness_rounds_each_component_before_summation
        """
        # The canonical synthetic surface carries an infill depth of 34.0 mm, so
        # the specification ratio is exactly two thirds.
        field = fixtures.register_synthetic_stadium_1(client, roster)
        impact = fixtures.record_impact_test(
            client, roster, field["id"], [120.0, 120.0, 120.0]
        )
        fixtures.record_inspection(
            client, roster, field["id"], assessment_type="STRIPING_LAYOUT"
        )
        fixtures.record_inspection(
            client, roster, field["id"], assessment_type="GOAL_ANCHORING"
        )

        grooming = fixtures.schedule_task(
            client,
            roster,
            field["id"],
            task_type="GROOMING",
            scheduled_start_utc="2026-08-01T06:00:00Z",
            scheduled_end_utc="2026-08-01T07:00:00Z",
            planned_for_certification_window=True,
        )
        fixtures.schedule_task(
            client,
            roster,
            field["id"],
            task_type="INFILL_REDISTRIBUTION",
            scheduled_start_utc="2026-08-01T08:00:00Z",
            scheduled_end_utc="2026-08-01T09:00:00Z",
            planned_for_certification_window=True,
        )
        fixtures.schedule_task(
            client,
            roster,
            field["id"],
            task_type="SEAM_INSPECTION",
            scheduled_start_utc="2026-08-01T10:00:00Z",
            scheduled_end_utc="2026-08-01T11:00:00Z",
            planned_for_certification_window=True,
        )

        fixtures.set_clock(client, roster, "2026-08-02T00:00:00Z")
        # Exactly one of the three programme tasks is carried to COMPLETED, so the
        # agronomic ratio is one third.
        completed = fixtures.start_and_complete_task(
            client, roster, grooming["id"], "2026-08-02T00:00:00Z"
        )
        assert completed["status"] == "COMPLETED"

        current = fixtures.read_field(client, roster, field["id"])
        packet = fixtures.open_packet(
            client,
            roster,
            field["id"],
            impact["id"],
            current["version"],
            competition_season_label="2026-FALL",
        )
        submitted = fixtures.submit_packet(client, roster, packet["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["return_count"] == 0

        # 30.00 safety + 6.67 agronomic (20 x 1/3) + 15.00 striping + 15.00 goal
        # anchoring + 6.67 specification (10 x 34/51) + 10.00 remediation.
        assert_two_decimals(
            submitted["documentation_completeness_score"],
            83.34,
            "documentation_completeness_score",
        )
        assert round(float(submitted["documentation_completeness_score"]), 2) != 83.33, (
            "summing 6.666667 and 6.666667 at full precision would have given 83.33"
        )
        # Wear 100.00 x 0.20 + age 0.00 x 0.20 + safety 72.73 x 0.60 = 63.638,
        # which is already below the safety component the cap compares against.
        assert_two_decimals(
            submitted["condition_index_certification"],
            63.64,
            "condition_index_certification",
        )

        after = fixtures.read_field(client, roster, field["id"])
        assert after["certification_status"] == "PENDING_REVIEW"

    def test_a_draft_packet_scores_nothing_until_it_is_submitted(
        self, client, roster
    ):
        """The scores are a property of submission, and the create is version-guarded.

        "The packet starts in `DRAFT` with `documentation_completeness_score` and
        `condition_index_certification` both null, `submitted_by_staff_member_id`,
        `decided_by_staff_member_id`, `submitted_at_utc`, `decided_at_utc`,
        `certified_until_utc` and `decision_notes` all null, and `return_count` at
        0."

        "If that value does not equal the field's current `version`, the create is
        rejected with `ERR_STALE_FIELD_VERSION` (HTTP 412)."

        "Creating the packet increments `Field.open_certification_packet_count` by
        1 and `Field.version` by 1."

        Design: Difficulty/combinatorial_formula/certification_completeness_rounds_each_component_before_summation
        """
        built = fixtures.build_certifiable_synthetic_field(
            client, roster, infill_depth_mm=34.0
        )
        field = built["field"]
        observed_version = field["version"]

        packet = fixtures.open_packet(
            client,
            roster,
            field["id"],
            built["impact"]["id"],
            observed_version,
            competition_season_label="2026-FALL",
        )
        assert_certification_packet(packet)
        assert packet["status"] == "DRAFT"
        assert packet.get("documentation_completeness_score") is None
        assert packet.get("condition_index_certification") is None
        assert packet.get("submitted_by_staff_member_id") is None
        assert packet.get("submitted_at_utc") is None
        assert packet["return_count"] == 0

        # Opening the packet moved the field's version on, so the same observation
        # can no longer be replayed.
        validate_error(
            client.create_certification_packet(
                factories.make_certification_packet_payload(
                    field_id=field["id"],
                    governing_assessment_id=built["impact"]["id"],
                    expected_field_version=observed_version,
                    competition_season_label="2026-SPRING",
                ),
                roster.cert_officer_headers,
            ),
            ApiErrorId.STALE_FIELD_VERSION,
            412,
        )

        moved_on = fixtures.read_field(client, roster, field["id"])
        assert moved_on["version"] == observed_version + 1
        assert moved_on["open_certification_packet_count"] == 1

        submitted = fixtures.submit_packet(client, roster, packet["id"])
        # 30.00 safety + 20.00 vacuous agronomic + 15.00 striping + 15.00 goal
        # anchoring + 6.67 specification (10 x 34/51) + 10.00 remediation.
        assert_two_decimals(
            submitted["documentation_completeness_score"],
            96.67,
            "documentation_completeness_score",
        )
        assert_two_decimals(
            submitted["condition_index_certification"],
            63.64,
            "condition_index_certification",
        )
        assert submitted["submitted_by_staff_member_id"] == roster.id_of("cert_officer")


class TestPlanContingencyTierOrdering:
    def test_contingency_tier_is_read_off_the_pre_contingency_subtotal(
        self, client, roster
    ):
        """The uplift is part of the total, so its tier cannot be read from the total.

        "Fourth — and this is the pinned step — the `contingency_rate` is selected
        from that **pre-contingency** subtotal and never from the final total: a
        subtotal below 2000000 cents takes a rate of 0.10, a subtotal of 2000000
        cents or more but below 5000000 cents takes 0.07, and a subtotal of 5000000
        cents or more takes 0.05."

        "Second, `disposal_cents` accounts for taking the *existing* surface away:
        when the existing `Field.surface_type` is `SYNTHETIC_TURF` it is the plan's
        `area_sq_ft` multiplied by 5 cents per square foot, and when the existing
        surface is `NATURAL_GRASS` it is 0, because grass is not a waste stream."

        "Its second, **independent** axis, `disposal_status`, starts at `PENDING`
        when the *existing* `Field.surface_type` is `SYNTHETIC_TURF` — synthetic
        infill and carpet must be manifested to a licensed receiver — and at
        `NOT_APPLICABLE` otherwise."

        Design: Difficulty/combinatorial_formula/plan_contingency_tier_selected_on_pre_contingency_subtotal
        """
        field = fixtures.register_synthetic_stadium_1(client, roster)
        budget = fixtures.authorize_budget(client, roster)

        plan = fixtures.draft_plan(
            client,
            roster,
            field["id"],
            budget["id"],
            field["version"],
            target_surface_type="SYNTHETIC_TURF",
            area_sq_ft=70000,
            priority_basis="CONDITION_RISK",
            planned_install_year=2028,
        )
        assert_replacement_plan(plan)

        # 70000 sq ft at 65 cents, plus the same area at 5 cents to take the old
        # carpet away.
        assert plan["base_construction_cents"] == 4550000
        assert plan["disposal_cents"] == 350000
        assert plan["pre_contingency_subtotal_cents"] == 4900000
        # 4900000 sits below the 5000000 boundary, so the middle tier applies.
        assert round(float(plan["contingency_rate"]), 4) == 0.07
        assert plan["contingency_cents"] == 343000
        assert plan["plan_funding_amount_cents"] == 5243000
        assert plan["plan_funding_amount_cents"] != 5145000, (
            "reading the tier off the finished total would have selected 0.05"
        )
        assert plan["disposal_status"] == "PENDING"
        assert plan["funding_status"] == "DRAFT"

    def test_a_smaller_project_can_cost_more_than_a_larger_one(self, client, roster):
        """The tier boundary is a discontinuity, and it sits before the uplift.

        "The upper bounds are strict, so a subtotal of exactly 5000000 cents
        selects 0.05."

        "First, `base_construction_cents` is the plan's `area_sq_ft` multiplied by
        a unit cost keyed on `target_surface_type`: 22 cents per square foot for
        `NATURAL_GRASS`, 65 cents per square foot for `SYNTHETIC_TURF`."

        "Finally, `plan_funding_amount_cents` is `pre_contingency_subtotal_cents`
        plus `contingency_cents`. Reading the tier off the finished total would be
        circular and is wrong."

        Design: Difficulty/combinatorial_formula/plan_contingency_tier_selected_on_pre_contingency_subtotal
        """
        field = fixtures.register_grass_main_1(client, roster)
        budget = fixtures.authorize_budget(client, roster)

        smaller = fixtures.draft_plan(
            client,
            roster,
            field["id"],
            budget["id"],
            field["version"],
            target_surface_type="SYNTHETIC_TURF",
            area_sq_ft=76000,
            priority_basis="CONDITION_RISK",
            planned_install_year=2028,
        )
        larger = fixtures.draft_plan(
            client,
            roster,
            field["id"],
            budget["id"],
            fixtures.read_field(client, roster, field["id"])["version"],
            target_surface_type="SYNTHETIC_TURF",
            area_sq_ft=77000,
            priority_basis="CONDITION_RISK",
            planned_install_year=2028,
        )
        modest = fixtures.draft_plan(
            client,
            roster,
            field["id"],
            budget["id"],
            fixtures.read_field(client, roster, field["id"])["version"],
            target_surface_type="NATURAL_GRASS",
            area_sq_ft=80000,
            priority_basis="CONDITION_RISK",
            planned_install_year=2028,
        )

        # The existing surface is grass, so nothing is a waste stream and the
        # subtotal is the construction cost alone.
        assert smaller["disposal_cents"] == 0
        assert smaller["pre_contingency_subtotal_cents"] == 4940000
        assert round(float(smaller["contingency_rate"]), 4) == 0.07
        assert smaller["contingency_cents"] == 345800
        assert smaller["plan_funding_amount_cents"] == 5285800

        assert larger["pre_contingency_subtotal_cents"] == 5005000
        assert round(float(larger["contingency_rate"]), 4) == 0.05
        assert larger["contingency_cents"] == 250250
        assert larger["plan_funding_amount_cents"] == 5255250

        # A thousand extra square feet crosses the boundary and lowers the total.
        assert (
            larger["plan_funding_amount_cents"] < smaller["plan_funding_amount_cents"]
        ), "the tier discontinuity makes the bigger project the cheaper one"

        assert modest["pre_contingency_subtotal_cents"] == 1760000
        assert round(float(modest["contingency_rate"]), 4) == 0.10
        assert modest["contingency_cents"] == 176000
        assert modest["plan_funding_amount_cents"] == 1936000

        for plan in (smaller, larger, modest):
            assert plan["disposal_status"] == "NOT_APPLICABLE"
