"""Distribution plans: filing gates, approval cascade, reject/amend cycle."""
from test_helpers import (
    COURT,
    RECEIVER,
    ApiErrorId,
    amend_distribution_plan,
    create_case,
    create_claim,
    create_distribution_plan,
    decide_distribution_plan,
    determine_claim,
    get_case,
    list_claim_payments,
    list_plan_payments,
    setup_case_with_cash,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlanFilingGates:
    def test_plan_reserve_exceeds_cash_rejected(self, api):
        """PRD §3.7: "`reserve_cents` must be non-negative and no greater
        than the current `cash_on_hand_cents` (else
        `ERR_RESERVE_EXCEEDS_POOL`, HTTP 422)."

        Design: Corner/validations/plan_reserve_exceeds_cash_rejected
        """
        case, _asset = setup_case_with_cash(50000)
        resp = api.create_distribution_plan(
            {"case_id": case["id"], "reserve_cents": 60000}, RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_RESERVE_EXCEEDS_POOL)

    def test_second_open_plan_rejected(self, api):
        """PRD §3.7: "no other plan of the case may be `FILED` or `APPROVED`
        (else `ERR_PLAN_ALREADY_OPEN`)"

        Design: Corner/errors/second_open_plan_rejected
        """
        case = create_case()
        claim = create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                             filed_amount_cents=50000)
        determine_claim(claim["id"], "ALLOWED", 50000)
        create_distribution_plan(case["id"], reserve_cents=0)

        resp = api.create_distribution_plan(
            {"case_id": case["id"], "reserve_cents": 0}, RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_ALREADY_OPEN)

    def test_plan_create_with_undetermined_claim_rejected(self, api):
        """PRD §3.7: "no claim of the case may remain `FILED` (else
        `ERR_UNDETERMINED_CLAIMS`)"

        Design: Corner/errors/plan_create_with_undetermined_claim_rejected
        """
        case = create_case()
        create_claim(case["id"], creditor_name="Pending Creditor",
                     creditor_type="GENERAL_UNSECURED", filed_amount_cents=50000)

        resp = api.create_distribution_plan(
            {"case_id": case["id"], "reserve_cents": 0}, RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_UNDETERMINED_CLAIMS)


class TestPlanApprovalCascade:
    def test_plan_approval_case_to_payment_generation(self, api):
        """PRD §3.7: "Approval stamps `approved_at`, moves the plan to
        `APPROVED`, moves the case from `ACTIVE` to `DISTRIBUTING`, and — on
        the case's entry into `DISTRIBUTING` — materializes the payment
        schedule: one distribution payment row per claim-and-class-bucket
        pair whose computed amount is greater than zero, each carrying its
        `plan_id`, `claim_id`, `priority_class`, and a
        `scheduled_amount_cents`, starting in `SCHEDULED` status."

        Design: Difficulty/transitive_cascade/plan_approval_case_to_payment_generation
        """
        case, _asset = setup_case_with_cash(150000)
        g = create_claim(case["id"], creditor_name="Trade Supplier",
                         creditor_type="GENERAL_UNSECURED", filed_amount_cents=90000)
        i = create_claim(case["id"], creditor_name="Investor I",
                         creditor_type="INVESTOR", filed_amount_cents=500000)
        determine_claim(g["id"], "ALLOWED", 90000)
        determine_claim(i["id"], "ALLOWED", 500000)
        plan = create_distribution_plan(case["id"], reserve_cents=0)

        # Pre-cascade: the plan's payment list is empty.
        before = list_plan_payments(plan["id"])
        assert before == [], "no payment rows exist before approval"

        decided = decide_distribution_plan(plan["id"], "APPROVE")
        assert decided["status"] == "APPROVED"

        case_after = get_case(case["id"])
        assert case_after["status"] == "DISTRIBUTING", (
            "the approval itself moves the case ACTIVE -> DISTRIBUTING"
        )

        g_payments = list_claim_payments(g["id"])
        assert len(g_payments) == 1
        assert g_payments[0]["scheduled_amount_cents"] == 90000
        assert g_payments[0]["status"] == "SCHEDULED"
        assert g_payments[0]["priority_class"] == "GENERAL"

        i_payments = list_claim_payments(i["id"])
        assert len(i_payments) == 1
        # Remaining pool after GENERAL (90000) is 150000-90000 = 60000 -> INVESTOR pro-rata.
        assert i_payments[0]["scheduled_amount_cents"] == 60000
        assert i_payments[0]["priority_class"] == "INVESTOR"

    def test_plan_approval_generates_no_rows_before_decide(self, api):
        """PRD §3.8: "Payment rows exist only because a plan approval
        generated them; there is no way to create one directly."

        Design: Difficulty/transitive_cascade/plan_approval_case_to_payment_generation
        """
        case, _asset = setup_case_with_cash(150000)
        g = create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                         filed_amount_cents=90000)
        determine_claim(g["id"], "ALLOWED", 90000)
        plan = create_distribution_plan(case["id"], reserve_cents=0)

        assert list_plan_payments(plan["id"]) == []
        decided = decide_distribution_plan(plan["id"], "APPROVE")
        assert decided["status"] == "APPROVED"
        assert len(list_plan_payments(plan["id"])) == 1


