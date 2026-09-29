"""Formula corners: the blend, the filtered input set, the constants and the closure."""

from test_helpers import (
    CC_ADJUDICATOR,
    FC,
    HR,
    PA,
    adjustment_decision_payload,
    assert_pct,
    assert_ratio,
    build_funded_scenario,
    build_settled_scenario,
    build_targets_set_scenario,
    discretionary_adjustment_payload,
    make_committee_headers,
    validate_paginated,
    validate_success,
)

_L3_ONLY = ({"job_level": "L3", "target_bonus_pct": 10.00},)
_L3_AND_L5 = (
    {"job_level": "L3", "target_bonus_pct": 10.00},
    {"job_level": "L5", "target_bonus_pct": 20.00},
)
_ONE_REVENUE_METRIC = (
    {
        "metric_code": "REVENUE",
        "weight_pct": 100.00,
        "threshold_value": 900,
        "target_value": 1000,
        "max_value": 1200,
    },
)


class TestTheThreePillarBlend:
    def test_the_individual_pillar_funds_at_unity_inside_the_weighted_blend(self, api):
        """PRD §3.4: "Third, `blended_achievement_pct` is the sum of three weighted terms,
        rounded half up to two decimals on the total only: `company_weight_pct` divided by
        100 times `company_achievement_pct`, plus `business_unit_weight_pct` divided by 100
        times `bu_weighted_achievement_pct`, plus `individual_weight_pct` divided by 100
        times a fixed 100.00." And PRD §3.4: "`discretionary_budget_cents` is then
        `funded_pool_cents` multiplied by `discretionary_budget_pct`, divided by 100 and
        rounded half up to whole cents — on a pool of 10,000,000 cents at the default
        reserve of one tenth, that is 1,000,000 cents of discretionary authority."

        Design: Corner/calculations/blended_achievement_blends_company_bu_and_a_unity_individual_pillar
        """
        scenario = build_funded_scenario(
            units=("UNIT-C1",),
            plan_overrides={
                "plan_name": "FY26 Blend Plan",
                "company_weight_pct": 50.00,
                "business_unit_weight_pct": 30.00,
                "individual_weight_pct": 20.00,
            },
            targets=_L3_ONLY,
            metrics=_ONE_REVENUE_METRIC,
            metric_actuals={"REVENUE": 1040},
            scorecards={"UNIT-C1": 150.00},
            participants=(
                {
                    "label": "one",
                    "employee_code": "E701",
                    "full_name": "Cal One",
                    "job_level": "L3",
                    "base_salary_cents": 10000000,
                    "hire_date": "2025-01-01",
                },
                {
                    "label": "two",
                    "employee_code": "E702",
                    "full_name": "Cal Two",
                    "job_level": "L3",
                    "base_salary_cents": 10000000,
                    "hire_date": "2025-01-01",
                },
            ),
        )

        metric = validate_success(
            api.get_company_metric(scenario.metrics["REVENUE"]["id"], PA)
        )
        assert_pct(metric["achievement_pct"], 110.00)

        plan = scenario.refresh_plan()
        assert_pct(plan["company_achievement_pct"], 110.00)
        assert_pct(plan["blended_achievement_pct"], 120.00)
        assert_ratio(plan["funding_multiplier"], 1.5000)
        assert plan["total_target_cents"] == 2000000
        assert plan["funded_pool_cents"] == 3000000
        assert plan["discretionary_budget_cents"] == 300000

        pool = scenario.refresh_pool("UNIT-C1")
        assert_pct(pool["bu_metric_achievement_pct"], 150.00)
        assert pool["funded_cents"] == 3000000
        assert pool["min_utilization_cents"] == 2985000
        assert pool["max_top_tier_count"] == 1


