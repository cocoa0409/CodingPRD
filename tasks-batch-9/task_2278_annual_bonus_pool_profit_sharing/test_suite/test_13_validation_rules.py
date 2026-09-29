"""Business rules that refuse a request, and the boundary where they all pass."""

from test_helpers import (
    CC_ADJUDICATOR,
    CC_LOCKER,
    FC,
    HR,
    PA,
    PAYMENT_DATE,
    PAYMENT_DATE_CLOCK,
    ApiErrorId,
    BonusPlanScenario,
    accrual_post_payload,
    accrual_reverse_payload,
    adjustment_decision_payload,
    adjustment_reverse_payload,
    assert_pct,
    bonus_plan_payload,
    build_allocated_scenario,
    build_funded_scenario,
    build_setup_scenario,
    build_targets_set_scenario,
    company_metric_payload,
    discretionary_adjustment_payload,
    leave_event_payload,
    make_committee_headers,
    participant_payload,
    payout_run_payload,
    retract_allocation_payload,
    termination_event_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

_L3_ONLY = ({"job_level": "L3", "target_bonus_pct": 10.00},)
_L5_ONLY = ({"job_level": "L5", "target_bonus_pct": 20.00},)
_ADA = (
    {
        "label": "ada",
        "employee_code": "E851",
        "full_name": "Ada Long",
        "job_level": "L5",
        "base_salary_cents": 20000000,
        "hire_date": "2025-03-01",
    },
)
_ADA_AND_BEA = _ADA + (
    {
        "label": "bea",
        "employee_code": "E852",
        "full_name": "Bea Peer",
        "job_level": "L5",
        "base_salary_cents": 20000000,
        "hire_date": "2025-03-01",
    },
)


class TestFieldRelationshipRules:
    def test_three_field_rules_each_answer_with_their_own_error_id(self, api):
        """PRD §3.1: "They must sum to exactly 100.00 — not 99.99, not 100.01 — and any
        other total is rejected with `ERR_PLAN_WEIGHTS_INVALID`." And PRD §3.1: "A window
        of the wrong length, or a payment date before the end of the window, is rejected
        with `ERR_PLAN_PERIOD_INVALID`." And PRD §3.2: "The band must be strictly
        increasing — `threshold_value` below `target_value` below `max_value` — and
        anything else is `ERR_METRIC_BAND_INVALID`."

        Design: Corner/validations/plan_and_metric_band_field_rules_rejected
        """
        scenario = BonusPlanScenario()
        scenario.create_plan(plan_name="FY26 Field Rules Plan")

        weights = api.create_bonus_plan(
            bonus_plan_payload(
                plan_name="FY26 Bad Weights Plan", individual_weight_pct=10.00
            ),
            PA,
        )
        error = validate_error(
            weights, ApiErrorId.ERR_PLAN_WEIGHTS_INVALID.value, expected_status=422
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

        period = api.create_bonus_plan(
            bonus_plan_payload(
                plan_name="FY26 Bad Period Plan", plan_period_end="2025-01-01"
            ),
            PA,
        )
        error = validate_error(
            period, ApiErrorId.ERR_PLAN_PERIOD_INVALID.value, expected_status=422
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

        band = api.create_company_metric(
            company_metric_payload(
                scenario.plan_id,
                threshold_value=1000,
                target_value=900,
                max_value=1200,
            ),
            PA,
        )
        error = validate_error(
            band, ApiErrorId.ERR_METRIC_BAND_INVALID.value, expected_status=422
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

        _, meta = validate_paginated(
            api.list_bonus_plans(PA, params={"plan_year": 2026})
        )
        assert meta["total_count"] == 1

        _, meta = validate_paginated(
            api.list_company_metrics(PA, params={"plan_id": scenario.plan_id})
        )
        assert meta["total_count"] == 0


class TestEligibilityEventRules:
    def test_four_event_rules_fire_in_the_order_the_ladder_declares(self, api):
        """PRD §3.3: "The `effective_date` must lie inside the half-open plan window — on
        or after `plan_period_start` and strictly before `plan_period_end` — or the event
        is refused with `ERR_EVENT_DATE_OUTSIDE_PLAN_PERIOD`." And PRD §3.3: "It must also
        fall on or after the participant's `hire_date`, and a `LEAVE` must not end before
        it starts, or the event is refused with `ERR_EVENT_DATE_BEFORE_HIRE`." And PRD
        §3.3: "And once a participant carries a live termination, no event may be recorded
        with an `effective_date` strictly after that termination's `effective_date`, and a
        second termination is refused unless it supersedes the first — both cases report
        `ERR_PARTICIPANT_ALREADY_TERMINATED`." And PRD §3.3: "The named event must belong
        to the *same* participant and must not already be superseded, or the correction is
        refused with `ERR_SUPERSEDES_EVENT_INVALID`."

        Design: Corner/validations/eligibility_event_temporal_and_referential_rules_rejected
        """
        scenario = BonusPlanScenario()
        scenario.add_unit("UNIT-H1", name="Unit H1")
        scenario.create_plan(plan_name="FY26 Event Temporal Plan")
        scenario.add_target("L5", target_bonus_pct=20.00)
        scenario.add_participant(
            "eve",
            "UNIT-H1",
            employee_code="E811",
            full_name="Eve Ent",
            job_level="L5",
            base_salary_cents=20000000,
            hire_date="2026-02-01",
        )
        scenario.add_participant(
            "otto",
            "UNIT-H1",
            employee_code="E812",
            full_name="Otto Ther",
            job_level="L5",
            base_salary_cents=20000000,
            hire_date="2025-01-01",
        )
        other_leave = scenario.add_leave(
            "otto", "2026-03-01", "2026-03-31", paid_leave=True, note="other leave"
        )
        eve_id = scenario.participant_id("eve")

        # 2027-01-01 is the exclusive end of the window, so it lies outside it.
        outside = api.create_eligibility_event(
            leave_event_payload(
                eve_id,
                "2027-01-01",
                "2027-01-31",
                note="starts on the exclusive end bound",
            ),
            HR,
        )
        validate_error(
            outside,
            ApiErrorId.ERR_EVENT_DATE_OUTSIDE_PLAN_PERIOD.value,
            expected_status=422,
        )

        before_hire = api.create_eligibility_event(
            leave_event_payload(
                eve_id, "2026-01-15", "2026-01-20", note="before the hire date"
            ),
            HR,
        )
        validate_error(
            before_hire,
            ApiErrorId.ERR_EVENT_DATE_BEFORE_HIRE.value,
            expected_status=422,
        )

        termination = validate_success(
            api.create_eligibility_event(
                termination_event_payload(
                    eve_id, "2026-09-30", "VOLUNTARY_RESIGNATION", note="resigned"
                ),
                HR,
            ),
            expected_status=201,
        )
        assert termination["event_type"] == "TERMINATION"

        after_termination = api.create_eligibility_event(
            leave_event_payload(
                eve_id, "2026-10-01", "2026-10-15", note="after the termination"
            ),
            HR,
        )
        validate_error(
            after_termination,
            ApiErrorId.ERR_PARTICIPANT_ALREADY_TERMINATED.value,
            expected_status=409,
        )

        # Dated before the live termination, so only the second-termination rule bites.
        second_termination = api.create_eligibility_event(
            termination_event_payload(
                eve_id, "2026-08-31", "REDUNDANCY", note="second termination"
            ),
            HR,
        )
        validate_error(
            second_termination,
            ApiErrorId.ERR_PARTICIPANT_ALREADY_TERMINATED.value,
            expected_status=409,
        )

        foreign_supersede = api.create_eligibility_event(
            leave_event_payload(
                eve_id,
                "2026-05-01",
                "2026-05-10",
                supersedes_event_id=other_leave["id"],
                note="supersedes another participants event",
            ),
            HR,
        )
        validate_error(
            foreign_supersede,
            ApiErrorId.ERR_SUPERSEDES_EVENT_INVALID.value,
            expected_status=422,
        )

        assert (
            validate_success(api.get_eligibility_event(other_leave["id"], HR))[
                "superseded"
            ]
            is False
        )

        participant = validate_success(api.get_participant(eve_id, PA))
        assert participant["employment_status"] == "TERMINATED"
        assert participant["termination_date"] == "2026-09-30"

        _, meta = validate_paginated(
            api.list_eligibility_events(HR, params={"participant_id": eve_id})
        )
        assert meta["total_count"] == 1


class TestTargetAssignmentReferentialGates:
    def test_a_missing_target_row_and_a_missing_pool_each_void_the_whole_run(self, api):
        """PRD §3.3: "If a participant holds a job level on any segment for which the plan
        has no job-level target row, the whole run is refused with
        `ERR_JOB_LEVEL_TARGET_MISSING`." And PRD §3.3: "The award's `bu_pool_id` is then
        the business-unit pool of this plan whose `business_unit_id` equals the resolved
        unit; if no such pool exists the entire target-assignment run is refused with
        `ERR_POOL_MISSING_FOR_UNIT`."

        Design: Corner/validations/target_assignment_referential_gates_rejected
        """
        no_target = build_setup_scenario(
            units=("UNIT-H2",),
            plan_overrides={"plan_name": "FY26 Missing Target Plan"},
            targets=_L5_ONLY,
            participants=(
                {
                    "label": "level3",
                    "employee_code": "E821",
                    "full_name": "No Target",
                    "job_level": "L3",
                    "base_salary_cents": 10000000,
                    "hire_date": "2025-01-01",
                },
            ),
        )
        no_pool = build_setup_scenario(
            units=("UNIT-H3", "UNIT-H4"),
            plan_overrides={"plan_name": "FY26 Missing Pool Plan"},
            targets=_L3_ONLY,
            pooled_units=("UNIT-H3",),
            participants=(
                {
                    "label": "unpooled",
                    "unit_code": "UNIT-H4",
                    "employee_code": "E822",
                    "full_name": "No Pool",
                    "job_level": "L3",
                    "base_salary_cents": 10000000,
                    "hire_date": "2025-01-01",
                },
            ),
        )

        validate_error(
            api.run_target_assignments(no_target.plan_id, PA),
            ApiErrorId.ERR_JOB_LEVEL_TARGET_MISSING.value,
            expected_status=422,
        )
        validate_error(
            api.run_target_assignments(no_pool.plan_id, PA),
            ApiErrorId.ERR_POOL_MISSING_FOR_UNIT.value,
            expected_status=422,
        )

        for scenario in (no_target, no_pool):
            plan = scenario.refresh_plan()
            assert plan["status"] == "DRAFT"
            assert plan["total_target_cents"] == 0

            _, meta = validate_paginated(
                api.list_participant_awards(PA, params={"plan_id": scenario.plan_id})
            )
            assert meta["total_count"] == 0


class TestCertificationCascade:
    def test_each_repaired_defect_uncovers_the_next_gate_down_the_ladder(self, api):
        """PRD §3.4: "Four conditions must hold, and they are checked in the ladder order
        of §2.10: the plan's company-metric weights must sum to exactly 100.00 and at
        least one metric must exist (`ERR_METRIC_WEIGHTS_INVALID`); every company metric
        of the plan must be in `ACTUAL_ENTERED` (`ERR_METRICS_NOT_ALL_ACTUALIZED`); every
        business-unit pool of the plan must be in `SCORECARD_CERTIFIED`
        (`ERR_SCORECARDS_NOT_ALL_CERTIFIED`); and `total_target_cents` must be greater
        than 0, meaning at least one award survived the ninety-day minimum-service gate
        (`ERR_NO_ELIGIBLE_PARTICIPANTS`)." And PRD §3.4: "Submission moves no money — it
        only increments the plan's `version`."

        Design: Corner/validations/certification_gates_are_checked_in_cascade_order
        """
        scenario = BonusPlanScenario()
        scenario.add_unit("UNIT-H5", name="Unit H5")
        scenario.create_plan(plan_name="FY26 Certification Gates Plan")
        scenario.add_target("L5", target_bonus_pct=20.00)
        scenario.add_metric("REVENUE", weight_pct=60.00)
        scenario.add_pool("UNIT-H5")
        scenario.add_participant(
            "ada",
            "UNIT-H5",
            employee_code="E831",
            full_name="Ada Long",
            job_level="L5",
            base_salary_cents=20000000,
            hire_date="2025-03-01",
        )
        scenario.assign_targets()

        validate_error(
            api.submit_plan_for_certification(scenario.plan_id, PA),
            ApiErrorId.ERR_METRIC_WEIGHTS_INVALID.value,
            expected_status=422,
        )

        scenario.add_metric(
            "EBITDA",
            weight_pct=40.00,
            threshold_value=90,
            target_value=100,
            max_value=130,
        )
        error = validate_error(
            api.submit_plan_for_certification(scenario.plan_id, PA),
            ApiErrorId.ERR_METRICS_NOT_ALL_ACTUALIZED.value,
            expected_status=409,
        )
        # The scorecard is still DRAFT here, yet the actuals rule outranks it.
        assert error["error_id"] != ApiErrorId.ERR_SCORECARDS_NOT_ALL_CERTIFIED.value

        scenario.file_actual("REVENUE", 1000, source_note="audited revenue")
        scenario.file_actual("EBITDA", 100, source_note="audited ebitda")
        validate_error(
            api.submit_plan_for_certification(scenario.plan_id, PA),
            ApiErrorId.ERR_SCORECARDS_NOT_ALL_CERTIFIED.value,
            expected_status=409,
        )

        scenario.submit_scorecard("UNIT-H5", 100.00, scorecard_narrative="at plan")
        scenario.decide_scorecard("UNIT-H5", "CERTIFY")

        submitted = validate_success(
            api.submit_plan_for_certification(scenario.plan_id, PA)
        )
        assert submitted["status"] == "PENDING_CERTIFICATION"
        assert submitted["total_target_cents"] == 4000000
        assert_pct(submitted["company_achievement_pct"], 0.00)


class TestCertificationNeedsAPositiveTarget:
    def test_a_single_eighty_nine_day_participant_cannot_be_certified(self, api):
        """PRD §3.3: "A participant credited with fewer than 90 days is
        `INELIGIBLE_MIN_SERVICE`, and their `prorated_target_cents` is forced to 0; exactly
        90 credited days is eligible, and 89 is not." And PRD §3.4: "Four conditions must
        hold, and they are checked in the ladder order of §2.10: the plan's company-metric
        weights must sum to exactly 100.00 and at least one metric must exist
        (`ERR_METRIC_WEIGHTS_INVALID`); every company metric of the plan must be in
        `ACTUAL_ENTERED` (`ERR_METRICS_NOT_ALL_ACTUALIZED`); every business-unit pool of
        the plan must be in `SCORECARD_CERTIFIED` (`ERR_SCORECARDS_NOT_ALL_CERTIFIED`);
        and `total_target_cents` must be greater than 0, meaning at least one award
        survived the ninety-day minimum-service gate (`ERR_NO_ELIGIBLE_PARTICIPANTS`)."

        Design: Corner/validations/certification_without_any_eligible_participant_rejected
        """
        scenario = build_targets_set_scenario(
            units=("UNIT-H6",),
            plan_overrides={"plan_name": "FY26 No Eligible Plan"},
            targets=_L3_ONLY,
            participants=(
                {
                    "label": "newt",
                    "employee_code": "E841",
                    "full_name": "Newt Short",
                    "job_level": "L3",
                    "base_salary_cents": 10000000,
                    "hire_date": "2026-10-04",
                },
            ),
        )

        validate_error(
            api.submit_plan_for_certification(scenario.plan_id, PA),
            ApiErrorId.ERR_NO_ELIGIBLE_PARTICIPANTS.value,
            expected_status=409,
        )

        plan = scenario.refresh_plan()
        assert plan["status"] == "TARGETS_SET"
        assert plan["total_target_cents"] == 0
        assert scenario.refresh_pool("UNIT-H6")["eligible_headcount"] == 0

        _, meta = validate_paginated(
            api.list_participant_awards(
                PA,
                params={
                    "plan_id": scenario.plan_id,
                    "eligibility_status": "INELIGIBLE_MIN_SERVICE",
                },
            )
        )
        assert meta["total_count"] == 1


class TestAwardAndAdjustmentStateGates:
    def test_an_unallocated_award_and_a_pending_adjustment_refuse_their_undo(self, api):
        """PRD §3.5: "It requires the acting manager to own the award's business unit, the
        plan to be in `ALLOCATION_OPEN` (`ERR_PLAN_NOT_IN_ALLOCATION`), the pool to be in
        `FUNDED` or `ALLOCATING` (`ERR_POOL_NOT_ALLOCATING`), the award to be in
        `PROPOSED` (`ERR_AWARD_STATE_INVALID`), and a matching `expected_pool_version`."
        And PRD §3.6: "Reversal requires the adjustment to be in `APPROVED`
        (`ERR_ADJUSTMENT_NOT_PENDING`) and the plan to be in `ALLOCATION_OPEN` or
        `CALIBRATION_REVIEW` (`ERR_PLAN_NOT_IN_ALLOCATION`)."

        Design: Corner/validations/award_and_adjustment_state_gates_rejected
        """
        scenario = build_funded_scenario(
            units=("UNIT-H7",),
            plan_overrides={"plan_name": "FY26 Award State Plan"},
            participants=_ADA_AND_BEA,
        )
        scenario.propose("ada", 4000000, allocation_rationale="at target")

        # The pool is legally ALLOCATING; only Bea's own award state is wrong.
        retraction = api.retract_allocation(
            scenario.award_id("bea"),
            retract_allocation_payload(
                scenario.pool_version("UNIT-H7"),
                retraction_reason="nothing to retract",
            ),
            scenario.manager_headers("UNIT-H7"),
        )
        error = validate_error(
            retraction, ApiErrorId.ERR_AWARD_STATE_INVALID.value, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_POOL_NOT_ALLOCATING.value

        adjustment = validate_success(
            api.create_discretionary_adjustment(
                discretionary_adjustment_payload(
                    scenario.plan_id,
                    scenario.award_id("ada"),
                    200000,
                    scenario.plan_version(),
                    justification="market adjustment",
                    documentation_ref="CC-2026-041",
                ),
                HR,
            ),
            expected_status=201,
        )
        assert adjustment["status"] == "PENDING_APPROVAL"

        reversal = api.reverse_discretionary_adjustment(
            adjustment["id"],
            adjustment_reverse_payload(decision_note="reversing before approval"),
            make_committee_headers(CC_ADJUDICATOR),
        )
        validate_error(
            reversal, ApiErrorId.ERR_ADJUSTMENT_NOT_PENDING.value, expected_status=409
        )

        assert (
            validate_success(api.get_discretionary_adjustment(adjustment["id"], HR))[
                "status"
            ]
            == "PENDING_APPROVAL"
        )

        bea = scenario.refresh_award("bea")
        assert bea["allocation_status"] == "UNALLOCATED"
        assert bea["retraction_count"] == 0
        assert scenario.refresh_award("ada")["adjustment_total_cents"] == 0

        pool = scenario.refresh_pool("UNIT-H7")
        assert pool["allocated_cents"] == 4000000
        assert pool["available_cents"] == 4000000


class TestAdjustmentGovernanceAndSignRules:
    def test_the_documentation_gate_and_then_the_negative_award_gate_refuse_the_money(
        self, api
    ):
        """PRD §3.6: "`documentation_ref` is not always optional: when the absolute value
        of `adjustment_cents` is strictly greater than 100000 cents — a thousand dollars —
        a non-empty `documentation_ref` pointing at the filed governance paperwork is
        required, and its absence is `ERR_ADJUSTMENT_DOCUMENTATION_REQUIRED`." And PRD
        §3.6: "And the award's `final_award_cents` plus the signed `adjustment_cents` must
        be at least 0, since no employee may be given a negative award
        (`ERR_NEGATIVE_AWARD_NOT_ALLOWED`)." And PRD §2.10: "**Fiscal checks**, last, in
        this order: the frozen per-award adjustment cap
        (`ERR_ADJUSTMENT_EXCEEDS_PER_AWARD_LIMIT`), the pool's remaining money
        (`ERR_POOL_FUNDS_EXCEEDED`) and the plan's discretionary budget
        (`ERR_DISCRETIONARY_BUDGET_EXCEEDED`)."

        Design: Corner/validations/adjustment_documentation_and_negative_award_rejected
        """
        scenario = build_funded_scenario(
            units=("UNIT-H8",),
            plan_overrides={"plan_name": "FY26 Adjustment Governance Plan"},
        )
        scenario.propose("ada", 4000000, allocation_rationale="at target")
        plan_version = scenario.plan_version()

        undocumented = api.create_discretionary_adjustment(
            discretionary_adjustment_payload(
                scenario.plan_id,
                scenario.award_id("ada"),
                150000,
                plan_version,
                justification="undocumented uplift",
            ),
            HR,
        )
        validate_error(
            undocumented,
            ApiErrorId.ERR_ADJUSTMENT_DOCUMENTATION_REQUIRED.value,
            expected_status=422,
        )

        clawback = validate_success(
            api.create_discretionary_adjustment(
                discretionary_adjustment_payload(
                    scenario.plan_id,
                    scenario.award_id("ada"),
                    -5000000,
                    plan_version,
                    justification="clawback of the whole award and then some",
                    documentation_ref="CC-2026-099",
                ),
                HR,
            ),
            expected_status=201,
        )
        assert clawback["per_award_cap_cents"] == 1000000

        decision = api.decide_discretionary_adjustment(
            clawback["id"],
            adjustment_decision_payload(
                "APPROVE", decision_note="committee approves the clawback"
            ),
            make_committee_headers(CC_ADJUDICATOR),
        )
        error = validate_error(
            decision,
            ApiErrorId.ERR_NEGATIVE_AWARD_NOT_ALLOWED.value,
            expected_status=422,
        )
        assert (
            error["error_id"] != ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_PER_AWARD_LIMIT.value
        )
        assert error["error_id"] != ApiErrorId.ERR_DISCRETIONARY_BUDGET_EXCEEDED.value

        assert (
            validate_success(api.get_discretionary_adjustment(clawback["id"], HR))[
                "status"
            ]
            == "PENDING_APPROVAL"
        )

        award = scenario.refresh_award("ada")
        assert award["adjustment_total_cents"] == 0
        assert award["final_award_cents"] == 4000000
        assert scenario.refresh_plan()["discretionary_used_cents"] == 0

        _, meta = validate_paginated(
            api.list_discretionary_adjustments(
                HR, params={"plan_id": scenario.plan_id}
            )
        )
        assert meta["total_count"] == 1


class TestRetractionBlockedByAnApprovedAdjustment:
    def test_the_committees_uplift_cannot_be_undone_by_the_manager(self, api):
        """PRD §3.5: "It also requires the award's `adjustment_total_cents` to be exactly
        0 — an approved discretionary adjustment must be reversed first, and retracting an
        award that still carries one is refused with
        `ERR_AWARD_HAS_APPROVED_ADJUSTMENT`." And PRD §3.6: "An adjustment of exactly
        100000 cents needs no documentation."

        Design: Corner/validations/retraction_blocked_by_an_approved_adjustment_rejected
        """
        scenario = build_funded_scenario(
            units=("UNIT-H9",),
            plan_overrides={"plan_name": "FY26 Retraction Block Plan"},
        )
        scenario.propose("ada", 4000000, allocation_rationale="at target")
        adjustment = scenario.file_adjustment(
            "ada",
            100000,
            justification="retention uplift at the documentation boundary",
        )
        assert adjustment["documentation_ref"] is None
        scenario.decide_adjustment(
            adjustment["id"], "APPROVE", decision_note="approved"
        )

        retraction = api.retract_allocation(
            scenario.award_id("ada"),
            retract_allocation_payload(
                scenario.pool_version("UNIT-H9"),
                retraction_reason="manager changed their mind",
            ),
            scenario.manager_headers("UNIT-H9"),
        )
        validate_error(
            retraction,
            ApiErrorId.ERR_AWARD_HAS_APPROVED_ADJUSTMENT.value,
            expected_status=409,
        )

        award = scenario.refresh_award("ada")
        assert award["allocation_status"] == "PROPOSED"
        assert award["retraction_count"] == 0
        assert award["adjustment_total_cents"] == 100000
        assert award["final_award_cents"] == 4100000

        pool = scenario.refresh_pool("UNIT-H9")
        assert pool["allocated_cents"] == 4100000
        assert pool["available_cents"] == -100000
        assert pool["distribution_status"] == "OVER_ALLOCATED"
        assert scenario.refresh_plan()["discretionary_used_cents"] == 100000


class TestAccrualPostingAndReversalOrder:
    def test_posting_is_once_only_and_reversal_is_strictly_last_in_first_out(self, api):
        """PRD §3.8: "It requires the period to be `OPEN` (`ERR_ACCRUAL_ALREADY_POSTED`),
        the plan not to have reached `PAID_OUT` or `SETTLED`, and every earlier period of
        the plan — every period whose `period_end` precedes this period's `period_start` —
        to be `POSTED` or `REVERSED` already, so that periods are posted in ascending
        order (`ERR_ACCRUAL_PERIOD_GAP`)." And PRD §3.8: "Reversal is last-in-first-out:
        no later period of the plan may still be `POSTED`, or the request is refused with
        `ERR_ACCRUAL_REVERSAL_OUT_OF_ORDER`, and the plan must not have reached
        `SETTLED`."

        Design: Corner/validations/accrual_double_post_and_out_of_order_reversal_rejected
        """
        scenario = build_setup_scenario(
            units=("UNIT-HA",),
            plan_overrides={"plan_name": "FY26 Accrual Ladder Plan"},
            participants=_ADA,
        )
        first = scenario.open_accrual_period("2026-01-01", "2026-06-30", 100.00)
        scenario.post_accrual_period(first["id"], posting_note="H1")
        second = scenario.open_accrual_period("2026-07-01", "2026-12-31", 100.00)
        scenario.post_accrual_period(second["id"], posting_note="H2")

        double_post = api.post_accrual_period(
            first["id"], FC, accrual_post_payload(posting_note="double post")
        )
        validate_error(
            double_post,
            ApiErrorId.ERR_ACCRUAL_ALREADY_POSTED.value,
            expected_status=409,
        )

        out_of_order = api.reverse_accrual_period(
            first["id"],
            accrual_reverse_payload(reversal_reason="out of order reversal"),
            FC,
        )
        validate_error(
            out_of_order,
            ApiErrorId.ERR_ACCRUAL_REVERSAL_OUT_OF_ORDER.value,
            expected_status=409,
        )

        assert (
            scenario.reverse_accrual_period(
                second["id"], reversal_reason="restating H2"
            )["status"]
            == "REVERSED"
        )
        reversed_first = scenario.reverse_accrual_period(
            first["id"], reversal_reason="restating H1"
        )
        assert reversed_first["status"] == "REVERSED"
        assert reversed_first["total_period_cents"] == 2135304
        assert_pct(reversed_first["burden_rate_pct"], 7.65)

        plan = scenario.refresh_plan()
        assert plan["accrued_total_cents"] == 0
        assert plan["accrued_base_cents"] == 0


class TestPayoutExecutionGates:
    def test_the_same_draft_run_is_refused_twice_and_then_pays_unchanged(self, api):
        """PRD §3.9: "It requires the plan to be `LOCKED` (`ERR_PLAN_NOT_LOCKED`) and the
        logical clock date to have reached the plan's `payment_date` — on the payment date
        itself is permitted, before it is refused with `ERR_PAYMENT_DATE_NOT_REACHED`."
        And PRD §3.9: "The run stamps the logical clock date into `payment_date_used`."

        Design: Corner/validations/payout_execution_lock_and_payment_date_gates_rejected
        """
        scenario = build_allocated_scenario(
            units=("UNIT-HB",),
            plan_overrides={"plan_name": "FY26 Execution Gates Plan"},
        )
        run = validate_success(
            api.create_payout_run(
                payout_run_payload(scenario.plan_id, run_note="premature run"), FC
            ),
            expected_status=201,
        )

        validate_error(
            api.execute_payout_run(run["id"], FC),
            ApiErrorId.ERR_PLAN_NOT_LOCKED.value,
            expected_status=409,
        )

        scenario.submit_calibration("UNIT-HB")
        scenario.open_calibration()
        scenario.decide_calibration("UNIT-HB", "CERTIFY")
        scenario.lock(user_id=CC_LOCKER)

        # The plan is locked, but the logical clock still reads 2026-08-01.
        validate_error(
            api.execute_payout_run(run["id"], FC),
            ApiErrorId.ERR_PAYMENT_DATE_NOT_REACHED.value,
            expected_status=409,
        )

        stalled = validate_success(api.get_payout_run(run["id"], FC))
        assert stalled["status"] == "DRAFT"
        assert stalled["paid_award_count"] == 0

        scenario.set_clock(PAYMENT_DATE_CLOCK)
        executed = validate_success(api.execute_payout_run(run["id"], FC))
        assert executed["status"] == "EXECUTED"
        assert executed["payment_date_used"] == PAYMENT_DATE
        assert executed["paid_award_count"] == 1
        assert executed["total_paid_cents"] == 4000000

        award = scenario.refresh_award("ada")
        assert award["payment_status"] == "PAID"
        assert award["payout_amount_cents"] == 4000000

        plan = scenario.refresh_plan()
        assert plan["status"] == "PAID_OUT"
        assert plan["paid_total_cents"] == 4000000
        assert plan["locked_total_cents"] == 4000000


class TestSetupPhaseCloses:
    def test_no_participant_and_no_metric_may_join_a_submitted_plan(self, api):
        """PRD §3.2: "Metric definition, target-grid definition, participant enrolment and
        pool creation are all setup-phase writes: they require the plan to be in `DRAFT`
        or `TARGETS_SET`, and are otherwise rejected with `ERR_PLAN_NOT_IN_SETUP`." And
        PRD §3.4: "Submitting the plan for certification moves it from `TARGETS_SET` to
        `PENDING_CERTIFICATION` and is where the setup phase is audited as a whole."

        Design: Corner/validations/setup_writes_after_submission_rejected
        """
        scenario = build_targets_set_scenario(
            units=("UNIT-HC",),
            plan_overrides={"plan_name": "FY26 Setup Phase Plan"},
            participants=_ADA,
        )
        scenario.submit_for_certification()

        late_participant = api.create_participant(
            participant_payload(
                scenario.plan_id,
                scenario.unit_id("UNIT-HC"),
                employee_code="E863",
                full_name="Late Joiner",
                job_level="L5",
                base_salary_cents=20000000,
                hire_date="2025-01-01",
            ),
            PA,
        )
        validate_error(
            late_participant,
            ApiErrorId.ERR_PLAN_NOT_IN_SETUP.value,
            expected_status=409,
        )

        late_metric = api.create_company_metric(
            company_metric_payload(
                scenario.plan_id,
                metric_code="CASHFLOW",
                weight_pct=10.00,
                threshold_value=90,
                target_value=100,
                max_value=130,
            ),
            PA,
        )
        validate_error(
            late_metric, ApiErrorId.ERR_PLAN_NOT_IN_SETUP.value, expected_status=409
        )

        plan = scenario.refresh_plan()
        assert plan["status"] == "PENDING_CERTIFICATION"
        assert plan["total_target_cents"] == 4000000

        _, meta = validate_paginated(
            api.list_participants(PA, params={"plan_id": scenario.plan_id})
        )
        assert meta["total_count"] == 1

        _, meta = validate_paginated(
            api.list_company_metrics(PA, params={"plan_id": scenario.plan_id})
        )
        assert meta["total_count"] == 1


class TestGovernancePostureGuardsTheLock:
    def test_an_approval_after_calibration_flags_the_plan_and_stops_the_lock(self, api):
        """PRD §3.7: "Three conditions guard it, in ladder order: the acting `X-User-ID`
        must differ from the plan's `certified_by_user_id`, so that the member who
        certified the performance figures is not the member who freezes the money
        (`ERR_SEGREGATION_OF_DUTIES`); the plan's `governance_posture` must be
        `COMPLIANT`, which means no pool may be left over-allocated or under-utilized
        (`ERR_GOVERNANCE_POSTURE_BREACHED`); and every pool of the plan must be in
        `CALIBRATED`, not merely submitted (`ERR_POOL_CALIBRATION_PENDING`)." And PRD
        §3.5: "The plan then re-derives its governance view: `over_allocated_pool_count`
        is the number of its pools in `OVER_ALLOCATED`, `under_utilized_pool_count` the
        number in `UNDER_UTILIZED`, and `governance_posture` is `BREACHED` when two or
        more pools are over-allocated, otherwise `FLAGGED` when exactly one pool is
        over-allocated or at least one pool is under-utilized, otherwise `COMPLIANT`."

        Design: Corner/validations/governance_posture_flag_blocks_the_plan_lock
        """
        scenario = build_allocated_scenario(
            units=("UNIT-HD",),
            plan_overrides={"plan_name": "FY26 Governance Lock Plan"},
        )
        adjustment = scenario.file_adjustment(
            "ada",
            400000,
            justification="exceptional individual year",
            documentation_ref="CC-2026-118",
        )
        scenario.submit_calibration("UNIT-HD")
        scenario.open_calibration()
        certified_pool = scenario.decide_calibration("UNIT-HD", "CERTIFY")
        assert certified_pool["distribution_status"] == "WITHIN_GUIDELINES"

        approved = scenario.decide_adjustment(
            adjustment["id"],
            "APPROVE",
            decision_note="committee funds the uplift from the discretionary budget",
        )
        assert approved["status"] == "APPROVED"

        award = scenario.refresh_award("ada")
        assert award["adjustment_total_cents"] == 400000
        assert award["final_award_cents"] == 4400000

        pool = scenario.refresh_pool("UNIT-HD")
        assert pool["allocated_cents"] == 4400000
        assert pool["available_cents"] == -400000
        assert_pct(pool["utilization_pct"], 110.00)
        assert pool["distribution_status"] == "OVER_ALLOCATED"
        assert pool["calibration_status"] == "CALIBRATED"

        plan = scenario.refresh_plan()
        assert plan["over_allocated_pool_count"] == 1
        assert plan["governance_posture"] == "FLAGGED"
        assert plan["discretionary_used_cents"] == 400000

        lock = api.lock_plan(scenario.plan_id, make_committee_headers(CC_LOCKER))
        error = validate_error(
            lock,
            ApiErrorId.ERR_GOVERNANCE_POSTURE_BREACHED.value,
            expected_status=409,
        )
        assert error["error_id"] != ApiErrorId.ERR_POOL_CALIBRATION_PENDING.value

        plan = scenario.refresh_plan()
        assert plan["status"] == "CALIBRATION_REVIEW"
        assert plan["locked_total_cents"] == 0


class TestEveryAllocationGateAtItsBoundary:
    def test_an_allocation_sitting_on_every_boundary_at_once_is_accepted(self, api):
        """PRD §3.5: "For a non-zero amount, that ratio must be at least the
        `guideline_min_ratio` and at most the `guideline_max_ratio` of the job-level target
        row for the award's level; a ratio outside the band is
        `ERR_GUIDELINE_RATIO_BREACH`." And PRD §3.5: "The pool's `allocated_cents`,
        evaluated after this award's previous proposed amount has been removed and the new
        one added, must not exceed the pool's frozen `funded_cents`; if it would, the
        request is refused with `ERR_POOL_FUNDS_EXCEEDED`." And PRD §3.5: "Allocating
        exactly `min_utilization_cents` is therefore within guidelines, since the
        under-utilization test is strict." And PRD §3.7: "And the pool's
        `top_tier_award_count` must not exceed its `max_top_tier_count`, or the submission
        is refused with `ERR_TOP_TIER_CONCENTRATION`."

        Design: Corner/validations/every_allocation_gate_satisfied_at_its_boundary_passes
        """
        scenario = build_funded_scenario(
            units=("UNIT-HE",),
            plan_overrides={"plan_name": "FY26 Boundary Pass Plan"},
        )

        award = scenario.propose(
            "ada", 4000000, allocation_rationale="exactly the funded pool"
        )
        assert award["allocation_status"] == "PROPOSED"
        assert award["allocation_ratio"] == 1.0000
        assert award["final_award_cents"] == 4000000

        pool = scenario.refresh_pool("UNIT-HE")
        assert pool["allocated_cents"] == 4000000
        assert pool["available_cents"] == 0
        assert_pct(pool["utilization_pct"], 100.00)
        assert pool["min_utilization_cents"] == 3980000
        assert pool["top_tier_award_count"] == 0
        assert pool["max_top_tier_count"] == 1
        assert pool["distribution_status"] == "WITHIN_GUIDELINES"

        submitted = scenario.submit_calibration(
            "UNIT-HE", scorecard_narrative="fully distributed"
        )
        assert submitted["calibration_status"] == "CALIBRATION_SUBMITTED"

        scenario.open_calibration()
        calibrated = scenario.decide_calibration(
            "UNIT-HE", "CERTIFY", decision_note="no outliers"
        )
        assert calibrated["calibration_status"] == "CALIBRATED"
        assert scenario.refresh_award("ada")["allocation_status"] == "CALIBRATED"
        assert scenario.refresh_plan()["governance_posture"] == "COMPLIANT"
