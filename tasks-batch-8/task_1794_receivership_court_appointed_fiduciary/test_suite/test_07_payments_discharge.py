"""Distribution payments: pay/void/cancel, seniority gate, OCC, discharge."""
from test_helpers import (
    COURT,
    RECEIVER,
    ApiErrorId,
    create_approved_engagement,
    create_asset,
    create_case,
    create_claim,
    create_distribution_plan,
    create_fee_application,
    create_status_report,
    decide_distribution_plan,
    decide_fee_application,
    decide_status_report,
    determine_claim,
    get_case,
    liquidate_asset,
    list_claim_payments,
    pay_distribution_payment,
    pay_fee_application,
    setup_case_with_cash,
    validate_error,
    validate_success,
)


def _setup_approved_plan_single_payment(api, cash=50000, claim_amount=50000):
    """Case with one GENERAL claim, plan APPROVED, single SCHEDULED payment."""
    case, _asset = setup_case_with_cash(cash)
    claim = create_claim(case["id"], creditor_name="Trade Supplier",
                         creditor_type="GENERAL_UNSECURED",
                         filed_amount_cents=claim_amount)
    determine_claim(claim["id"], "ALLOWED", claim_amount)
    plan = create_distribution_plan(case["id"], reserve_cents=0)
    decide_distribution_plan(plan["id"], "APPROVE")
    payments = list_claim_payments(claim["id"])
    return case, claim, plan, payments[0]