class TestTheFilteredTargetInputSet:
    def test_the_eighty_nine_day_award_exists_and_still_funds_nothing(self, api):
        """PRD §3.3: "A participant credited with fewer than 90 days is
        `INELIGIBLE_MIN_SERVICE`, and their `prorated_target_cents` is forced to 0; exactly
        90 credited days is eligible, and 89 is not." And PRD §3.3: "Because the awards
        changed, each pool immediately recomputes `eligible_target_cents` as the sum of
        `prorated_target_cents` over its awards whose `eligibility_status` is anything other
        than `INELIGIBLE_MIN_SERVICE`, and `eligible_headcount` as the count of those same
        awards, along with `max_top_tier_count`, `allocated_cents`, `available_cents` and
        `distribution_status`."

        Design: Corner/calculations/input_set_filtering_excludes_the_eighty_nine_day_participant
        """
        scenario = build_funded_scenario(
            units=("UNIT-C2",),
            plan_overrides={"plan_name": "FY26 Filtering Plan"},
            targets=_L3_AND_L5,
            metrics=_ONE_REVENUE_METRIC,
            participants=(
                {
                    "label": "ada",
                    "employee_code": "E703",
                    "full_name": "Ada Long",
                    "job_level": "L5",
                    "base_salary_cents": 20000000,
                    "hire_date": "2025-03-01",
                },
                {
                    "label": "newt",
                    "employee_code": "E704",
                    "full_name": "Newt Short",
                    "job_level": "L3",
                    "base_salary_cents": 10000000,
                    "hire_date": "2026-10-04",
                },
            ),
        )

        short = scenario.refresh_award("newt")
        assert short["eligibility_status"] == "INELIGIBLE_MIN_SERVICE"
        assert short["credited_days"] == 89
        assert short["prorated_target_cents"] == 0

        plan = scenario.refresh_plan()
        assert plan["total_target_cents"] == 4000000
        assert_ratio(plan["funding_multiplier"], 1.0000)
        assert plan["funded_pool_cents"] == 4000000

        pool = scenario.refresh_pool("UNIT-C2")
        assert pool["eligible_headcount"] == 1
        assert pool["max_top_tier_count"] == 1

        _, meta = validate_paginated(
            api.list_participant_awards(PA, params={"plan_id": scenario.plan_id})
        )
        assert meta["total_count"] == 2

        _, meta = validate_paginated(
            api.list_participant_awards(
                PA,
                params={"plan_id": scenario.plan_id, "eligibility_status": "ELIGIBLE"},
            )
        )
        assert meta["total_count"] == 1


class TestTheFrozenPerAwardCapFloor:
    def test_the_fifty_thousand_cent_floor_beats_a_quarter_of_a_small_target(self, api):
        """PRD §3.6: "`per_award_cap_cents` is the greater of 50000 cents and a quarter of
        the award's `prorated_target_cents` — the latter computed as `prorated_target_cents`
        multiplied by 25, divided by 100 and rounded half up to whole cents — read at
        creation time and never moved afterwards, so a later re-proration that changes
        `prorated_target_cents` leaves an existing adjustment's frozen cap exactly as it
        was."

        Design: Corner/calculations/discretionary_cap_floor_constant_lifts_a_small_salary_cap
        """
        scenario = build_funded_scenario(
            units=("UNIT-C3",),
            plan_overrides={"plan_name": "FY26 Cap Floor Plan"},
            targets=_L3_AND_L5,
            metrics=_ONE_REVENUE_METRIC,
            participants=(
                {
                    "label": "ada",
                    "employee_code": "E705",
                    "full_name": "Ada Long",
                    "job_level": "L5",
                    "base_salary_cents": 20000000,
                    "hire_date": "2025-03-01",
                },
                {
                    "label": "tiny",
                    "employee_code": "E706",
                    "full_name": "Tiny Wage",
                    "job_level": "L3",
                    "base_salary_cents": 1000000,
                    "hire_date": "2025-01-01",
                },
            ),
        )
        assert scenario.awards["tiny"]["prorated_target_cents"] == 100000
        scenario.propose("ada", 4000000, allocation_rationale="at target")
        scenario.propose("tiny", 100000, allocation_rationale="at target")

        adjustment = validate_success(
            api.create_discretionary_adjustment(
                discretionary_adjustment_payload(
                    scenario.plan_id,
                    scenario.award_id("tiny"),
                    50000,
                    scenario.plan_version(),
                    justification="retention risk on a low-base high-performer",
                ),
                HR,
            ),
            expected_status=201,
        )
        assert adjustment["per_award_cap_cents"] == 50000
        assert adjustment["documentation_ref"] is None

        decided = validate_success(
            api.decide_discretionary_adjustment(
                adjustment["id"],
                adjustment_decision_payload("APPROVE", decision_note="at the floor cap"),
                make_committee_headers(CC_ADJUDICATOR),
            )
        )
        assert decided["status"] == "APPROVED"

        award = scenario.refresh_award("tiny")
        assert award["adjustment_total_cents"] == 50000
        assert award["final_award_cents"] == 150000

        plan = scenario.refresh_plan()
        assert plan["discretionary_used_cents"] == 50000
        assert plan["discretionary_budget_cents"] == 410000
        assert plan["total_target_cents"] == 4100000
        assert plan["funded_pool_cents"] == 4100000