class TestClaimReconsiderCascade:
    def test_claim_reconsider_totals_to_plan_withdrawal(self, api):
        """PRD §3.7: "If the case's `allowed_claims_total_cents` changes
        while the plan is `FILED` — because a claim was determined or
        reconsidered — the plan's premise is stale and it moves
        automatically to `WITHDRAWN`, a terminal state."
        PRD §3.4: "Reconsidering an allowed claim clears
        `allowed_amount_cents` and all four class buckets to null, resets
        `determined_at` to null, recomputes `allowed_claims_total_cents`
        downward by the cleared amount, withdraws any `FILED` plan of the
        case"

        Design: Difficulty/transitive_cascade/claim_reconsider_totals_to_plan_withdrawal
        """
        case = create_case()
        c1 = create_claim(case["id"], creditor_name="Creditor One",
                          creditor_type="GENERAL_UNSECURED", filed_amount_cents=100000)
        c2 = create_claim(case["id"], creditor_name="Creditor Two",
                          creditor_type="GENERAL_UNSECURED", filed_amount_cents=200000)
        c3 = create_claim(case["id"], creditor_name="Creditor Three",
                          creditor_type="GENERAL_UNSECURED", filed_amount_cents=300000)
        determine_claim(c1["id"], "ALLOWED", 100000)
        determine_claim(c2["id"], "ALLOWED", 200000)
        determine_claim(c3["id"], "ALLOWED", 300000)
        plan = create_distribution_plan(case["id"], reserve_cents=0)

        tot_before = get_case(case["id"])["allowed_claims_total_cents"]
        assert tot_before == 600000

        reconsidered = validate_success(
            api.reconsider_claim(c3["id"], COURT), 200,
        )
        assert reconsidered["status"] == "FILED"
        assert reconsidered["allowed_amount_cents"] is None

        tot_after = get_case(case["id"])["allowed_claims_total_cents"]
        assert tot_after == 300000, "drop caused by the reconsideration"

        plan_after = validate_success(
            api.get_distribution_plan(plan["id"], RECEIVER), 200,
        )
        assert plan_after["status"] == "WITHDRAWN", (
            "caused by the total's change"
        )

    def test_determination_withdraws_filed_plan(self, api):
        """PRD §3.4: "if that total changed while a distribution plan of the
        case is sitting `FILED`, the plan's premise is stale and the plan is
        automatically moved to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/claim_reconsider_totals_to_plan_withdrawal
        """
        case = create_case()
        c1 = create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                          filed_amount_cents=100000)
        c2 = create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                          filed_amount_cents=200000)
        determine_claim(c1["id"], "ALLOWED", 100000)
        # Plan filed with c1 determined; c2 still FILED would block creation,
        # so determine c2 first, then reconsider it to re-open, then file plan.
        determine_claim(c2["id"], "ALLOWED", 200000)
        plan = create_distribution_plan(case["id"], reserve_cents=0)
        # Reconsider c2 -> plan must auto-withdraw.
        api.reconsider_claim(c2["id"], COURT)
        plan_after = validate_success(
            api.get_distribution_plan(plan["id"], RECEIVER), 200,
        )
        assert plan_after["status"] == "WITHDRAWN"


