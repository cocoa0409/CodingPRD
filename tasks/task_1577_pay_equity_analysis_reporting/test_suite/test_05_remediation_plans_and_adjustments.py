"""Remediation plans, individual adjustments, budgets, and OCC (PRD §2.6, §2.8, §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_proposed_adjustments,
    approve_adjustment,
    assert_plan_budget_invariant,
    create_adjustment_payload,
    create_plan,
    create_plan_payload,
    decide_plan,
    disposition_finding,
    get_adjustment,
    get_finding,
    get_plan,
    make_comp_analyst_headers,
    make_remediation_approver_headers,
    open_remediation,
    propose_adjustment,
    setup_privileged_final_study,
    setup_remediation_open,
    submit_and_approve_plan,
    submit_plan,
    sweep_clock,
    two_eng_member_specs,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["comp_analyst_headers"]
APPROVER = TEST_USERS["remediation_approver_headers"]


class TestPlanCreationAndSubmitGuards:
    def test_plan_creation_and_submit_guards(self, api):
        """PRD §3.4: "A `CompAnalyst` drafts a remediation plan for a study that is `REMEDIATION_OPEN` (otherwise `ERR_STUDY_NOT_IN_REMEDIATION`)."
        PRD §3.4: "A study may have at most one plan whose status is not `COMPLETED`; an attempt to create a second live plan is rejected with `ERR_ACTIVE_PLAN_EXISTS`."
        PRD §3.4: "a `CompAnalyst` submits a plan in `DRAFT` (otherwise `ERR_PLAN_INVALID_STATE`) that contains at least one `PROPOSED` adjustment (otherwise `ERR_PLAN_EMPTY`), moving it to `SUBMITTED`."

        Design: Corner/validations/plan_creation_and_submit_guards
        """
        ctx = setup_privileged_final_study(
            name="PG", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", member_specs=two_eng_member_specs(),
            group_name="GPG", min_group_size=2,
        )
        # Plan creation requires REMEDIATION_OPEN; the study is PRIVILEGED_FINAL.
        res = api.create_plan(
            create_plan_payload(ctx["study"]["id"], total_budget_cents=500000), ANALYST
        )
        validate_error(res, ApiErrorId.ERR_STUDY_NOT_IN_REMEDIATION)
        open_remediation(ctx["study"]["id"])
        plan = create_plan(ctx["study"]["id"], total_budget_cents=500000)
        # A second live (non-COMPLETED) plan conflicts.
        res2 = api.create_plan(
            create_plan_payload(ctx["study"]["id"], total_budget_cents=600000), ANALYST
        )
        validate_error(res2, ApiErrorId.ERR_ACTIVE_PLAN_EXISTS)
        # Submitting a plan with zero PROPOSED adjustments fails.
        res3 = api.submit_plan(plan["id"], ANALYST)
        validate_error(res3, ApiErrorId.ERR_PLAN_EMPTY)


class TestAdjustmentCreationValidation:
    def test_adjustment_invalid_increase_rejected(self, api):
        """PRD §3.4: "The `proposed_increase_cents` must be greater than zero (otherwise `ERR_INVALID_INCREASE`), and the `effective_date` must not precede the current logical-clock date; a date in the past is rejected with `ERR_EFFECTIVE_DATE_IN_PAST`, while a date equal to the clock date is acceptable."

        Design: Corner/validations/adjustment_invalid_increase_rejected
        """
        ctx = setup_remediation_open(
            name="AI", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", member_specs=two_eng_member_specs(),
            group_name="GAI", min_group_size=2, significance_threshold=0.1,
            budget=500000,
        )
        res = api.create_adjustment(
            create_adjustment_payload(
                ctx["plan"]["id"], ctx["finding"]["id"], ctx["members"][1]["id"],
                proposed_increase_cents=0, effective_date="2026-09-01",
            ),
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_INCREASE)

    def test_adjustment_effective_date_in_past_rejected(self, api):
        """PRD §3.4: "The `proposed_increase_cents` must be greater than zero (otherwise `ERR_INVALID_INCREASE`), and the `effective_date` must not precede the current logical-clock date; a date in the past is rejected with `ERR_EFFECTIVE_DATE_IN_PAST`, while a date equal to the clock date is acceptable."
        PRD §2.4: "Before any client call sets it, the logical clock reads exactly 2026-08-01T00:00:00Z as a fixed startup default; the server never falls back to the host's wall clock."

        Design: Corner/validations/adjustment_effective_date_in_past_rejected
        """
        ctx = setup_remediation_open(
            name="ED", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", member_specs=two_eng_member_specs(),
            group_name="GED", min_group_size=2, significance_threshold=0.1,
            budget=500000,
        )
        # 2026-07-31 precedes the logical clock's 2026-08-01 startup date.
        res = api.create_adjustment(
            create_adjustment_payload(
                ctx["plan"]["id"], ctx["finding"]["id"], ctx["members"][1]["id"],
                proposed_increase_cents=100000, effective_date="2026-07-31",
            ),
            make_comp_analyst_headers("user-analyst-1"),
        )
        validate_error(res, ApiErrorId.ERR_EFFECTIVE_DATE_IN_PAST)
        # A date exactly equal to the clock date is acceptable.
        ok = validate_success(
            api.create_adjustment(
                create_adjustment_payload(
                    ctx["plan"]["id"], ctx["finding"]["id"], ctx["members"][1]["id"],
                    proposed_increase_cents=100000, effective_date="2026-08-01",
                ),
                make_comp_analyst_headers("user-analyst-1"),
            ),
            201,
        )
        assert ok["status"] == "PROPOSED"
        assert ok["effective_date"] == "2026-08-01"


class TestBudgetAndSegregationGuards:
    def test_budget_exceeded_and_segregation_guards(self, api):
        """PRD §3.4: "For an approval specifically, the budget check runs last: the plan's `committed_cents` plus the adjustment's `proposed_increase_cents` must not exceed the plan's `total_budget_cents`, with equality permitted — an approval that would overshoot the envelope is rejected with `ERR_BUDGET_EXCEEDED`."
        PRD §3.4: "segregation of duties forbids the decider from being the proposer: if the decider's `X-User-ID` equals the adjustment's `created_by_user_id`, the decision is rejected with `ERR_SELF_DECISION_FORBIDDEN`."

        Design: Corner/validations/budget_exceeded_and_segregation_guards
        """
        ctx = setup_remediation_open(
            name="BG", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", member_specs=two_eng_member_specs(),
            group_name="GBG", min_group_size=2, significance_threshold=0.1,
            budget=100000,
        )
        a_over = propose_adjustment(
            ctx["plan"]["id"], ctx["finding"]["id"], ctx["members"][1]["id"],
            100001, proposer_user_id="user-shared-1",
        )
        a_ok = propose_adjustment(
            ctx["plan"]["id"], ctx["finding"]["id"], ctx["members"][0]["id"],
            50000, proposer_user_id="user-shared-1",
        )
        submit_and_approve_plan(ctx)
        pv = get_plan(ctx["plan"]["id"])["version"]

        # One cent over the envelope: committed 0 + 100001 > 100000.
        res = api.decide_adjustment(
            a_over["id"],
            {"decision": "APPROVE", "expected_plan_version": pv},
            make_remediation_approver_headers("user-approver-9"),
        )
        validate_error(res, ApiErrorId.ERR_BUDGET_EXCEEDED)
        # Decider identical to the proposer violates segregation of duties.
        res2 = api.decide_adjustment(
            a_ok["id"],
            {"decision": "APPROVE", "expected_plan_version": pv},
            make_remediation_approver_headers("user-shared-1"),
        )
        validate_error(res2, ApiErrorId.ERR_SELF_DECISION_FORBIDDEN)
        # A different approver deciding within budget succeeds.
        pv2 = get_plan(ctx["plan"]["id"])["version"]
        ok = validate_success(
            api.decide_adjustment(
                a_ok["id"],
                {"decision": "APPROVE", "expected_plan_version": pv2},
                make_remediation_approver_headers("user-approver-9"),
            )
        )
        assert ok["status"] == "APPROVED"
        assert get_plan(ctx["plan"]["id"])["committed_cents"] == 50000


class TestBeginMonitoringGates:
    def test_begin_monitoring_guards(self, api):
        """PRD §3.4: "A `CompAnalyst` moving the study from `REMEDIATION_OPEN` to `MONITORING` — or the automatic transitions just described — must satisfy two gates, checked in this order: the study's `unresolved_finding_count` must be zero (otherwise `ERR_GAPS_NOT_RESOLVED`, and this check runs first), and the study must have a remediation plan — its non-completed plan, if one exists — in `FULLY_COMMITTED` or `COMPLETED` status, with a plan required to exist (otherwise `ERR_PLAN_NOT_COMMITTED`)."

        Design: Corner/validations/begin_monitoring_guards
        """
        ctx = setup_remediation_open(
            name="BM", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", member_specs=two_eng_member_specs(),
            group_name="GBM", min_group_size=2, target_finding=False,
            budget=500000,
        )
        # The FLAGGED finding still counts as unresolved: gate one fires first.
        res = api.begin_monitoring(ctx["study"]["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_GAPS_NOT_RESOLVED)
        # MONITORED has no actionability requirement; the finding resolves out.
        disposition_finding(ctx["finding"]["id"], "MONITORED")
        # Findings resolved, but the DRAFT plan is neither FULLY_COMMITTED nor
        # COMPLETED: gate two fires.
        res2 = api.begin_monitoring(ctx["study"]["id"], ANALYST)
        validate_error(res2, ApiErrorId.ERR_PLAN_NOT_COMMITTED)


class TestAdjustmentPlanStateDependency:
    def test_decision_rejected_while_plan_submitted(self, api):
        """PRD §3.4: "The adjustment must be `PROPOSED` (otherwise `ERR_ADJUSTMENT_INVALID_STATE`), its parent plan must be `APPROVED` or `EXECUTING` (otherwise `ERR_PLAN_NOT_APPROVED`), and segregation of duties forbids the decider from being the proposer: if the decider's `X-User-ID` equals the adjustment's `created_by_user_id`, the decision is rejected with `ERR_SELF_DECISION_FORBIDDEN`."

        Design: Difficulty/cross_entity_state_dependency/adjustment_decision_requires_plan_approved
        """
        ctx = setup_remediation_open(
            name="StudyK", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", budget=2700000,
        )
        add_proposed_adjustments(ctx, [(3, 100000)])
        submit_plan(ctx["plan"]["id"])
        # The plan is merely SUBMITTED — not yet APPROVED or EXECUTING.
        pv = get_plan(ctx["plan"]["id"])["version"]
        res = api.decide_adjustment(
            ctx["adjustments"][0]["id"],
            {"decision": "APPROVE", "expected_plan_version": pv},
            make_remediation_approver_headers("user-approver-1"),
        )
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_APPROVED)

    def test_decision_succeeds_after_plan_approved(self, api):
        """PRD §3.4: "A successful approval stamps `approved_increase_cents` equal to `proposed_increase_cents`, records the decider as `decided_by_user_id`, recomputes the plan's `committed_cents`, and advances the plan's `version` by one. The first approval on a plan moves the plan automatically from `APPROVED` to `EXECUTING`."

        Design: Difficulty/cross_entity_state_dependency/adjustment_decision_requires_plan_approved
        """
        ctx = setup_remediation_open(
            name="StudyK", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", budget=2700000,
        )
        add_proposed_adjustments(ctx, [(3, 100000)])
        submit_plan(ctx["plan"]["id"])
        decide_plan(ctx["plan"]["id"], "APPROVE")
        pv = get_plan(ctx["plan"]["id"])["version"]
        decided = validate_success(
            api.decide_adjustment(
                ctx["adjustments"][0]["id"],
                {"decision": "APPROVE", "expected_plan_version": pv},
                make_remediation_approver_headers("user-approver-1"),
            )
        )
        assert decided["status"] == "APPROVED"
        assert decided["approved_increase_cents"] == 100000
        assert decided["decided_by_user_id"] == "user-approver-1"
        # The first approval flips the plan APPROVED -> EXECUTING.
        assert get_plan(ctx["plan"]["id"])["status"] == "EXECUTING"


class TestStateBeatsBudgetPriority:
    def test_dual_failure_reports_plan_state_not_budget(self, api):
        """PRD §2.8: "Sixth, entity state preconditions for the attempted action are enforced (the state-guard errors catalogued in §5)."
        PRD §2.8: "Budget sufficiency on an adjustment approval is evaluated last, after all other checks have passed."

        Design: Difficulty/priority_pair_validation_conflict/adjustment_decision_state_beats_budget
        """
        ctx = setup_remediation_open(
            name="StudyE", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", budget=1000000,
        )
        # 2000000 proposed against a 1000000 envelope: the budget check would
        # also fail, but the plan is still DRAFT and the state check runs first.
        adjustment = propose_adjustment(
            ctx["plan"]["id"], ctx["finding"]["id"], ctx["members"][3]["id"], 2000000
        )
        pv = get_plan(ctx["plan"]["id"])["version"]
        res = api.decide_adjustment(
            adjustment["id"],
            {"decision": "APPROVE", "expected_plan_version": pv},
            make_remediation_approver_headers("user-approver-1"),
        )
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_APPROVED)
        assert get_adjustment(adjustment["id"])["status"] == "PROPOSED"

    def test_budget_check_surfaces_once_state_passes(self, api):
        """PRD §2.8: "Budget sufficiency on an adjustment approval is evaluated last, after all other checks have passed."
        PRD §3.4: "For an approval specifically, the budget check runs last: the plan's `committed_cents` plus the adjustment's `proposed_increase_cents` must not exceed the plan's `total_budget_cents`, with equality permitted — an approval that would overshoot the envelope is rejected with `ERR_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/adjustment_decision_state_beats_budget
        """
        ctx = setup_remediation_open(
            name="StudyE", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", budget=1000000,
        )
        adjustment = propose_adjustment(
            ctx["plan"]["id"], ctx["finding"]["id"], ctx["members"][3]["id"], 2000000
        )
        pv = get_plan(ctx["plan"]["id"])["version"]
        res = api.decide_adjustment(
            adjustment["id"],
            {"decision": "APPROVE", "expected_plan_version": pv},
            make_remediation_approver_headers("user-approver-1"),
        )
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_APPROVED)
        # Once the plan is APPROVED, the fiscal check is unmasked: committed 0
        # plus proposed 2000000 exceeds the 1000000 envelope.
        submit_plan(ctx["plan"]["id"])
        decide_plan(ctx["plan"]["id"], "APPROVE")
        pv2 = get_plan(ctx["plan"]["id"])["version"]
        res2 = api.decide_adjustment(
            adjustment["id"],
            {"decision": "APPROVE", "expected_plan_version": pv2},
            make_remediation_approver_headers("user-approver-1"),
        )
        validate_error(res2, ApiErrorId.ERR_BUDGET_EXCEEDED)
        assert get_adjustment(adjustment["id"])["status"] == "PROPOSED"


class TestBudgetCommitBoundary:
    def test_commit_exactly_at_total_allowed(self, api):
        """PRD §3.4: "For an approval specifically, the budget check runs last: the plan's `committed_cents` plus the adjustment's `proposed_increase_cents` must not exceed the plan's `total_budget_cents`, with equality permitted — an approval that would overshoot the envelope is rejected with `ERR_BUDGET_EXCEEDED`."
        PRD §3.4: "Whenever a recompute brings `committed_cents` exactly equal to `total_budget_cents`, the plan moves automatically from `EXECUTING` to `FULLY_COMMITTED`."

        Design: Difficulty/boundary_precision_check/budget_commit_at_exact_total_allowed
        """
        ctx = setup_remediation_open(
            name="StudyI", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", budget=2700000,
        )
        add_proposed_adjustments(ctx, [(3, 1500000), (4, 1200000)])
        submit_and_approve_plan(ctx)
        approve_adjustment(ctx["adjustments"][0]["id"], ctx["plan"]["id"])
        # 1500000 + 1200000 == 2700000 == total_budget_cents: equality is allowed.
        second = approve_adjustment(ctx["adjustments"][1]["id"], ctx["plan"]["id"])
        assert second["status"] == "APPROVED"
        plan = get_plan(ctx["plan"]["id"])
        assert plan["committed_cents"] == 2700000
        assert plan["remaining_cents"] == 0
        assert_plan_budget_invariant(plan)
        # The plan auto-transitions at exact equality.
        assert plan["status"] == "FULLY_COMMITTED"

    def test_first_approval_intermediate_commit_arithmetic(self, api):
        """PRD §2.10: "A remediation plan reports `committed_cents` (the sum of `approved_increase_cents` over its adjustments in `APPROVED` or `EFFECTIVE` status) and `remaining_cents` (its `total_budget_cents` minus `committed_cents`). The plan invariant holds at all times: `committed_cents` plus `remaining_cents` always equals `total_budget_cents`."
        PRD §3.4: "The first approval on a plan moves the plan automatically from `APPROVED` to `EXECUTING`."

        Design: Difficulty/boundary_precision_check/budget_commit_at_exact_total_allowed
        """
        ctx = setup_remediation_open(
            name="StudyI", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", budget=2700000,
        )
        add_proposed_adjustments(ctx, [(3, 1500000), (4, 1200000)])
        submit_and_approve_plan(ctx)
        approve_adjustment(ctx["adjustments"][0]["id"], ctx["plan"]["id"])
        plan = get_plan(ctx["plan"]["id"])
        assert plan["committed_cents"] == 1500000
        assert plan["remaining_cents"] == 1200000
        assert_plan_budget_invariant(plan)
        assert plan["status"] == "EXECUTING"


class TestApproveReverseRoundTrip:
    def test_approve_and_effectivation_keep_commitment(self, api):
        """PRD §2.10: "A remediation plan reports `committed_cents` (the sum of `approved_increase_cents` over its adjustments in `APPROVED` or `EFFECTIVE` status) and `remaining_cents` (its `total_budget_cents` minus `committed_cents`). The plan invariant holds at all times: `committed_cents` plus `remaining_cents` always equals `total_budget_cents`."
        PRD §2.4: "First, every `APPROVED` adjustment whose `effective_date` falls on or before the new UTC calendar date becomes `EFFECTIVE`; ties are processed by `effective_date` ascending and then by `created_at` ascending."

        Design: Difficulty/compensating_invariant/approve_reverse_roundtrip_conserves_budget_cents
        """
        ctx = setup_remediation_open(
            name="StudyN", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", budget=2700000,
        )
        # A2 (100000) is deliberately never decided so the plan cannot
        # auto-complete and block the reverse path exercised by the pair test.
        add_proposed_adjustments(ctx, [(3, 950000), (4, 100000)])
        submit_and_approve_plan(ctx)
        plan0 = get_plan(ctx["plan"]["id"])
        assert plan0["committed_cents"] == 0
        assert plan0["remaining_cents"] == 2700000
        assert_plan_budget_invariant(plan0)

        approve_adjustment(ctx["adjustments"][0]["id"], ctx["plan"]["id"])
        plan1 = get_plan(ctx["plan"]["id"])
        assert plan1["committed_cents"] == 950000
        assert plan1["remaining_cents"] == 1750000
        assert_plan_budget_invariant(plan1)

        # Effectivation alone does not change committed_cents: EFFECTIVE
        # adjustments stay committed.
        sweep_clock("2026-09-01T00:00:00Z")
        assert get_adjustment(ctx["adjustments"][0]["id"])["status"] == "EFFECTIVE"
        plan2 = get_plan(ctx["plan"]["id"])
        assert plan2["committed_cents"] == 950000
        # The undecided A2 (PROPOSED) blocks plan auto-completion.
        assert plan2["status"] == "EXECUTING"

    def test_reverse_returns_budget_to_baseline(self, api):
        """PRD §3.4: "Reversal moves the adjustment to `REVERSED`, recomputes the plan's `committed_cents` so that it drops by the reversed adjustment's `approved_increase_cents`, advances the plan's `version` by one, and — if the plan was `FULLY_COMMITTED` and its committed total has fallen below the budget — returns the plan to `EXECUTING`."
        PRD §3.4: "Reversal also runs the finding resolution re-check, but deliberately changes nothing there: a `RESOLVED` finding stays `RESOLVED`, and a `TARGETED` finding stays `TARGETED`."
        PRD §2.10: "The plan invariant holds at all times: `committed_cents` plus `remaining_cents` always equals `total_budget_cents`."

        Design: Difficulty/compensating_invariant/approve_reverse_roundtrip_conserves_budget_cents
        """
        ctx = setup_remediation_open(
            name="StudyN", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", budget=2700000,
        )
        add_proposed_adjustments(ctx, [(3, 950000), (4, 100000)])
        submit_and_approve_plan(ctx)
        approve_adjustment(ctx["adjustments"][0]["id"], ctx["plan"]["id"])
        sweep_clock("2026-09-01T00:00:00Z")
        assert get_adjustment(ctx["adjustments"][0]["id"])["status"] == "EFFECTIVE"

        reversed_adj = validate_success(
            api.reverse_adjustment(
                ctx["adjustments"][0]["id"],
                {"rationale": "Employee departed before payout"},
                APPROVER,
            )
        )
        assert reversed_adj["status"] == "REVERSED"
        # The approve -> effective -> reverse round trip conserves budget cents
        # exactly: committed returns to the 0 baseline, remaining to the envelope.
        plan = get_plan(ctx["plan"]["id"])
        assert plan["committed_cents"] == 0
        assert plan["remaining_cents"] == 2700000
        assert_plan_budget_invariant(plan)
        # A TARGETED finding stays TARGETED through the reversal re-check.
        assert get_finding(ctx["finding"]["id"])["status"] == "TARGETED"


class TestPlanRejectResubmitCycle:
    def test_reject_returns_plan_to_draft_and_counts(self, api):
        """PRD §3.4: "A `decision` of `REJECT` requires a non-empty `rationale` (otherwise `ERR_RATIONALE_REQUIRED`), returns the plan to `DRAFT` for rework, and increments its `rejection_count` by one."

        Design: Difficulty/non_linear_state_machine/plan_reject_resubmit_cycle
        """
        ctx = setup_remediation_open(
            name="StudyT", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", budget=5000000,
        )
        add_proposed_adjustments(ctx, [(3, 100000)])
        submit_plan(ctx["plan"]["id"])
        rejected = decide_plan(
            ctx["plan"]["id"], "REJECT", rationale="Rework the adjustment mix"
        )
        assert rejected["status"] == "DRAFT"
        assert rejected["rejection_count"] == 1
        # The drafted adjustment survives the rejection for rework.
        assert get_adjustment(ctx["adjustments"][0]["id"])["status"] == "PROPOSED"

    def test_resubmit_then_approve_traverses_loop(self, api):
        """PRD §3.4: "A `decision` of `REJECT` requires a non-empty `rationale` (otherwise `ERR_RATIONALE_REQUIRED`), returns the plan to `DRAFT` for rework, and increments its `rejection_count` by one."
        PRD §3.4: "A `decision` of `APPROVE` moves the plan from `SUBMITTED` to `APPROVED`."

        Design: Difficulty/non_linear_state_machine/plan_reject_resubmit_cycle
        """
        ctx = setup_remediation_open(
            name="StudyT", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", budget=5000000,
        )
        add_proposed_adjustments(ctx, [(3, 100000)])
        submit_plan(ctx["plan"]["id"])
        rejected = decide_plan(
            ctx["plan"]["id"], "REJECT", rationale="Rework the adjustment mix"
        )
        assert rejected["status"] == "DRAFT"
        # The surviving PROPOSED adjustment satisfies the submit gate again.
        resubmitted = submit_plan(ctx["plan"]["id"])
        assert resubmitted["status"] == "SUBMITTED"
        approved = decide_plan(ctx["plan"]["id"], "APPROVE")
        assert approved["status"] == "APPROVED"
        assert approved["rejection_count"] == 1


class TestSuggestedAllocationVariants:
    def test_full_closure_totals_ignore_budget(self, api):
        """PRD §3.4: "Under `FULL_CLOSURE`, the suggestion for each employee is exactly that per-capita gap; the suggestions are advisory only, and their sum may exceed the plan's budget envelope."
        PRD §3.4: "Each affected employee's per-capita gap is the employee's `annualized_base_cents` multiplied by the finding's `adjusted_gap_pct` and divided by one hundred, rounded half-up to a whole cent."
        PRD §3.4: "To guide the drafting of adjustments, the API offers a computed suggested-allocation read on a plan, available to `CompAnalyst` and `RemediationApprover`, returning the `strategy`, the `total_suggested_cents`, and the per-employee `suggestions`."

        Design: Difficulty/dual_variant_calc/allocation_strategy_variants_diverge
        """
        ctx = setup_remediation_open(
            name="AllocA", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", budget=3000000,
            allocation_strategy="FULL_CLOSURE",
        )
        data = validate_success(
            api.get_suggested_allocation(ctx["plan"]["id"], ANALYST)
        )
        assert data["strategy"] == "FULL_CLOSURE"
        # Per-capita gaps 950000 + 900000 + 850000 = 2700000 (one per FEMALE
        # member of the finding's group), advisory and unconstrained by budget.
        assert data["total_suggested_cents"] == 2700000
        assert len(data["suggestions"]) == 3

    def test_pro_rata_totals_scale_exactly_to_budget(self, api):
        """PRD §3.4: "When the total gap figure is greater than zero, the `PRO_RATA` suggestions sum to exactly `total_budget_cents`."
        PRD §3.4: "To guide the drafting of adjustments, the API offers a computed suggested-allocation read on a plan, available to `CompAnalyst` and `RemediationApprover`, returning the `strategy`, the `total_suggested_cents`, and the per-employee `suggestions`."

        Design: Difficulty/dual_variant_calc/allocation_strategy_variants_diverge
        """
        ctx = setup_remediation_open(
            name="AllocB", analysis_period_start="2026-01-01",
            analysis_period_end="2026-06-30", budget=2000000,
            allocation_strategy="PRO_RATA",
        )
        data = validate_success(
            api.get_suggested_allocation(ctx["plan"]["id"], APPROVER)
        )
        assert data["strategy"] == "PRO_RATA"
        # The identical TARGETED universe (per-capita gaps summing to 2700000)
        # is scaled to exactly the 2000000 envelope, never beyond it.
        assert data["total_suggested_cents"] == 2000000
        assert len(data["suggestions"]) == 3


class TestProRataWaterfall:
    def test_pro_rata_total_equals_budget_exactly(self, api):
        """PRD §3.4: "Otherwise each employee's raw share is their per-capita gap multiplied by `total_budget_cents` and divided by the total gap figure; each share is floored to a whole cent; and the remaining cents — the budget minus the sum of the floored shares — are distributed one cent at a time to employees ordered by per-capita gap descending with ties broken by the snapshot's `created_at` ascending, one cent per employee per pass, until no remainder is left. When the total gap figure is greater than zero, the `PRO_RATA` suggestions sum to exactly `total_budget_cents`."

        Design: Difficulty/combinatorial_formula/prorata_waterfall_remainder_distribution
        """
        ctx = setup_remediation_open(
            name="StudyP", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", budget=2000000,
            allocation_strategy="PRO_RATA",
        )
        data = validate_success(
            api.get_suggested_allocation(ctx["plan"]["id"], ANALYST)
        )
        # The floor-then-remainder waterfall exhausts the budget exactly.
        assert data["total_suggested_cents"] == 2000000
        assert len(data["suggestions"]) == 3

    def test_pro_rata_distribution_is_deterministic(self, api):
        """PRD §3.4: "the remaining cents — the budget minus the sum of the floored shares — are distributed one cent at a time to employees ordered by per-capita gap descending with ties broken by the snapshot's `created_at` ascending, one cent per employee per pass, until no remainder is left."

        Design: Difficulty/combinatorial_formula/prorata_waterfall_remainder_distribution
        """
        ctx = setup_remediation_open(
            name="StudyP", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", budget=2000000,
            allocation_strategy="PRO_RATA",
        )
        first = validate_success(
            api.get_suggested_allocation(ctx["plan"]["id"], ANALYST)
        )
        second = validate_success(
            api.get_suggested_allocation(ctx["plan"]["id"], ANALYST)
        )
        # The pinned ordering makes the waterfall deterministic, not random:
        # repeated computed reads return identical payloads.
        assert first == second
        assert first["total_suggested_cents"] == 2000000


class TestAdjustmentOccAndStateGuards:
    def test_occ_stale_plan_version_returns_412(self, api):
        """PRD §2.6: "Deciding an adjustment requires the request body to carry `expected_plan_version`, holding the `version` of the parent remediation plan as the client last observed it. If the plan's current `version` differs, the decision is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412)."
        PRD §3.4: "Either decision requires the plan to be in `SUBMITTED` (otherwise `ERR_PLAN_INVALID_STATE`)."
        PRD §3.4: "a `RemediationApprover` reverses an `EFFECTIVE` adjustment (any other adjustment state is rejected with `ERR_ADJUSTMENT_INVALID_STATE`), supplying a `rationale`, but only while the parent plan is `EXECUTING` or `FULLY_COMMITTED` — a `COMPLETED` plan cannot reopen, and the attempt is rejected with `ERR_PLAN_INVALID_STATE`."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_returns_412
        """
        ctx = setup_remediation_open(
            name="OC", analysis_period_start="2024-01-01",
            analysis_period_end="2024-12-31", member_specs=two_eng_member_specs(),
            group_name="GOC", min_group_size=2, significance_threshold=0.1,
            budget=2700000,
        )
        a1 = propose_adjustment(
            ctx["plan"]["id"], ctx["finding"]["id"], ctx["members"][1]["id"], 50000
        )
        a2 = propose_adjustment(
            ctx["plan"]["id"], ctx["finding"]["id"], ctx["members"][0]["id"], 60000
        )
        # The committee cannot decide a DRAFT (never submitted) plan.
        res0 = api.decide_plan(ctx["plan"]["id"], {"decision": "APPROVE"}, APPROVER)
        validate_error(res0, ApiErrorId.ERR_PLAN_INVALID_STATE)
        submit_plan(ctx["plan"]["id"])
        decide_plan(ctx["plan"]["id"], "APPROVE")
        pv1 = get_plan(ctx["plan"]["id"])["version"]

        # A PROPOSED adjustment cannot be reversed.
        res1 = api.reverse_adjustment(
            a1["id"], {"rationale": "too early"}, APPROVER
        )
        validate_error(res1, ApiErrorId.ERR_ADJUSTMENT_INVALID_STATE)
        # Fresh-version decision succeeds...
        decided1 = validate_success(
            api.decide_adjustment(
                a1["id"],
                {"decision": "APPROVE", "expected_plan_version": pv1},
                make_remediation_approver_headers("user-approver-1"),
            )
        )
        assert decided1["status"] == "APPROVED"
        # ...and bumps plan.version, so the same token is stale for the next call.
        res2 = api.decide_adjustment(
            a2["id"],
            {"decision": "APPROVE", "expected_plan_version": pv1},
            make_remediation_approver_headers("user-approver-1"),
        )
        validate_error(res2, ApiErrorId.ERR_STALE_PLAN_VERSION)
        # Re-reading the version and retrying succeeds.
        pv2 = get_plan(ctx["plan"]["id"])["version"]
        decided2 = validate_success(
            api.decide_adjustment(
                a2["id"],
                {"decision": "APPROVE", "expected_plan_version": pv2},
                make_remediation_approver_headers("user-approver-1"),
            )
        )
        assert decided2["status"] == "APPROVED"