class TestPerPoolRoundingOrder:
    def test_three_half_cent_pools_round_up_apiece_and_book_the_audit_delta(self, api):
        """PRD §2.6: "The second is **pool funding**: each business unit's pool is rounded
        to whole cents separately, and the plan's authoritative `funded_pool_cents` is the
        sum of those already-rounded per-pool figures." And PRD §2.6: "Multiplying the
        plan's whole `total_target_cents` by the multiplier and rounding once is *not* the
        authoritative total — but because auditors ask, the system computes that competing
        figure anyway and stores the signed difference in `aggregate_rounding_delta_cents`:
        the once-rounded product of `total_target_cents` and `funding_multiplier`, minus
        `funded_pool_cents`."

        Design: Corner/calculations/precision_per_pool_rounding_then_sum_exposes_the_aggregate_delta
        """
        units = ("UNIT-D1", "UNIT-D2", "UNIT-D3")
        scenario = build_funded_scenario(
            units=units,
            plan_overrides={"plan_name": "FY26 Rounding Delta Plan"},
            targets=_L3_ONLY,
            metrics=_ONE_REVENUE_METRIC,
            metric_actuals={"REVENUE": 920},
            participants=tuple(
                {
                    "label": f"odd{index}",
                    "unit_code": unit_code,
                    "employee_code": f"E71{index}",
                    "full_name": f"Odd {index}",
                    "job_level": "L3",
                    "base_salary_cents": 10000005,
                    "hire_date": "2025-01-01",
                }
                for index, unit_code in enumerate(units, start=1)
            ),
        )

        plan = scenario.refresh_plan()
        assert_pct(plan["blended_achievement_pct"], 80.00)
        assert_ratio(plan["funding_multiplier"], 0.5000)
        assert plan["total_target_cents"] == 3000003

        for unit_code in units:
            assert scenario.refresh_pool(unit_code)["funded_cents"] == 500001

        assert plan["funded_pool_cents"] == 1500003
        assert plan["aggregate_rounding_delta_cents"] == -1
        assert plan["discretionary_budget_cents"] == 150000


