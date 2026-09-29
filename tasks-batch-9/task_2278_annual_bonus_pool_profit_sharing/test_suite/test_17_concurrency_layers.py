"""Version preconditions: what a stale balance costs, and what a clean write bumps."""

from test_helpers import (
    HR,
    PA,
    ApiErrorId,
    assert_pct,
    assert_ratio,
    build_funded_scenario,
    discretionary_adjustment_payload,
    propose_allocation_payload,
    retract_allocation_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

_TWO_L5 = (
    {
        "label": "ada",
        "employee_code": "L921",
        "full_name": "Ada Long",
        "job_level": "L5",
        "base_salary_cents": 20000000,
        "hire_date": "2025-03-01",
    },
    {
        "label": "bea",
        "employee_code": "L922",
        "full_name": "Bea Short",
        "job_level": "L5",
        "base_salary_cents": 20000000,
        "hire_date": "2025-03-01",
    },
)
_L3_ONLY = ({"job_level": "L3", "target_bonus_pct": 10.00},)
_ONE_REVENUE_METRIC = (
    {
        "metric_code": "REVENUE",
        "weight_pct": 100.00,
        "threshold_value": 900,
        "target_value": 1000,
        "max_value": 1200,
    },
)
_TWO_L3 = (
    {
        "label": "ada",
        "employee_code": "L961",
        "full_name": "Ada Long",
        "job_level": "L3",
        "base_salary_cents": 10000000,
        "hire_date": "2025-01-01",
    },
    {
        "label": "bea",
        "employee_code": "L962",
        "full_name": "Bea Short",
        "job_level": "L3",
        "base_salary_cents": 10000000,
        "hire_date": "2025-01-01",
    },
)


class TestStalePoolVersionOnAllocation:
    def test_a_second_manager_spending_the_balance_they_first_read_is_refused(self, api):
        """PRD §2.8: "Allocating money to an award
        (`POST /participant-awards/{awardId}/propose-allocation`) requires
        `expected_pool_version` in the request body, carrying the client's last observed
        `version` of the award's `BusinessUnitPool`." And PRD §2.8: "If it does not match the
        pool's current `version`, the request is rejected with `ERR_STALE_POOL_VERSION`
        (HTTP 412)." And PRD §3.5: "For a non-zero amount, that ratio must be at least the
        `guideline_min_ratio` and at most the `guideline_max_ratio` of the job-level target
        row for the award's level; a ratio outside the band is `ERR_GUIDELINE_RATIO_BREACH`."

        Design: Corner/cross_cutting_complexity_layers/stale_pool_version_on_propose_allocation_rejected
        """
        scenario = build_funded_scenario(
            units=("L2",),
            plan_overrides={"plan_name": "FY26 Stale Propose Plan"},
            participants=_TWO_L5,
        )
        assert scenario.refresh_pool("L2")["funded_cents"] == 8000000

        pool_version_before = scenario.pool_version("L2")
        scenario.propose(
            "ada",
            2000000,
            expected_pool_version=pool_version_before,
            allocation_rationale="first half of the pool for Ada",
        )

        # 2,000,000 of a 4,000,000 target is a ratio of 0.5000, and 6,000,000 is still free.
        stale = api.propose_allocation(
            scenario.award_id("bea"),
            propose_allocation_payload(
                2000000,
                pool_version_before,
                allocation_rationale="second half from a balance already spent against",
            ),
            scenario.manager_headers("L2"),
        )
        error = validate_error(
            stale, ApiErrorId.ERR_STALE_POOL_VERSION.value, expected_status=412
        )
        assert error["error_id"] != ApiErrorId.ERR_GUIDELINE_RATIO_BREACH.value
        assert error["error_id"] != ApiErrorId.ERR_POOL_FUNDS_EXCEEDED.value

        bea = scenario.refresh_award("bea")
        assert bea["allocation_status"] == "UNALLOCATED"
        assert bea["proposed_allocation_cents"] == 0

        ada = scenario.refresh_award("ada")
        assert ada["allocation_status"] == "PROPOSED"
        assert ada["proposed_allocation_cents"] == 2000000

        pool = scenario.refresh_pool("L2")
        assert pool["allocated_cents"] == 2000000
        assert pool["available_cents"] == 6000000
        assert_pct(pool["utilization_pct"], 25.00)
        assert pool["distribution_status"] == "UNDER_UTILIZED"


class TestStalePoolVersionOnRetraction:
    def test_a_retraction_computed_against_a_superseded_balance_is_refused(self, api):
        """PRD §2.8: "Retracting an allocation
        (`POST /participant-awards/{awardId}/retract-allocation`) likewise requires
        `expected_pool_version` carrying the client's last observed pool `version`, and a
        mismatch with the pool's current `version` is rejected with
        `ERR_STALE_POOL_VERSION` (HTTP 412)." And PRD §2.8: "A retraction computed against a
        superseded pool balance is refused rather than silently re-derived."

        Design: Corner/cross_cutting_complexity_layers/stale_pool_version_on_retract_allocation_rejected
        """
        scenario = build_funded_scenario(
            units=("L3",),
            plan_overrides={"plan_name": "FY26 Stale Retract Plan"},
            participants=_TWO_L5,
        )
        scenario.propose("ada", 4000000, allocation_rationale="Ada at target")
        after_first = scenario.pool_version("L3")
        scenario.propose("bea", 4000000, allocation_rationale="Bea at target")

        # Every state and ownership condition on the retraction is satisfied.
        stale = api.retract_allocation(
            scenario.award_id("ada"),
            retract_allocation_payload(
                after_first,
                retraction_reason="undo Ada using the balance read before Bea was paid",
            ),
            scenario.manager_headers("L3"),
        )
        error = validate_error(
            stale, ApiErrorId.ERR_STALE_POOL_VERSION.value, expected_status=412
        )
        assert error["error_id"] != ApiErrorId.ERR_POOL_NOT_ALLOCATING.value
        assert error["error_id"] != ApiErrorId.ERR_AWARD_STATE_INVALID.value
        assert error["error_id"] != ApiErrorId.ERR_AWARD_HAS_APPROVED_ADJUSTMENT.value

        ada = scenario.refresh_award("ada")
        assert ada["allocation_status"] == "PROPOSED"
        assert ada["proposed_allocation_cents"] == 4000000
        assert ada["retraction_count"] == 0

        pool = scenario.refresh_pool("L3")
        assert pool["allocated_cents"] == 8000000
        assert pool["available_cents"] == 0
        assert_pct(pool["utilization_pct"], 100.00)
        assert pool["distribution_status"] == "WITHIN_GUIDELINES"


class TestStalePlanVersionOnAdjustmentFiling:
    def test_an_approval_elsewhere_makes_the_remaining_budget_arithmetic_stale(self, api):
        """PRD §2.8: "Creating a discretionary adjustment (`POST /discretionary-adjustments`)
        requires `expected_plan_version` in the request body, carrying the client's last
        observed `version` of the `BonusPlan` whose `discretionary_budget_cents` and
        `discretionary_used_cents` pair the amount was sized from." And PRD §2.8: "If it does
        not match the plan's current `version`, the create is rejected with
        `ERR_STALE_PLAN_VERSION` (HTTP 412) — once any other adjustment has been approved,
        the remaining-budget arithmetic the new draw was sized from is stale." And PRD §3.6:
        "Approval then fires four money effects: `decided_by_user_id` is set to the acting
        `X-User-ID` and the plan's `discretionary_used_cents` increases by the absolute value
        of `adjustment_cents`; the award's `adjustment_total_cents` increases by the signed
        `adjustment_cents` and its `final_award_cents` becomes `proposed_allocation_cents`
        plus `adjustment_total_cents`; the pool's `allocated_cents`, `available_cents`,
        `utilization_pct` and `distribution_status` are recomputed, which is where a pool may
        tip into `OVER_ALLOCATED`; and the plan's `over_allocated_pool_count` and
        `governance_posture` are recomputed from the resulting pool states."

        Design: Corner/cross_cutting_complexity_layers/stale_plan_version_on_adjustment_creation_rejected
        """
        scenario = build_funded_scenario(
            units=("L4",),
            plan_overrides={"plan_name": "FY26 Stale Plan Version Plan"},
            participants=_TWO_L5,
        )
        assert scenario.refresh_plan()["discretionary_budget_cents"] == 800000
        scenario.propose("ada", 4000000, allocation_rationale="Ada at target")

        plan_version_before = scenario.plan_version()
        first = scenario.file_adjustment(
            "ada",
            100000,
            expected_plan_version=plan_version_before,
            justification="retention uplift sized against the untouched budget",
        )
        approved = scenario.decide_adjustment(
            first["id"], decision_note="committee approves the first draw"
        )
        assert approved["status"] == "APPROVED"

        # An exactly-100,000 draw needs no documentation and is well inside the cap.
        stale = api.create_discretionary_adjustment(
            discretionary_adjustment_payload(
                scenario.plan_id,
                scenario.award_id("ada"),
                100000,
                plan_version_before,
                justification="second draw sized against the same stale budget",
            ),
            HR,
        )
        error = validate_error(
            stale, ApiErrorId.ERR_STALE_PLAN_VERSION.value, expected_status=412
        )
        assert (
            error["error_id"]
            != ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_PER_AWARD_LIMIT.value
        )
        assert error["error_id"] != ApiErrorId.ERR_DISCRETIONARY_BUDGET_EXCEEDED.value
        assert (
            error["error_id"]
            != ApiErrorId.ERR_ADJUSTMENT_DOCUMENTATION_REQUIRED.value
        )
        assert error["error_id"] != ApiErrorId.ERR_AWARD_STATE_INVALID.value

        plan = scenario.refresh_plan()
        assert plan["discretionary_budget_cents"] == 800000
        assert plan["discretionary_used_cents"] == 100000

        stored = validate_success(api.get_discretionary_adjustment(first["id"], PA))
        assert stored["status"] == "APPROVED"

        ada = scenario.refresh_award("ada")
        assert ada["adjustment_total_cents"] == 100000
        assert ada["final_award_cents"] == 4100000
        assert scenario.refresh_pool("L4")["allocated_cents"] == 4100000

        _, meta = validate_paginated(
            api.list_discretionary_adjustments(
                PA, params={"plan_id": scenario.plan_id}
            )
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False


class TestVersionIncrementsOnAnAcceptedWrite:
    def test_one_allocation_moves_both_parent_and_child_forward_by_exactly_one(self, api):
        """PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
        timestamp refreshed on every subsequent write, and `version`, an integer that starts
        at 1 and increments by one on every write that changes any stored field — including
        writes that only change derived roll-up figures such as a pool's `allocated_cents` or
        a plan's `governance_posture`." And PRD §3.5: "A pool sitting in `FUNDED` moves to
        `ALLOCATING` on the first successful allocation against any of its awards."

        Design: Corner/cross_cutting_complexity_layers/pool_and_award_versions_increment_by_one_on_an_accepted_allocation
        """
        scenario = build_funded_scenario(
            units=("L5",),
            plan_overrides={"plan_name": "FY26 Version Increment Plan"},
            participants=_TWO_L5,
        )
        pool_version_before = scenario.pool_version("L5")
        award_version_before = scenario.award_version("ada")

        allocated = validate_success(
            api.propose_allocation(
                scenario.award_id("ada"),
                propose_allocation_payload(
                    4000000,
                    pool_version_before,
                    allocation_rationale="Ada at target",
                ),
                scenario.manager_headers("L5"),
            )
        )
        assert allocated["version"] == award_version_before + 1
        assert allocated["allocation_status"] == "PROPOSED"
        assert_ratio(allocated["allocation_ratio"], 1.0000)

        pool = scenario.refresh_pool("L5")
        assert pool["version"] == pool_version_before + 1
        assert pool["allocated_cents"] == 4000000
        assert pool["available_cents"] == 4000000
        assert pool["calibration_status"] == "ALLOCATING"
        assert pool["top_tier_award_count"] == 0


class TestTopTierConcentrationBoundary:
    def test_two_awards_exactly_on_the_line_break_a_cap_of_one(self, api):
        """PRD §3.5: "`top_tier_award_count` is the number of the pool's awards in
        `PROPOSED`, `CALIBRATED` or `LOCKED` whose `allocation_ratio` is at least 1.50 — a
        ratio of exactly 1.50 does count as top tier — and `max_top_tier_count` is the
        greater of 1 and a quarter of `eligible_headcount` truncated downward, so a unit of
        seven eligible people may nominate at most one top-tier award while a unit of eight
        may nominate two." And PRD §3.7: "And the pool's `top_tier_award_count` must not
        exceed its `max_top_tier_count`, or the submission is refused with
        `ERR_TOP_TIER_CONCENTRATION`." And PRD §3.7: "The pool's `distribution_status` must
        be `WITHIN_GUIDELINES` or `NO_ELIGIBLE_PARTICIPANTS` — an `UNDER_UTILIZED` pool that
        has left money on the table and an `OVER_ALLOCATED` pool that has overspent are both
        refused with `ERR_POOL_NOT_WITHIN_GUIDELINES`."

        Design: Corner/cross_cutting_complexity_layers/top_tier_concentration_threshold_at_the_boundary
        """
        scenario = build_funded_scenario(
            units=("L6",),
            plan_overrides={
                "plan_name": "FY26 Top Tier Concentration Plan",
                "company_weight_pct": 50.00,
                "business_unit_weight_pct": 30.00,
                "individual_weight_pct": 20.00,
            },
            targets=_L3_ONLY,
            metrics=_ONE_REVENUE_METRIC,
            metric_actuals={"REVENUE": 1040},
            scorecards={"L6": 150.00},
            participants=_TWO_L3,
        )
        plan = scenario.refresh_plan()
        assert_pct(plan["blended_achievement_pct"], 120.00)
        assert_ratio(plan["funding_multiplier"], 1.5000)
        assert plan["funded_pool_cents"] == 3000000

        scenario.propose("ada", 1500000, allocation_rationale="top tier for Ada")
        scenario.propose("bea", 1500000, allocation_rationale="top tier for Bea")

        # Both awards sit exactly on the 1.50 line, and the pool is fully spent.
        pool = scenario.refresh_pool("L6")
        assert_pct(pool["utilization_pct"], 100.00)
        assert pool["distribution_status"] == "WITHIN_GUIDELINES"

        crowded = api.submit_calibration(
            scenario.pool_id("L6"), scenario.manager_headers("L6")
        )
        error = validate_error(
            crowded, ApiErrorId.ERR_TOP_TIER_CONCENTRATION.value, expected_status=422
        )
        assert error["error_id"] != ApiErrorId.ERR_POOL_NOT_WITHIN_GUIDELINES.value

        pool = scenario.refresh_pool("L6")
        assert pool["calibration_status"] == "ALLOCATING"
        assert pool["top_tier_award_count"] == 2
        assert pool["max_top_tier_count"] == 1
        assert pool["min_utilization_cents"] == 2985000

        revised = scenario.propose(
            "bea",
            1490000,
            allocation_rationale="just under the top tier line for Bea",
        )
        assert_ratio(revised["allocation_ratio"], 1.4900)

        pool = scenario.refresh_pool("L6")
        assert pool["top_tier_award_count"] == 1
        assert pool["allocated_cents"] == 2990000
        assert pool["available_cents"] == 10000
        assert_pct(pool["utilization_pct"], 99.67)
        assert pool["distribution_status"] == "WITHIN_GUIDELINES"

        submitted = validate_success(
            api.submit_calibration(
                scenario.pool_id("L6"), scenario.manager_headers("L6")
            )
        )
        assert submitted["calibration_status"] == "CALIBRATION_SUBMITTED"
        assert_ratio(scenario.refresh_award("ada")["allocation_ratio"], 1.5000)