class TestSeniorClassGate:
    def test_senior_class_payment_blocks_junior(self, api):
        """PRD §3.8: "Seniority is enforced across the plan: no payment of
        the same plan in a strictly senior class may still be `SCHEDULED` —
        `SECURED` before `PRIORITY` before `GENERAL` before `INVESTOR` — and
        a violation is rejected with `ERR_SENIOR_CLASS_UNPAID`; payments
        within the same class may be paid in any order."

        Design: Corner/validations/senior_class_payment_blocks_junior
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
        liquidate_asset(a1["id"], 80000)
        liquidate_asset(a2["id"], 2000000)

        c1 = create_claim(case["id"], creditor_name="Secured Bank",
                          creditor_type="SECURED", filed_amount_cents=100000,
                          collateral_asset_id=a1["id"])
        c2 = create_claim(case["id"], creditor_name="Wage Claimant",
                          creditor_type="PRIORITY_WAGE", filed_amount_cents=2000000)
        c3 = create_claim(case["id"], creditor_name="Trade Supplier",
                          creditor_type="GENERAL_UNSECURED", filed_amount_cents=300000)
        determine_claim(c1["id"], "ALLOWED", 100000)
        determine_claim(c2["id"], "ALLOWED", 2000000)
        determine_claim(c3["id"], "ALLOWED", 300000)
        plan = create_distribution_plan(case["id"], reserve_cents=80000)
        decide_distribution_plan(plan["id"], "APPROVE")

        p1_sec = next(p for p in list_claim_payments(c1["id"])
                      if p["priority_class"] == "SECURED")
        p2_pri = next(p for p in list_claim_payments(c2["id"])
                      if p["priority_class"] == "PRIORITY")
        p3_gen = list_claim_payments(c3["id"])[0]

        v0 = get_case(case["id"])["version"]
        blocked = api.pay_distribution_payment(
            p3_gen["id"], {"expected_case_version": v0}, RECEIVER,
        )
        validate_error(blocked, ApiErrorId.ERR_SENIOR_CLASS_UNPAID)

        assert pay_distribution_payment(p1_sec["id"], v0)["status"] == "PAID"
        v1 = get_case(case["id"])["version"]
        assert pay_distribution_payment(p2_pri["id"], v1)["status"] == "PAID"
        v2 = get_case(case["id"])["version"]
        # The identical junior pay call now succeeds with no senior SCHEDULED rows left.
        assert pay_distribution_payment(p3_gen["id"], v2)["status"] == "PAID"

    def test_senior_class_gate_unlocked_after_seniors_paid(self, api):
        """PRD §3.8: "no payment of the same plan in a strictly senior class
        may still be `SCHEDULED` — `SECURED` before `PRIORITY` before
        `GENERAL` before `INVESTOR` — and a violation is rejected with
        `ERR_SENIOR_CLASS_UNPAID`; payments within the same class may be
        paid in any order."

        Design: Corner/validations/senior_class_payment_blocks_junior
        """
        # Authority limit above the seeded cash asset so its liquidation needs
        # no court authorization (PRD §3.2).
        case = create_case(authority_limit_cents=5000000)
        asset = create_asset(case["id"], asset_class="CASH", estimated_value_cents=2000000)
        liquidate_asset(asset["id"], 2000000)
        wage = create_claim(case["id"], creditor_name="Wage Claimant",
                            creditor_type="PRIORITY_WAGE", filed_amount_cents=40000)
        general = create_claim(case["id"], creditor_name="Trade Supplier",
                               creditor_type="GENERAL_UNSECURED", filed_amount_cents=30000)
        determine_claim(wage["id"], "ALLOWED", 40000)
        determine_claim(general["id"], "ALLOWED", 30000)
        plan = create_distribution_plan(case["id"], reserve_cents=0)
        decide_distribution_plan(plan["id"], "APPROVE")
        p_pri = list_claim_payments(wage["id"])[0]
        p_gen = list_claim_payments(general["id"])[0]

        v0 = get_case(case["id"])["version"]
        blocked = api.pay_distribution_payment(
            p_gen["id"], {"expected_case_version": v0}, RECEIVER,
        )
        validate_error(blocked, ApiErrorId.ERR_SENIOR_CLASS_UNPAID)

        pay_distribution_payment(p_pri["id"], v0)
        v1 = get_case(case["id"])["version"]
        paid = pay_distribution_payment(p_gen["id"], v1)
        assert paid["status"] == "PAID", (
            "with no senior SCHEDULED rows left, the identical junior pay call succeeds"
        )


class TestPaymentCancelOnReconsider:
    def test_payment_cancelled_on_claim_reconsider_conditional_cascade(self, api):
        """PRD §3.4: "Reconsidering an allowed claim clears
        `allowed_amount_cents` and all four class buckets to null, resets
        `determined_at` to null, recomputes `allowed_claims_total_cents`
        downward by the cleared amount, withdraws any `FILED` plan of the
        case, and cancels every distribution payment of that claim still in
        `SCHEDULED` status — moving each to `CANCELLED` with no cash
        movement, since scheduled payments never debited the estate."
        PRD §3.7: "And once every payment of an approved plan has left
        `SCHEDULED` — each `PAID`, `VOIDED`, or `CANCELLED` — the plan moves
        automatically from `APPROVED` to `EXECUTED`, also terminal."

        Design: Corner/state_machines/payment_cancelled_on_claim_reconsider_conditional_cascade
        """
        case, claim, plan, payment = _setup_approved_plan_single_payment(api)
        assert get_case(case["id"])["status"] == "DISTRIBUTING"

        reconsidered = validate_success(api.reconsider_claim(claim["id"], COURT), 200)
        assert reconsidered["status"] == "FILED"

        payments = list_claim_payments(claim["id"])
        assert payments[0]["status"] == "CANCELLED"

        assert get_case(case["id"])["cash_on_hand_cents"] == 50000, (
            "a SCHEDULED payment never debited cash, so cancellation moves nothing"
        )
        plan_after = validate_success(
            api.get_distribution_plan(plan["id"], RECEIVER), 200,
        )
        assert plan_after["status"] == "EXECUTED", "no SCHEDULED rows remain"


class TestPlanExecutedBubbleUp:
    def test_plan_executed_bubble_up_when_last_payment_paid(self, api):
        """PRD §3.8: "when the payment was the last `SCHEDULED` row on its
        plan — bubbles the plan up to `EXECUTED`."

        Design: Corner/state_machines/plan_executed_bubble_up_when_last_payment_paid
        """
        case, claim, plan, payment = _setup_approved_plan_single_payment(api)
        v = get_case(case["id"])["version"]
        paid = pay_distribution_payment(payment["id"], v)
        assert paid["status"] == "PAID"

        plan_after = validate_success(
            api.get_distribution_plan(plan["id"], RECEIVER), 200,
        )
        assert plan_after["status"] == "EXECUTED", (
            "bubble-up fired on the last SCHEDULED payment resolving"
        )


class TestPaymentVoid:
    def test_void_after_plan_executed_rejected(self, api):
        """PRD §3.8: "The court may void a payment that has been `PAID` —
        an uncashed check, for instance — but only while the payment's plan
        is still `APPROVED`; once the plan has reached `EXECUTED` the void
        window has closed and the attempt is rejected with
        `ERR_PLAN_NOT_EXECUTING`."

        Design: Corner/errors/void_after_plan_executed_rejected
        """
        case, claim, plan, payment = _setup_approved_plan_single_payment(api)
        v = get_case(case["id"])["version"]
        pay_distribution_payment(payment["id"], v)
        # The single payment resolved -> plan EXECUTED.
        resp = api.void_distribution_payment(payment["id"], COURT)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_EXECUTING)

    def test_payment_pay_void_conserves_estate_cash(self, api):
        """PRD §2.4: "A conservation invariant holds at all times: the
        case's `cash_on_hand_cents`, plus the approved amounts of all paid
        fee applications, plus the paid amounts of distribution payments
        still in `PAID` status (a payment later voided no longer counts,
        because voiding credits the cash back), plus the amounts of all
        approved `EXPENDITURE` authorizations, exactly equals the total
        liquidation proceeds."

        Design: Difficulty/compensating_invariant/payment_pay_void_conserves_estate_cash
        """
        case, _asset = setup_case_with_cash(50000)
        g1 = create_claim(case["id"], creditor_name="Creditor One",
                          creditor_type="GENERAL_UNSECURED", filed_amount_cents=30000)
        g2 = create_claim(case["id"], creditor_name="Creditor Two",
                          creditor_type="GENERAL_UNSECURED", filed_amount_cents=20000)
        determine_claim(g1["id"], "ALLOWED", 30000)
        determine_claim(g2["id"], "ALLOWED", 20000)
        plan = create_distribution_plan(case["id"], reserve_cents=0)
        decide_distribution_plan(plan["id"], "APPROVE")
        p1 = list_claim_payments(g1["id"])[0]

        v0 = get_case(case["id"])["version"]
        cash0 = get_case(case["id"])["cash_on_hand_cents"]
        assert cash0 == 50000

        paid = pay_distribution_payment(p1["id"], v0)
        assert paid["status"] == "PAID"
        assert get_case(case["id"])["cash_on_hand_cents"] == 20000

        voided = validate_success(
            api.void_distribution_payment(p1["id"], COURT), 200,
        )
        assert voided["status"] == "VOIDED"
        assert get_case(case["id"])["cash_on_hand_cents"] == 50000, (
            "forward + compensating action leaves estate cash exactly unchanged"
        )

    def test_void_credits_cash_back_and_keeps_paid_amount(self, api):
        """PRD §3.8: "Voiding moves the payment to `VOIDED` and credits
        `paid_amount_cents` back to the case's `cash_on_hand_cents`,
        incrementing the case's `version` and recomputing `posture`; the
        voided row retains its `paid_amount_cents` for audit even though
        the cash has returned."

        Design: Difficulty/compensating_invariant/payment_pay_void_conserves_estate_cash
        """
        case, _asset = setup_case_with_cash(50000)
        g1 = create_claim(case["id"], creditor_name="Creditor One",
                          creditor_type="GENERAL_UNSECURED", filed_amount_cents=30000)
        g2 = create_claim(case["id"], creditor_name="Creditor Two",
                          creditor_type="GENERAL_UNSECURED", filed_amount_cents=20000)
        determine_claim(g1["id"], "ALLOWED", 30000)
        determine_claim(g2["id"], "ALLOWED", 20000)
        plan = create_distribution_plan(case["id"], reserve_cents=0)
        decide_distribution_plan(plan["id"], "APPROVE")
        p1 = list_claim_payments(g1["id"])[0]

        v0 = get_case(case["id"])["version"]
        pay_distribution_payment(p1["id"], v0)
        assert get_case(case["id"])["cash_on_hand_cents"] == 20000

        voided = validate_success(
            api.void_distribution_payment(p1["id"], COURT), 200,
        )
        assert voided["status"] == "VOIDED"
        assert voided["paid_amount_cents"] == 30000, "kept for audit"
        assert get_case(case["id"])["cash_on_hand_cents"] == 50000


class TestPaymentOCC:
    def test_occ_payment_pay_stale_case_version_rejected(self, api):
        """PRD §2.7: "Each of these requests must carry
        `expected_case_version`, a non-optional input holding the `version`
        of the case as the client last read it. If the case's current
        `version` has advanced past that value — because a liquidation, a
        fee payment, an expenditure approval, a distribution payment, or a
        void has since landed — the request is rejected with
        `ERR_STALE_CASE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_payment_pay_stale_case_version_rejected
        """
        case, _asset = setup_case_with_cash(50000)
        g1 = create_claim(case["id"], creditor_name="Creditor One",
                          creditor_type="GENERAL_UNSECURED", filed_amount_cents=30000)
        g2 = create_claim(case["id"], creditor_name="Creditor Two",
                          creditor_type="GENERAL_UNSECURED", filed_amount_cents=20000)
        determine_claim(g1["id"], "ALLOWED", 30000)
        determine_claim(g2["id"], "ALLOWED", 20000)
        plan = create_distribution_plan(case["id"], reserve_cents=0)
        decide_distribution_plan(plan["id"], "APPROVE")
        p1 = list_claim_payments(g1["id"])[0]
        p2 = list_claim_payments(g2["id"])[0]

        v_obs = get_case(case["id"])["version"]
        paid = pay_distribution_payment(p1["id"], v_obs)
        assert paid["status"] == "PAID"

        # The previously observed version is now stale.
        resp = api.pay_distribution_payment(
            p2["id"], {"expected_case_version": v_obs}, RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)

    def test_occ_payment_pay_second_pay_after_version_advanced(self, api):
        """PRD §3.8: "The receiver pays a `SCHEDULED` payment — the second
        of the two OCC-guarded cash writes — carrying
        `expected_case_version` equal to the case's current `version`,
        failing with `ERR_STALE_CASE_VERSION` (HTTP 412) on mismatch."

        Design: Corner/cross_cutting_layers/occ_payment_pay_stale_case_version_rejected
        """
        case, _asset = setup_case_with_cash(50000)
        g1 = create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                          filed_amount_cents=30000)
        g2 = create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                          filed_amount_cents=20000)
        determine_claim(g1["id"], "ALLOWED", 30000)
        determine_claim(g2["id"], "ALLOWED", 20000)
        plan = create_distribution_plan(case["id"], reserve_cents=0)
        decide_distribution_plan(plan["id"], "APPROVE")
        p1 = list_claim_payments(g1["id"])[0]
        p2 = list_claim_payments(g2["id"])[0]

        v = get_case(case["id"])["version"]
        pay_distribution_payment(p1["id"], v)
        resp = api.pay_distribution_payment(
            p2["id"], {"expected_case_version": v}, RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)


class TestInsufficientFunds:
    def test_payment_pay_after_fee_drain_insufficient_funds(self, api):
        """PRD §3.8: "The case's `cash_on_hand_cents` must cover the
        `scheduled_amount_cents`, failing with `ERR_INSUFFICIENT_ESTATE_FUNDS`
        otherwise"

        Design: Corner/errors/payment_pay_after_fee_drain_insufficient_funds
        """
        case, _asset = setup_case_with_cash(50000)
        claim = create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                             filed_amount_cents=50000)
        determine_claim(claim["id"], "ALLOWED", 50000)
        eng = create_approved_engagement(case["id"], fee_cap_cents=1000000)
        app = create_fee_application(
            eng["id"], time_entries=[{"hours": 1.0, "rate_cents": 20000}],
        )
        decide_fee_application(app["id"], "APPROVE", 20000)
        plan = create_distribution_plan(case["id"], reserve_cents=0)
        decide_distribution_plan(plan["id"], "APPROVE")
        payment = list_claim_payments(claim["id"])[0]

        v1 = get_case(case["id"])["version"]
        pay_fee_application(app["id"], v1)
        case_after = get_case(case["id"])
        assert case_after["cash_on_hand_cents"] == 30000

        resp = api.pay_distribution_payment(
            payment["id"], {"expected_case_version": case_after["version"]}, RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ESTATE_FUNDS)

    def test_expenditure_approval_drains_cash_and_blocks_overdraft(self, api):
        """PRD §3.3: "The court may approve only while the case's
        `cash_on_hand_cents` is at least the requested `amount_cents`,
        failing with `ERR_INSUFFICIENT_ESTATE_FUNDS` otherwise. On approval
        the amount is debited from `cash_on_hand_cents` immediately, the
        case's `version` is incremented, and `posture` is recomputed."

        Design: Corner/errors/expenditure_approval_drains_cash_and_blocks_overdraft
        """
        case, _asset = setup_case_with_cash(50000)
        ar1 = validate_success(
            api.create_authorization_request(
                {"case_id": case["id"], "request_type": "EXPENDITURE",
                 "description": "Pay overdue supplier", "amount_cents": 70000},
                RECEIVER,
            ),
            201,
        )
        ar2 = validate_success(
            api.create_authorization_request(
                {"case_id": case["id"], "request_type": "EXPENDITURE",
                 "description": "Pay utility deposit", "amount_cents": 30000},
                RECEIVER,
            ),
            201,
        )

        resp1 = api.decide_authorization_request(ar1["id"], {"decision": "APPROVE"}, COURT)
        validate_error(resp1, ApiErrorId.ERR_INSUFFICIENT_ESTATE_FUNDS)

        ok = api.decide_authorization_request(ar2["id"], {"decision": "APPROVE"}, COURT)
        assert validate_success(ok, 200)["status"] == "APPROVED"
        assert get_case(case["id"])["cash_on_hand_cents"] == 20000


class TestDischarge:
    def test_discharge_requires_accepted_final_report(self, api):
        """PRD §3.8: "Six aggregate preconditions must all hold, any failure
        surfacing as `ERR_DISCHARGE_BLOCKED`: some plan of the case has
        reached `EXECUTED`; no claim of the case remains `FILED`; no fee
        application of any engagement of the case remains `FILED` or
        `APPROVED`; a `FINAL` status report of the case has been `ACCEPTED`;
        no asset of the case remains `IDENTIFIED`; and `cash_on_hand_cents`
        is exactly zero."

        Design: Difficulty/cross_entity_state_dependency/discharge_requires_accepted_final_report
        """
        case, claim, plan, payment = _setup_approved_plan_single_payment(api)
        v = get_case(case["id"])["version"]
        paid = pay_distribution_payment(payment["id"], v)
        assert paid["status"] == "PAID"
        # Plan is now EXECUTED; cash is 0; claims all determined; no FILED/PAID
        # fee applications; the single asset is LIQUIDATED.
        assert get_case(case["id"])["cash_on_hand_cents"] == 0

        blocked = api.discharge_case(case["id"], COURT)
        validate_error(blocked, ApiErrorId.ERR_DISCHARGE_BLOCKED)

        report = create_status_report(
            case["id"], report_type="FINAL",
            period_start="2026-08-01T00:00:00Z", period_end="2026-09-01T00:00:00Z",
            narrative="Final accounting: all assets liquidated, all allowed claims paid in full.",
        )
        decide_status_report(report["id"], "APPROVE")

        discharged = validate_success(api.discharge_case(case["id"], COURT), 200)
        assert discharged["status"] == "DISCHARGED"

    def test_discharge_blocked_until_final_report_accepted(self, api):
        """PRD §3.8: "a `FINAL` status report of the case has been
        `ACCEPTED`"

        Design: Difficulty/cross_entity_state_dependency/discharge_requires_accepted_final_report
        """
        case, claim, plan, payment = _setup_approved_plan_single_payment(api)
        v = get_case(case["id"])["version"]
        pay_distribution_payment(payment["id"], v)

        # FINAL report filed but not yet accepted -> still blocked.
        report = create_status_report(
            case["id"], report_type="FINAL",
            period_start="2026-08-01T00:00:00Z", period_end="2026-09-01T00:00:00Z",
            narrative="Final accounting.",
        )
        blocked = api.discharge_case(case["id"], COURT)
        validate_error(blocked, ApiErrorId.ERR_DISCHARGE_BLOCKED)

        decide_status_report(report["id"], "APPROVE")
        discharged = validate_success(api.discharge_case(case["id"], COURT), 200)
        assert discharged["status"] == "DISCHARGED"


class TestDetermineReconsiderInvariant:
    def test_determine_reconsider_conserves_claim_exposure(self, api):
        """PRD §2.4: "The `allowed_claims_total_cents` is the sum of
        `allowed_amount_cents` over the case's claims currently in `ALLOWED`
        status."
        PRD §3.4: "Reconsidering an allowed claim clears
        `allowed_amount_cents` and all four class buckets to null, resets
        `determined_at` to null, recomputes `allowed_claims_total_cents`
        downward by the cleared amount"

        Design: Difficulty/compensating_invariant/determine_reconsider_conserves_claim_exposure
        """
        case = create_case()
        d1 = create_claim(case["id"], creditor_name="Creditor D1",
                          creditor_type="GENERAL_UNSECURED", filed_amount_cents=40000)
        d2 = create_claim(case["id"], creditor_name="Creditor D2",
                          creditor_type="GENERAL_UNSECURED", filed_amount_cents=60000)

        tot0 = get_case(case["id"])["allowed_claims_total_cents"]
        assert tot0 == 0

        allowed = determine_claim(d1["id"], "ALLOWED", 40000)
        assert allowed["status"] == "ALLOWED"
        tot1 = get_case(case["id"])["allowed_claims_total_cents"]
        assert tot1 == 40000

        reconsidered = validate_success(api.reconsider_claim(d1["id"], COURT), 200)
        assert reconsidered["status"] == "FILED"
        tot2 = get_case(case["id"])["allowed_claims_total_cents"]
        assert tot2 == 0

    def test_determine_reconsider_pair_restores_allowed_total(self, api):
        """PRD §3.4: "Determination stamps `determined_at` from the logical
        clock and recomputes the case's `allowed_claims_total_cents`"
        PRD §3.4: "Reconsidering an allowed claim clears
        `allowed_amount_cents` and all four class buckets to null, resets
        `determined_at` to null, recomputes `allowed_claims_total_cents`
        downward by the cleared amount"

        Design: Difficulty/compensating_invariant/determine_reconsider_conserves_claim_exposure
        """
        case = create_case()
        d1 = create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                          filed_amount_cents=40000)
        create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                     filed_amount_cents=60000)
        determine_claim(d1["id"], "ALLOWED", 40000)
        assert get_case(case["id"])["allowed_claims_total_cents"] == 40000
        api.reconsider_claim(d1["id"], COURT)
        assert get_case(case["id"])["allowed_claims_total_cents"] == 0