class TestPoolPlacementAndEventOrdering:
    def test_the_whole_award_lands_in_the_destination_unit_pool(self, api):
        """PRD §3.3: "**Pool placement.** Each award's `business_unit_id` is the unit in
        force on the last credited day, and only transfers move a participant between
        pools — leaves and terminations never do." And PRD §3.3: "The award's `bu_pool_id`
        is then the business-unit pool of this plan whose `business_unit_id` equals the
        resolved unit; if no such pool exists the entire target-assignment run is refused
        with `ERR_POOL_MISSING_FOR_UNIT`."

        Design: Corner/calculations/award_pool_assignment_follows_the_unit_in_effect_at_period_end
        """

        def transfer_hook(scenario):
            scenario.add_transfer(
                "mover",
                "2026-07-01",
                "L5",
                20000000,
                "UNIT-E2",
                note="promoted into unit E2",
            )

        scenario = build_targets_set_scenario(
            units=("UNIT-E1", "UNIT-E2"),
            plan_overrides={"plan_name": "FY26 Transfer Pool Plan"},
            targets=_L3_AND_L5,
            metrics=_ONE_REVENUE_METRIC,
            participants=(
                {
                    "label": "mover",
                    "unit_code": "UNIT-E1",
                    "employee_code": "E721",
                    "full_name": "Trans Fer",
                    "job_level": "L3",
                    "base_salary_cents": 10000000,
                    "hire_date": "2025-01-01",
                },
            ),
            hook=transfer_hook,
        )

        award = scenario.refresh_award("mover")
        assert award["bu_pool_id"] == scenario.pool_id("UNIT-E2")
        assert award["business_unit_id"] == scenario.unit_id("UNIT-E2")
        assert award["segment_count"] == 2
        assert award["credited_days"] == 365
        assert_pct(award["target_bonus_pct"], 20.00)
        assert award["prorated_target_cents"] == 2512328
        assert scenario.refresh_plan()["total_target_cents"] == 2512328

        _, meta = validate_paginated(
            api.list_participant_awards(
                PA, params={"bu_pool_id": scenario.pool_id("UNIT-E1")}
            )
        )
        assert meta["total_count"] == 0

        _, meta = validate_paginated(
            api.list_participant_awards(
                PA, params={"bu_pool_id": scenario.pool_id("UNIT-E2")}
            )
        )
        assert meta["total_count"] == 1

        participant = validate_success(
            api.get_participant(scenario.participant_id("mover"), PA)
        )
        assert participant["current_business_unit_id"] == scenario.unit_id("UNIT-E2")
        assert participant["business_unit_id"] == scenario.unit_id("UNIT-E1")

    def test_a_back_filed_leave_prorates_by_its_effective_date_not_its_filing_order(
        self, api
    ):
        """PRD §3.3: "**Segmentation.** The window is cut at every non-superseded
        `TRANSFER` event whose `effective_date` falls strictly after the window's start and
        strictly before its end, taken in ascending `effective_date` order with
        `created_at` ascending breaking ties between transfers sharing a date." And PRD
        §3.3: "For unpaid leave, walk the participant's non-superseded `LEAVE` events whose
        `paid_leave` is false in ascending `effective_date` order with `created_at`
        ascending breaking ties, and collect every calendar date from each event's
        `effective_date` through its `leave_end_date` inclusive that also lies inside the
        participation window." And PRD §2.3: "Two collections deviate: accrual periods are
        returned in ascending `period_start` order, and eligibility events are returned in
        ascending `effective_date` order with `created_at` ascending breaking ties."

        Design: Corner/calculations/chronological_out_of_order_events_still_prorate_identically
        """

        def out_of_order_hook(scenario):
            scenario.add_transfer(
                "late",
                "2026-07-01",
                "L5",
                20000000,
                "UNIT-F1",
                note="recorded first, happens second",
            )
            scenario.add_leave(
                "late",
                "2026-03-01",
                "2026-05-31",
                paid_leave=False,
                note="back-filed unpaid leave",
            )

        scenario = build_targets_set_scenario(
            units=("UNIT-F1",),
            plan_overrides={"plan_name": "FY26 Out Of Order Plan"},
            targets=_L3_AND_L5,
            metrics=_ONE_REVENUE_METRIC,
            participants=(
                {
                    "label": "late",
                    "employee_code": "E731",
                    "full_name": "Late Filed",
                    "job_level": "L3",
                    "base_salary_cents": 10000000,
                    "hire_date": "2025-06-01",
                },
            ),
            hook=out_of_order_hook,
        )

        transfer, leave = scenario.events[0], scenario.events[1]
        assert leave["effective_date"] < transfer["effective_date"]

        # The transfer was recorded first, yet the leave is the earlier event.
        rows, _ = validate_paginated(
            api.list_eligibility_events(
                HR, params={"participant_id": scenario.participant_id("late")}
            )
        )
        assert [row["id"] for row in rows] == [leave["id"], transfer["id"]]

        award = scenario.refresh_award("late")
        assert award["segment_count"] == 2
        assert award["credited_days"] == 303
        assert award["excluded_leave_days"] == 62
        assert_pct(award["target_bonus_pct"], 20.00)
        assert award["prorated_target_cents"] == 2342465
        assert award["eligibility_status"] == "ELIGIBLE"
        assert scenario.refresh_plan()["total_target_cents"] == 2342465


class TestYearEndReconciliation:
    def test_the_true_up_consumes_the_posted_accrual_exactly_once(self, api):
        """PRD §3.9: "`true_up_cents` is then `paid_total_cents` plus
        `settlement_burden_cents`, minus the plan's `accrued_total_cents`, and it is
        signed — positive when the year was under-accrued, negative when it was
        over-accrued." And PRD §3.8: "Posting finally adds `period_accrual_cents` to the
        plan's `accrued_base_cents` and `total_period_cents` to its `accrued_total_cents`."

        Design: Corner/calculations/reconciliation_settles_the_accrual_to_actual_difference
        """

        def accrual_hook(scenario):
            period = scenario.open_accrual_period("2026-01-01", "2026-06-30", 100.00)
            scenario.post_accrual_period(period["id"], posting_note="H1 accrual")

        scenario = build_settled_scenario(
            units=("UNIT-G1",),
            plan_overrides={"plan_name": "FY26 True Up Plan"},
            hook=accrual_hook,
        )

        period = validate_success(
            api.get_accrual_period(scenario.accrual_periods[0]["id"], FC)
        )
        assert period["status"] == "POSTED"
        assert period["provisional_pool_cents"] == 4000000
        assert period["cumulative_accrual_target_cents"] == 1983562
        assert period["burden_cents"] == 151742
        assert period["total_period_cents"] == 2135304

        plan = scenario.refresh_plan()
        assert plan["accrued_total_cents"] == 2135304
        assert plan["paid_total_cents"] == 4000000
        assert plan["settlement_burden_cents"] == 306000
        assert plan["true_up_cents"] == 2170696
        assert plan["status"] == "SETTLED"
        assert scenario.payout_run["status"] == "SETTLED"
