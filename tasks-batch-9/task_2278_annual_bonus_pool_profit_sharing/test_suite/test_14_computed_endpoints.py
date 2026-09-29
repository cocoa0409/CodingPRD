"""Computed reads, the re-runnable bulk build, and the gates on the endpoints."""

from test_helpers import (
    FC,
    HR,
    PA,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_pct,
    assert_ratio,
    build_funded_scenario,
    build_locked_scenario,
    build_setup_scenario,
    dispute_payload,
    payout_run_payload,
    settle_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

_L3_AND_L5 = (
    {"job_level": "L3", "target_bonus_pct": 10.00},
    {"job_level": "L5", "target_bonus_pct": 20.00},
)
_TWO_METRICS = (
    {
        "metric_code": "REVENUE",
        "weight_pct": 60.00,
        "threshold_value": 900,
        "target_value": 1000,
        "max_value": 1200,
    },
    {
        "metric_code": "EBITDA",
        "weight_pct": 40.00,
        "threshold_value": 90,
        "target_value": 100,
        "max_value": 130,
    },
)
_ADA_AND_BEN = (
    {
        "label": "ada",
        "employee_code": "E881",
        "full_name": "Ada Long",
        "job_level": "L5",
        "base_salary_cents": 20000000,
        "hire_date": "2025-03-01",
    },
    {
        "label": "ben",
        "employee_code": "E882",
        "full_name": "Ben Mid",
        "job_level": "L3",
        "base_salary_cents": 10000000,
        "hire_date": "2026-07-01",
    },
)


class TestFundingSummaryComputedRead:
    def test_the_summary_replays_the_whole_committed_funding_chain(self, api):
        """PRD §4: "Computed read of the whole funding chain: achievements, multiplier,
        funded total, rounding delta, discretionary budget and usage, accrual ledger and
        governance posture." And PRD §3.4: "First, `company_achievement_pct` is the sum,
        over every company metric of the plan in `ACTUAL_ENTERED`, of that metric's
        `weight_pct` divided by 100 and multiplied by its `achievement_pct`; each term is
        kept at full precision and only the total is rounded half up to two decimals." And
        PRD §3.4: "The curve is inclusive at the bottom of each band: exactly 80.00 funds
        at 0.5000 rather than 0.0000, exactly 100.00 funds at 1.0000, and exactly 120.00
        funds at the 1.5000 cap." And PRD §3.4: "Once funded, each pool has money but
        nothing allocated, so its `distribution_status` becomes `UNDER_UTILIZED` (pools
        with an `eligible_headcount` of 0 stay `NO_ELIGIBLE_PARTICIPANTS`), the plan's
        `under_utilized_pool_count` is recomputed accordingly, and `governance_posture`
        becomes `FLAGGED` for as long as any pool remains under-utilized."

        Design: Corner/endpoints/funding_summary_computed_read_matches_the_certified_chain
        """
        scenario = build_funded_scenario(
            units=("UNIT-J1",),
            plan_overrides={"plan_name": "FY26 Funding Summary Plan"},
            targets=_L3_AND_L5,
            metrics=_TWO_METRICS,
            metric_actuals={"REVENUE": 900, "EBITDA": 95},
            scorecards={"UNIT-J1": 100.00},
            participants=_ADA_AND_BEN,
        )

        revenue = validate_success(
            api.get_company_metric(scenario.metrics["REVENUE"]["id"], PA)
        )
        ebitda = validate_success(
            api.get_company_metric(scenario.metrics["EBITDA"]["id"], PA)
        )
        assert_pct(revenue["achievement_pct"], 50.00)
        assert_pct(ebitda["achievement_pct"], 75.00)

        version_before = scenario.refresh_plan()["version"]

        summary = validate_success(api.get_funding_summary(scenario.plan_id, FC))
        assert_pct(summary["company_achievement_pct"], 60.00)
        assert_pct(summary["bu_weighted_achievement_pct"], 100.00)
        assert_pct(summary["blended_achievement_pct"], 80.00)
        assert_ratio(summary["funding_multiplier"], 0.5000)
        assert summary["total_target_cents"] == 4504110
        assert summary["funded_pool_cents"] == 2252055
        assert summary["aggregate_rounding_delta_cents"] == 0
        assert summary["discretionary_budget_cents"] == 225206
        assert summary["discretionary_used_cents"] == 0
        assert summary["accrued_total_cents"] == 0
        # Nothing has been allocated yet, so the funded pool is still under-utilized.
        assert summary["governance_posture"] == "FLAGGED"

        pool = scenario.refresh_pool("UNIT-J1")
        assert pool["funded_cents"] == 2252055
        assert pool["min_utilization_cents"] == 2240794

        assert scenario.refresh_plan()["version"] == version_before


class TestPayoutPreviewComputedRead:
    def test_the_retirees_preview_forfeits_while_the_stored_award_stays_pending(
        self, api
    ):
        """PRD §3.9: "Under `STRICT_PAYMENT_DATE`, an award pays its `final_award_cents` if
        the participant was employed on the payment date and pays 0 otherwise: any
        termination before the payment date forfeits the whole award regardless of reason,
        and the retiree and the resigner are treated identically." And PRD §3.9: "a verdict
        amount of 0 moves the award from `PENDING` to `FORFEITED` with `payout_amount_cents`
        set to 0, contributing its `final_award_cents` to `forfeited_award_count` and
        `total_forfeited_cents`." And PRD §3.9: "Before executing, any authorized reader may
        ask for a single award's payout preview, a computed read that reports what the
        verdict would be under the plan's active policy while changing nothing."

        Design: Corner/endpoints/payout_preview_computed_read_shows_forfeiture_without_paying
        """

        def retire_hook(scenario):
            scenario.add_termination(
                "rita", "2026-06-30", "RETIREMENT", note="retired mid-year"
            )

        scenario = build_funded_scenario(
            units=("UNIT-J2",),
            plan_overrides={"plan_name": "FY26 Payout Preview Plan"},
            participants=(
                {
                    "label": "rita",
                    "employee_code": "E883",
                    "full_name": "Rita Ires",
                    "job_level": "L5",
                    "base_salary_cents": 20000000,
                    "hire_date": "2025-03-01",
                },
            ),
            hook=retire_hook,
        )
        scenario.propose("rita", 1983562, allocation_rationale="full remaining target")

        assert (
            scenario.refresh_plan()["termination_treatment_policy"]
            == "STRICT_PAYMENT_DATE"
        )
        award = scenario.refresh_award("rita")
        assert award["eligibility_status"] == "GOOD_LEAVER"
        assert award["credited_days"] == 181
        assert award["prorated_target_cents"] == 1983562
        assert award["final_award_cents"] == 1983562
        version_before = award["version"]

        preview = validate_success(
            api.get_payout_preview(scenario.award_id("rita"), FC)
        )
        assert preview["payout_amount_cents"] == 0
        assert preview["payment_status"] == "FORFEITED"

        stored = scenario.refresh_award("rita")
        assert stored["payment_status"] == "PENDING"
        assert stored["payout_amount_cents"] == 0
        assert stored["version"] == version_before

        plan = scenario.refresh_plan()
        assert plan["forfeited_total_cents"] == 0
        assert plan["paid_total_cents"] == 0


class TestBulkTargetAssignment:
    def test_the_ineligible_row_is_still_built_and_a_second_run_refreshes_in_place(
        self, api
    ):
        """PRD §3.3: "It may also be re-run while the plan is already in `TARGETS_SET`, as
        a self-transition from `TARGETS_SET` to `TARGETS_SET`; that is the only way to
        refresh proration in bulk after transfer or leave corrections, and it updates
        existing award rows in place, preserving each award's `id` while incrementing its
        `version`." And PRD §3.3: "A participant credited with fewer than 90 days is
        `INELIGIBLE_MIN_SERVICE`, and their `prorated_target_cents` is forced to 0; exactly
        90 credited days is eligible, and 89 is not."

        Design: Corner/endpoints/bulk_target_assignment_is_skip_not_fail_and_is_re_runnable
        """
        scenario = build_setup_scenario(
            units=("UNIT-J3",),
            plan_overrides={"plan_name": "FY26 Bulk Assignment Plan"},
            targets=_L3_AND_L5,
            participants=_ADA_AND_BEN
            + (
                {
                    "label": "newt",
                    "employee_code": "E886",
                    "full_name": "Newt Short",
                    "job_level": "L3",
                    "base_salary_cents": 10000000,
                    "hire_date": "2026-10-04",
                },
            ),
        )

        first = validate_success(api.run_target_assignments(scenario.plan_id, PA))
        assert first["status"] == "TARGETS_SET"
        assert first["total_target_cents"] == 4504110

        rows, meta = validate_paginated(
            api.list_participant_awards(PA, params={"plan_id": scenario.plan_id})
        )
        assert meta["total_count"] == 3
        first_ids = sorted(row["id"] for row in rows)

        by_participant = {row["participant_id"]: row for row in rows}
        ben = by_participant[scenario.participant_id("ben")]
        assert ben["credited_days"] == 184
        assert ben["prorated_target_cents"] == 504110
        newt = by_participant[scenario.participant_id("newt")]
        assert newt["eligibility_status"] == "INELIGIBLE_MIN_SERVICE"
        assert newt["prorated_target_cents"] == 0

        pool = scenario.refresh_pool("UNIT-J3")
        assert pool["eligible_headcount"] == 2
        assert pool["eligible_target_cents"] == 4504110

        second = validate_success(api.run_target_assignments(scenario.plan_id, PA))
        assert second["status"] == "TARGETS_SET"
        assert second["total_target_cents"] == 4504110

        rows, meta = validate_paginated(
            api.list_participant_awards(PA, params={"plan_id": scenario.plan_id})
        )
        assert meta["total_count"] == 3
        assert sorted(row["id"] for row in rows) == first_ids


class TestDisputeCrossReferences:
    def test_each_unknown_reference_answers_with_its_own_not_found(self, api):
        """PRD §2.9: "References supplied in a request body are resolved after the body has
        been checked for shape, and they are resolved in the order the fields are declared
        on the resource being written: `plan_id` first, then `participant_id`, then
        `business_unit_id` or `new_business_unit_id`, then `bu_pool_id`, then `award_id`,
        then `supersedes_event_id`." And PRD §2.9: "Each unresolved reference raises its own
        not-found error — `ERR_PLAN_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`,
        `ERR_BUSINESS_UNIT_NOT_FOUND`, `ERR_POOL_NOT_FOUND`, `ERR_AWARD_NOT_FOUND` and
        `ERR_EVENT_NOT_FOUND` respectively." And PRD §2.10: "5. **Body references**,
        resolved in declaration order as described in §2.9."

        Design: Corner/endpoints/dispute_cross_reference_ids_must_all_resolve
        """
        scenario = build_funded_scenario(
            units=("J4",), plan_overrides={"plan_name": "FY26 Dispute Reference Plan"}
        )
        plan_id = scenario.plan_id
        award_id = scenario.award_id("ada")
        participant_id = scenario.participant_id("ada")
        employee = scenario.employee_headers("ada")

        # The plan is still ALLOCATION_OPEN, so even a well-formed filing is premature.
        unknown_plan = api.create_dispute(
            dispute_payload(
                NON_EXISTENT_UUID,
                award_id,
                participant_id,
                dispute_reason="unknown plan",
            ),
            employee,
        )
        error = validate_error(
            unknown_plan, ApiErrorId.ERR_PLAN_NOT_FOUND.value, expected_status=404
        )
        assert error["error_id"] != ApiErrorId.ERR_DISPUTE_NOT_ALLOWED_YET.value

        unknown_award = api.create_dispute(
            dispute_payload(
                plan_id,
                NON_EXISTENT_UUID,
                participant_id,
                dispute_reason="unknown award",
            ),
            employee,
        )
        error = validate_error(
            unknown_award, ApiErrorId.ERR_AWARD_NOT_FOUND.value, expected_status=404
        )
        assert error["error_id"] != ApiErrorId.ERR_DISPUTE_NOT_ALLOWED_YET.value

        unknown_participant = api.create_dispute(
            dispute_payload(
                plan_id,
                award_id,
                NON_EXISTENT_UUID,
                dispute_reason="unknown participant",
            ),
            employee,
        )
        error = validate_error(
            unknown_participant,
            ApiErrorId.ERR_PARTICIPANT_NOT_FOUND.value,
            expected_status=404,
        )
        assert error["error_id"] != ApiErrorId.ERR_DISPUTE_NOT_ALLOWED_YET.value

        _, meta = validate_paginated(
            api.list_disputes(HR, params={"plan_id": plan_id})
        )
        assert meta["total_count"] == 0


class TestSettlementOrdering:
    def test_a_locked_plan_is_not_yet_a_paid_plan(self, api):
        """PRD §3.9: "At most one run may exist per plan; a second attempt is refused
        with `ERR_PAYOUT_ALREADY_EXECUTED`, as is executing a run that is not in `DRAFT`
        or settling one that is not in `EXECUTED`." And PRD §3.9: "`true_up_cents` is then
        `paid_total_cents` plus `settlement_burden_cents`, minus the plan's
        `accrued_total_cents`, and it is signed — positive when the year was under-accrued,
        negative when it was over-accrued."

        The run here is still in `DRAFT`, so the run-state check is the earliest ladder
        position violated: PRD §2.10 orders "the payout run's state permitting execution
        or settlement and only one run existing per plan (`ERR_PAYOUT_ALREADY_EXECUTED`)"
        *before* "the plan being locked to execute and paid out to settle
        (`ERR_PLAN_NOT_LOCKED`)".

        Design: Corner/endpoints/settlement_before_execution_rejected
        """
        scenario = build_locked_scenario(
            units=("J5",), plan_overrides={"plan_name": "FY26 Settle Order Plan"}
        )
        run = validate_success(
            api.create_payout_run(
                payout_run_payload(scenario.plan_id, run_note="FY26 run"), FC
            ),
            expected_status=201,
        )

        settlement = api.settle_true_up(
            run["id"], FC, settle_payload(settlement_note="settling before paying")
        )
        validate_error(
            settlement, ApiErrorId.ERR_PAYOUT_ALREADY_EXECUTED.value, expected_status=409
        )

        stored = validate_success(api.get_payout_run(run["id"], FC))
        assert stored["status"] == "DRAFT"
        assert stored["true_up_cents"] == 0
        assert stored["settlement_burden_cents"] == 0

        plan = scenario.refresh_plan()
        assert plan["status"] == "LOCKED"
        assert plan["locked_total_cents"] == 4000000
        assert plan["true_up_cents"] == 0
        assert plan["paid_total_cents"] == 0
