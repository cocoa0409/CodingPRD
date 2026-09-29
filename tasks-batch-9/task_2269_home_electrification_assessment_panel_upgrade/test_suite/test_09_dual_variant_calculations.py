"""Two variants over one history: provisional versus final money, rolling versus weighted quality."""

from test_helpers import (
    ContractorStatus,
    DEFAULT_LOW_TIER_CAP_CENTS,
    DEFAULT_QUALITY_SUSPENSION_THRESHOLD,
    DEFAULT_RECERTIFICATION_THRESHOLD,
    InspectionType,
    InstallStatus,
    MEASURE_HPWH,
    MEASURE_HP_HVAC,
    MEASURE_PANEL_200A,
    ProjectStatus,
    QuoteVariant,
    ReservationStatus,
    SuspensionReason,
    VerificationStatus,
    assert_household_cap,
    assert_measure_codes_in_order,
    assert_quote_line,
    assert_quote_totals_match_lines,
    build_assessment_measure,
    build_fail_result_payload,
    build_hvac_heat_pump_payload,
    build_measure_result,
    build_pass_result_payload,
    build_world,
    create_inspector,
    find_measure_line,
    read_contractor,
    read_household,
    read_project,
    read_project_measures,
    read_quality_review,
    read_quote,
    read_reservation,
    record_result,
    schedule_inspection,
    set_clock,
)