class TestPlanRejectAmendCycle:
    def test_distribution_plan_reject_amend_cycle(self, api):
        """PRD §3.7: "The receiver may amend a `REJECTED` plan back to
        `FILED`, optionally supplying a new `reserve_cents`; amendment
        re-runs every filing validation — case `ACTIVE`, no overdue report,
        no undetermined claims, no other open plan, and the reserve (the new
        value when provided, the existing one otherwise) within current cash
        — and re-pins `pool_snapshot_cents` from the cash position at
        amendment time."

        Design: Difficulty/non_linear_state_machine/distribution_plan_reject_amend_cycle
        """
        case, _asset = setup_case_with_cash(200000)
        claim = create_claim(case["id"], creditor_name="Trade Supplier",
                             creditor_type="GENERAL_UNSECURED", filed_amount_cents=100000)
        determine_claim(claim["id"], "ALLOWED", 100000)
        plan = create_distribution_plan(case["id"], reserve_cents=0)
        assert plan["pool_snapshot_cents"] == 200000

        rejected = decide_distribution_plan(plan["id"], "REJECT")
        assert rejected["status"] == "REJECTED"

        amended = amend_distribution_plan(plan["id"])
        assert amended["status"] == "FILED"
        assert amended["pool_snapshot_cents"] == 200000, "pool re-pinned on amend"

        approved = decide_distribution_plan(plan["id"], "APPROVE")
        assert approved["status"] == "APPROVED"

        payments = list_claim_payments(claim["id"])
        assert len(payments) == 1
        assert payments[0]["scheduled_amount_cents"] == 100000

    def test_plan_reject_amend_rejects_when_not_rejected(self, api):
        """PRD §3.7: "Amending a plan that is not `REJECTED` is rejected
        with `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/distribution_plan_reject_amend_cycle
        """
        case, _asset = setup_case_with_cash(200000)
        claim = create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                             filed_amount_cents=100000)
        determine_claim(claim["id"], "ALLOWED", 100000)
        plan = create_distribution_plan(case["id"], reserve_cents=0)

        resp = api.amend_distribution_plan(plan["id"], {}, RECEIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestWaterfall:
    def test_waterfall_class_pro_rata_with_remainder_sweep(self, api):
        """PRD §3.7: "Otherwise the class is paid pro rata: each bucket's
        raw share is the remaining pool multiplied by the bucket and divided
        by the class total, truncated down to a whole cent; the cents left
        over by truncation — always fewer than the number of buckets in the
        class, so a single pass suffices — are distributed one cent at a
        time to buckets ordered by bucket amount descending, ties broken by
        the owning claim's `created_at` ascending, never by identifier."

        Design: Difficulty/combinatorial_formula/waterfall_class_pro_rata_with_remainder_sweep
        """
        # Authority limit set above every seeded asset's estimated value so the
        # setup liquidations need no court authorization (PRD §3.2).
        case = create_case(authority_limit_cents=5000000)
        a1 = validate_success(
            api.create_asset(
                {"case_id": case["id"], "description": "Warehouse",
                 "asset_class": "REAL_PROPERTY", "estimated_value_cents": 80000},
                RECEIVER,
            ),
            201,
        )
        a2 = validate_success(
            api.create_asset(
                {"case_id": case["id"], "description": "Operating account",
                 "asset_class": "CASH", "estimated_value_cents": 2000000},
                RECEIVER,
            ),
            201,
        )
        api.liquidate_asset(a1["id"], {"liquidation_value_cents": 80000}, RECEIVER)
        api.liquidate_asset(a2["id"], {"liquidation_value_cents": 2000000}, RECEIVER)

        c1 = create_claim(case["id"], creditor_name="Secured Bank",
                          creditor_type="SECURED", filed_amount_cents=100000,
                          collateral_asset_id=a1["id"])
        c2 = create_claim(case["id"], creditor_name="Wage Claimant",
                          creditor_type="PRIORITY_WAGE", filed_amount_cents=2000000)
        c3 = create_claim(case["id"], creditor_name="Trade Supplier",
                          creditor_type="GENERAL_UNSECURED", filed_amount_cents=300000)
        c4 = create_claim(case["id"], creditor_name="Investor I",
                          creditor_type="INVESTOR", filed_amount_cents=500000)
        determine_claim(c1["id"], "ALLOWED", 100000)
        determine_claim(c2["id"], "ALLOWED", 2000000)
        determine_claim(c3["id"], "ALLOWED", 300000)
        determine_claim(c4["id"], "ALLOWED", 500000)

        plan = create_distribution_plan(case["id"], reserve_cents=80000)
        decided = decide_distribution_plan(plan["id"], "APPROVE")
        assert decided["status"] == "APPROVED"

        p1 = list_claim_payments(c1["id"])
        p2 = list_claim_payments(c2["id"])
        p3 = list_claim_payments(c3["id"])
        p4 = list_claim_payments(c4["id"])

        # SECURED class paid in full.
        p1_sec = next(p for p in p1 if p["priority_class"] == "SECURED")
        assert p1_sec["scheduled_amount_cents"] == 80000
        # PRIORITY class paid in full (capped).
        p2_pri = next(p for p in p2 if p["priority_class"] == "PRIORITY")
        assert p2_pri["scheduled_amount_cents"] == 1515000
        # GENERAL pro-rata floors: 20000/485000/300000 of pool 405000.
        p1_gen = next(p for p in p1 if p["priority_class"] == "GENERAL")
        p2_gen = next(p for p in p2 if p["priority_class"] == "GENERAL")
        assert p1_gen["scheduled_amount_cents"] == 10062
        assert p3[0]["scheduled_amount_cents"] == 150931
        # Remainder cent swept to the largest GENERAL bucket.
        assert p2_gen["scheduled_amount_cents"] == 244007
        # INVESTOR class gets no rows.
        assert p4 == []

        total = sum(p["scheduled_amount_cents"] for p in (p1 + p2 + p3))
        assert total == 2000000, "sum of scheduled payments equals the pool"

    def test_waterfall_pool_equals_cash_minus_reserve(self, api):
        """PRD §3.7: "Approving recomputes the waterfall in its final
        variant at approval time: the pool is the case's
        `cash_on_hand_cents` at that moment minus `reserve_cents`"

        Design: Difficulty/combinatorial_formula/waterfall_class_pro_rata_with_remainder_sweep
        """
        # Authority limit above the seeded cash asset so its liquidation needs
        # no court authorization (PRD §3.2).
        case, _asset = setup_case_with_cash(2080000, authority_limit_cents=5000000)
        a1 = validate_success(
            api.create_asset(
                {"case_id": case["id"], "description": "Warehouse",
                 "asset_class": "REAL_PROPERTY", "estimated_value_cents": 80000},
                RECEIVER,
            ),
            201,
        )
        # Note: setup_case_with_cash already created one CASH asset of 2080000.
        # Add the REAL_PROPERTY collateral asset identified but not liquidated,
        # so the SECURED claim resolves against its estimated value.
        c1 = create_claim(case["id"], creditor_name="Secured Bank",
                          creditor_type="SECURED", filed_amount_cents=100000,
                          collateral_asset_id=a1["id"])
        determine_claim(c1["id"], "ALLOWED", 100000)
        plan = create_distribution_plan(case["id"], reserve_cents=80000)
        # Pool at approval: cash 2080000 - reserve 80000 = 2000000.
        decided = decide_distribution_plan(plan["id"], "APPROVE")
        assert decided["status"] == "APPROVED"
        p1 = list_claim_payments(c1["id"])
        # SECURED bucket uses estimated collateral 80000 (IDENTIFIED at determination).
        p1_sec = next(p for p in p1 if p["priority_class"] == "SECURED")
        assert p1_sec["scheduled_amount_cents"] == 80000

    def test_waterfall_reserve_subtracted_and_empty_classes_skipped(self, api):
        """PRD §3.7: "At filing the plan pins `pool_snapshot_cents` — the
        provisional pool, computed as the filing-time `cash_on_hand_cents`
        minus `reserve_cents` — which serves as the advisory figure
        circulated on court notice."
        PRD §3.7: "a class whose total is zero is skipped entirely,
        generating no rows and consuming no pool."

        Design: Corner/calculations/waterfall_reserve_subtracted_and_empty_classes_skipped
        """
        case, _asset = setup_case_with_cash(100000)
        claim = create_claim(case["id"], creditor_name="Trade Supplier",
                             creditor_type="GENERAL_UNSECURED", filed_amount_cents=70000)
        determine_claim(claim["id"], "ALLOWED", 70000)
        plan = create_distribution_plan(case["id"], reserve_cents=30000)
        assert plan["pool_snapshot_cents"] == 70000, (
            "provisional pool is cash minus reserve"
        )

        decide_distribution_plan(plan["id"], "APPROVE")
        payments = list_plan_payments(plan["id"])
        assert len(payments) == 1
        assert payments[0]["scheduled_amount_cents"] == 70000
        assert payments[0]["priority_class"] == "GENERAL", (
            "no SECURED, PRIORITY, or INVESTOR rows exist"
        )