class TestProvisionalVersusFinalProjectMoney:
    def test_one_measure_set_is_worth_1375000_as_planned_and_1230000_as_verified(self, api):
        """Verification recomputes the same three lines from actual costs, 145000 lower.

        PRD §3.5: "Which quantity and which cost feed the computation depends on the
        variant: the provisional computation uses `planned_quantity` and
        `estimated_cost_cents`, while the final computation uses `verified_quantity` and
        `actual_cost_cents`."

        PRD §3.5: "The line amount is then the smallest of three values: the raw amount,
        the `pinned_measure_cap_cents`, and the cost-share ceiling."

        PRD §3.5: "The provisional variant of this waterfall runs at project creation,
        again on resubmission from `INCOMPLETE`, and its result is the amount the
        reservation encumbers; it uses planned quantities and estimated costs, its Stage
        3 ceiling excludes any reservation of this project because none exists yet, and
        it writes `provisional_incentive_cents` on each line and
        `provisional_total_incentive_cents` on the project."

        PRD §3.5: "The final variant runs at post-installation verification and on the
        anchor-rejection cascade hop; it uses verified quantities and actual costs, its
        Stage 3 ceiling adds this project's own `reserved_amount_cents` back, it applies
        the conditional reduction in Stage 1 when a conditional pass is in force, and it
        writes `final_incentive_cents` on each line and `final_total_incentive_cents` on
        the project."

        PRD §3.6: "Its `reserved_amount_cents` and its immutable
        `initial_reserved_amount_cents` are both set to the project's
        `provisional_total_incentive_cents`"

        Design: Difficulty/dual_variant_calc/provisional_vs_final_project_incentive_divergence
        """
        world = build_world(
            api,
            stage="inspection_scheduled",
            household_overrides={"existing_panel_amps": 100},
            assessed_panel_amps=100,
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HPWH, 1, 300000),
                build_assessment_measure(MEASURE_PANEL_200A, 1, 600000),
            ],
            measure_results=[
                build_measure_result(MEASURE_HP_HVAC, 1, 700000),
                build_measure_result(MEASURE_HPWH, 1, 150000),
                build_measure_result(MEASURE_PANEL_200A, 1, 380000),
            ],
            installation_overrides={
                "installed_panel_amps": 200,
                "actual_project_cost_cents": 1230000,
            },
        )
        project_id = world["project_id"]

        #  Planned: unit incentives 800000 / 175000 / 400000, every cost-share ceiling
        #  (cost times 1.00) above them, so Stage 1 pays the pinned rates in full and
        #  the HVAC group lands exactly on its 800000 cap without prorating.
        reserved = read_project(api, project_id)
        assert reserved["provisional_total_incentive_cents"] == 1375000
        assert reserved["final_total_incentive_cents"] is None
        reservation = read_reservation(api, world["reservation_id"])
        assert reservation["initial_reserved_amount_cents"] == 1375000
        assert reservation["reserved_amount_cents"] == 1375000
        assert_household_cap(
            read_household(api, world["household_id"]),
            remaining=25000,
            encumbered=1375000,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

        record_result(
            api, world["inspection_id"], world["inspector_id"], build_pass_result_payload()
        )

        #  Verified: the same three lines, now ceilinged by actual costs 700000 / 150000
        #  / 380000, and the Stage 3 ceiling is 25000 remaining plus this project's own
        #  1375000 encumbrance, so no cap binds and the money simply shrinks.
        verified = read_project(api, project_id)
        assert verified["status"] == ProjectStatus.VERIFIED
        assert verified["conditional_pass_flag"] is False
        assert verified["provisional_total_incentive_cents"] == 1375000
        assert verified["final_total_incentive_cents"] == 1230000
        assert (
            verified["provisional_total_incentive_cents"]
            - verified["final_total_incentive_cents"]
            == 145000
        )

        lines = read_project_measures(api, project_id)
        heat_pump = find_measure_line(lines, MEASURE_HP_HVAC)
        assert heat_pump["provisional_incentive_cents"] == 800000
        assert heat_pump["final_incentive_cents"] == 700000
        water_heater = find_measure_line(lines, MEASURE_HPWH)
        assert water_heater["provisional_incentive_cents"] == 175000
        assert water_heater["final_incentive_cents"] == 150000
        panel = find_measure_line(lines, MEASURE_PANEL_200A)
        assert panel["provisional_incentive_cents"] == 400000
        assert panel["final_incentive_cents"] == 380000
        assert sum(line["final_incentive_cents"] for line in lines) == 1230000

        #  Payment has not run, so the reservation still holds the provisional amount
        #  and the household is still encumbered for it.
        settled = read_reservation(api, world["reservation_id"])
        assert settled["status"] == ReservationStatus.RESERVED
        assert settled["initial_reserved_amount_cents"] == 1375000
        assert settled["reserved_amount_cents"] == 1375000
        assert_household_cap(
            read_household(api, world["household_id"]),
            remaining=25000,
            encumbered=1375000,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

    def test_the_computed_read_replays_the_final_variant_before_verification_stores_it(
        self, api
    ):
        """The final replay exposes stage by stage what the pass branch will later write.

        PRD §3.5: "Because both cap stages are invisible in the stored totals alone, a
        computed read replays the whole waterfall over the project's current lines and
        exposes each stage without changing any state."

        PRD §3.5: "It accepts an optional `variant` selecting which computation to
        replay, defaulting to the provisional one, and returns the `project_id`, the
        `variant` it ran, a `lines` array, and the aggregates
        `group_capped_total_cents`, `household_cap_limit_cents`,
        `total_incentive_cents`, the booleans `group_cap_applied` and
        `household_cap_applied`, and `residual_cents_assigned_to_measure_code` naming
        the line that absorbed the residual."

        PRD §3.5: "Each entry of `lines` reports a `measure_code`, its
        `raw_incentive_cents`, its `cost_share_cap_cents`, its `capped_line_cents` after
        the per-line ceilings, and its `allocated_cents` after both cap stages, in
        `pinned_sort_order` ascending then `created_at` ascending order."

        PRD §3.5: "The available ceiling is the household's
        `lifetime_cap_remaining_cents` plus whatever this project has already encumbered
        for itself — that is, plus this project's own reservation's
        `reserved_amount_cents` when a reservation in status `RESERVED` exists, and plus
        0 when none does."

        PRD §3.8: "On a `POST_INSTALL` inspection of an installed project it moves the
        project `INSTALLED → VERIFIED`: every measure line moves `verification_status`
        from `PENDING` to `VERIFIED` and stores its `verified_quantity` from the result
        payload, the final allocation runs over the project and writes each line's
        `final_incentive_cents` and the project's `final_total_incentive_cents`, and the
        project's active stacking declaration, if one exists, is recomputed along with
        the project's `stacking_adjusted_state_incentive_cents`."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_project_incentive_divergence
        """
        world = build_world(
            api,
            stage="inspection_scheduled",
            household_overrides={"existing_panel_amps": 100},
            assessed_panel_amps=100,
            assessment_measures=[
                build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000),
                build_assessment_measure(MEASURE_HPWH, 1, 300000),
                build_assessment_measure(MEASURE_PANEL_200A, 1, 600000),
            ],
            measure_results=[
                build_measure_result(MEASURE_HP_HVAC, 1, 700000),
                build_measure_result(MEASURE_HPWH, 1, 150000),
                build_measure_result(MEASURE_PANEL_200A, 1, 380000),
            ],
            installation_overrides={
                "installed_panel_amps": 200,
                "actual_project_cost_cents": 1230000,
            },
        )
        project_id = world["project_id"]
        before = read_project(api, project_id)

        #  The default replay is the planned one: estimated costs 1000000 / 300000 /
        #  600000 set the cost-share ceilings, so no per-line ceiling bites.
        planned = read_quote(api, project_id)
        assert planned["project_id"] == project_id
        assert planned["variant"] == QuoteVariant.PROVISIONAL
        assert_measure_codes_in_order(
            planned["lines"], [MEASURE_HP_HVAC, MEASURE_HPWH, MEASURE_PANEL_200A]
        )
        assert_quote_line(planned, MEASURE_HP_HVAC, 800000, 1000000, 800000)
        assert_quote_line(planned, MEASURE_HPWH, 175000, 300000, 175000)
        assert_quote_line(planned, MEASURE_PANEL_200A, 400000, 600000, 400000)
        assert planned["group_capped_total_cents"] == 1375000
        assert planned["group_cap_applied"] is False

        #  The final replay reads verified quantities and actual costs instead, and its
        #  Stage 3 ceiling is 25000 + 1375000 = 1400000, so nothing is prorated.
        final = read_quote(api, project_id, QuoteVariant.FINAL)
        assert final["project_id"] == project_id
        assert final["variant"] == QuoteVariant.FINAL
        assert_measure_codes_in_order(
            final["lines"], [MEASURE_HP_HVAC, MEASURE_HPWH, MEASURE_PANEL_200A]
        )
        assert_quote_line(final, MEASURE_HP_HVAC, 800000, 700000, 700000, 700000)
        assert_quote_line(final, MEASURE_HPWH, 175000, 150000, 150000, 150000)
        assert_quote_line(final, MEASURE_PANEL_200A, 400000, 380000, 380000, 380000)
        assert final["group_capped_total_cents"] == 1230000
        assert final["household_cap_limit_cents"] == 1400000
        assert final["total_incentive_cents"] == 1230000
        assert final["group_cap_applied"] is False
        assert final["household_cap_applied"] is False
        assert_quote_totals_match_lines(final)

        #  Two replays of two variants changed nothing at all.
        untouched = read_project(api, project_id)
        assert untouched == before
        assert untouched["status"] == ProjectStatus.INSTALLED
        assert untouched["final_total_incentive_cents"] is None
        for line in read_project_measures(api, project_id):
            assert line["install_status"] == InstallStatus.INSTALLED
            assert line["verification_status"] == VerificationStatus.PENDING
            assert line["final_incentive_cents"] is None

        #  Recording the pass writes exactly what the final replay predicted.
        record_result(
            api, world["inspection_id"], world["inspector_id"], build_pass_result_payload()
        )
        verified = read_project(api, project_id)
        assert verified["final_total_incentive_cents"] == final["total_incentive_cents"]
        stored = read_project_measures(api, project_id)
        for quote_line in final["lines"]:
            line = find_measure_line(stored, quote_line["measure_code"])
            assert line["verification_status"] == VerificationStatus.VERIFIED
            assert line["verified_quantity"] == 1
            assert line["final_incentive_cents"] == quote_line["allocated_cents"]


class TestRollingWindowVersusSeverityWeightedQuality:
    def test_three_spot_results_score_sixty_seven_rolling_and_thirty_three_weighted(self, api):
        """Equal weights say 67, deficiency weights say 33, and only the first suspends.

        PRD §3.3: "Each candidate contributes a point value determined by its status:
        100 points for `PASSED`, 70 for `CONDITIONAL_PASS`, and 0 for `FAILED`."

        PRD §3.3: "The **rolling-window** measure takes at most the ten most recent
        candidates in that order, weights each equally, and is the sum of their point
        values divided by the number of candidates counted, rounded half up to a whole
        number. It ignores `deficiency_count` and ignores any date horizon."

        PRD §3.3: "When it lands strictly below the program's
        `quality_suspension_threshold`, the contractor is automatically taken
        `ENROLLED_ACTIVE → SUSPENDED` with `suspension_reason` set to `QUALITY_SCORE`,
        dragging the contractor-hold cascade behind it."

        PRD §3.3: "It takes every candidate whose `result_recorded_at` falls at or after
        365 days before the logical clock's instant — with no cap on how many that is —
        and weights each candidate by one plus its `deficiency_count`. The score is the
        sum of each weight multiplied by that candidate's point value, divided by the
        sum of the weights, rounded half up to a whole number; only that final quotient
        is rounded, never the individual terms."

        PRD §3.3: "A dedicated computed read exposes both measures side by side for one
        contractor and persists neither: it returns the `contractor_id`, the
        `rolling_window_score` and `severity_weighted_score`, the
        `rolling_window_inspection_count` and `weighted_inspection_count` that each
        measure actually counted, the `suspension_threshold` and
        `recertification_threshold` in force, and the boolean
        `recertification_eligible`."

        Design: Difficulty/dual_variant_calc/rolling_window_vs_severity_weighted_contractor_quality
        """
        world = build_world(api, stage="project", catalog=[build_hvac_heat_pump_payload()])
        project_id = world["project_id"]
        contractor_id = world["contractor_id"]
        inspector = create_inspector(api, world["program_id"])
        inspector_id = inspector["id"]

        #  Three SPOT audits of the same project, a day apart, so the 45-minute travel
        #  buffer never bites. A SPOT audit needs no particular project state.
        windows = [
            ("2026-09-01T09:00:00Z", "2026-09-01T10:00:00Z"),
            ("2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z"),
            ("2026-09-03T09:00:00Z", "2026-09-03T10:00:00Z"),
        ]
        inspections = [
            schedule_inspection(
                api,
                project_id,
                inspector_id,
                InspectionType.SPOT,
                scheduled_start=start,
                scheduled_end=end,
            )
            for start, end in windows
        ]

        record_result(api, inspections[0]["id"], inspector_id, build_pass_result_payload())
        after_one = read_contractor(api, contractor_id)
        assert after_one["quality_score_rolling"] == 100
        assert after_one["completed_inspection_count"] == 1
        assert after_one["status"] == ContractorStatus.ENROLLED_ACTIVE

        record_result(api, inspections[1]["id"], inspector_id, build_pass_result_payload())
        after_two = read_contractor(api, contractor_id)
        assert after_two["quality_score_rolling"] == 100
        assert after_two["completed_inspection_count"] == 2

        #  One failure carrying three deficiencies: equal weights give (100 + 100 + 0)
        #  / 3 = 66.67 -> 67, while weights 1, 1 and 4 give (100 + 100 + 0) / 6 =
        #  33.33 -> 33 over the very same three results.
        record_result(
            api,
            inspections[2]["id"],
            inspector_id,
            build_fail_result_payload(
                deficiency_count=3,
                deficiency_severity_max=4,
                notes="Three bonding deficiencies",
            ),
        )

        review = read_quality_review(api, contractor_id)
        assert review["contractor_id"] == contractor_id
        assert review["rolling_window_score"] == 67
        assert review["severity_weighted_score"] == 33
        assert review["rolling_window_score"] - review["severity_weighted_score"] == 34
        assert review["rolling_window_inspection_count"] == 3
        assert review["weighted_inspection_count"] == 3
        assert review["suspension_threshold"] == DEFAULT_QUALITY_SUSPENSION_THRESHOLD
        assert review["recertification_threshold"] == DEFAULT_RECERTIFICATION_THRESHOLD
        assert review["recertification_eligible"] is False

        #  Only the rolling variant is persisted, and only it suspends.
        contractor = read_contractor(api, contractor_id)
        assert contractor["quality_score_rolling"] == 67
        assert contractor["completed_inspection_count"] == 3
        assert contractor["status"] == ContractorStatus.SUSPENDED
        assert contractor["suspension_reason"] == SuspensionReason.QUALITY_SCORE

        #  A SPOT failure on a project that holds no money moves no project money.
        assert read_project(api, project_id)["status"] == ProjectStatus.DRAFT

    def test_the_365_day_horizon_empties_the_weighted_window_and_leaves_the_rolling_score(
        self, api
    ):
        """The weighted variant forgets a year-old history; the rolling variant never does.

        PRD §3.3: "The **rolling-window** measure takes at most the ten most recent
        candidates in that order, weights each equally, and is the sum of their point
        values divided by the number of candidates counted, rounded half up to a whole
        number. It ignores `deficiency_count` and ignores any date horizon."

        PRD §3.3: "The **severity-weighted** measure is never persisted; it is computed
        on demand. It takes every candidate whose `result_recorded_at` falls at or after
        365 days before the logical clock's instant — with no cap on how many that is —
        and weights each candidate by one plus its `deficiency_count`."

        PRD §3.3: "An empty window yields a score of 100 under either measure."

        PRD §3.3: "This variant has no side effect of its own; it decides only whether
        the contractor remains recertification-eligible, which is true when the weighted
        score is greater than or equal to the program's `recertification_threshold`."

        PRD §3.8: "Every branch stamps `result_recorded_at` from the logical clock and
        `recorded_by_user_id` with the acting identifier, recomputes the contractor's
        `quality_score_rolling` and `completed_inspection_count`, and increments the
        inspection's version."

        Design: Difficulty/dual_variant_calc/rolling_window_vs_severity_weighted_contractor_quality
        """
        world = build_world(api, stage="project", catalog=[build_hvac_heat_pump_payload()])
        contractor_id = world["contractor_id"]
        inspector_id = create_inspector(api, world["program_id"])["id"]

        #  All three results are stamped at the clock's 2026-08-01T00:00:00Z default.
        windows = [
            ("2026-09-01T09:00:00Z", "2026-09-01T10:00:00Z"),
            ("2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z"),
            ("2026-09-03T09:00:00Z", "2026-09-03T10:00:00Z"),
        ]
        payloads = [
            build_pass_result_payload(),
            build_pass_result_payload(),
            build_fail_result_payload(deficiency_count=3, deficiency_severity_max=4),
        ]
        for (start, end), payload in zip(windows, payloads):
            inspection = schedule_inspection(
                api,
                world["project_id"],
                inspector_id,
                InspectionType.SPOT,
                scheduled_start=start,
                scheduled_end=end,
            )
            recorded = record_result(api, inspection["id"], inspector_id, payload)
            assert recorded["result_recorded_at"].startswith("2026-08-01T00:00:00")

        #  Exactly 365 days later the horizon opens at 2026-08-01T00:00:00Z, and the
        #  lower bound is inclusive, so all three candidates are still weighted.
        set_clock(api, "2027-08-01T00:00:00Z")
        on_the_boundary = read_quality_review(api, contractor_id)
        assert on_the_boundary["rolling_window_score"] == 67
        assert on_the_boundary["severity_weighted_score"] == 33
        assert on_the_boundary["rolling_window_inspection_count"] == 3
        assert on_the_boundary["weighted_inspection_count"] == 3
        assert on_the_boundary["recertification_eligible"] is False

        #  One day past the horizon the weighted window is empty and scores 100, while
        #  the rolling window, which has no horizon, still reports the same 67.
        set_clock(api, "2027-08-02T00:00:00Z")
        past_the_horizon = read_quality_review(api, contractor_id)
        assert past_the_horizon["rolling_window_score"] == 67
        assert past_the_horizon["rolling_window_inspection_count"] == 3
        assert past_the_horizon["severity_weighted_score"] == 100
        assert past_the_horizon["weighted_inspection_count"] == 0
        assert past_the_horizon["recertification_eligible"] is True
        assert past_the_horizon["suspension_threshold"] == DEFAULT_QUALITY_SUSPENSION_THRESHOLD
        assert past_the_horizon["recertification_threshold"] == DEFAULT_RECERTIFICATION_THRESHOLD

        #  Neither read is a write: the persisted rolling score and the suspension the
        #  rolling variant caused are exactly where the last recorded result left them.
        contractor = read_contractor(api, contractor_id)
        assert contractor["quality_score_rolling"] == 67
        assert contractor["completed_inspection_count"] == 3
        assert contractor["status"] == ContractorStatus.SUSPENDED
        assert contractor["suspension_reason"] == SuspensionReason.QUALITY_SCORE
