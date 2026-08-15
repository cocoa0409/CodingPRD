"""Expense claims: tax gross-up variants, marginal bracket ordering, resubmission."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    assert_case_ledger,
    create_case_in_progress,
    setup_case_with_vendor,
    create_claim,
    create_approved_claim,
    approve_claim,
    reject_claim,
    pay_claim,
    create_completed_travel_booking,
    create_assignment_in_state,
    get_case,
)

MC = TEST_USERS["coordinator_headers"]
FIN = TEST_USERS["finance_headers"]


class TestPayGate:
    def test_pay_submitted_claim_rejected(self):
        """PRD §3.5: "Payment (`APPROVED` → `PAID`, by a `FinanceSpecialist`) is
        where the tax gross-up runs, and only taxable claims earn one — a
        `DIRECT_BILL` claim's `gross_up_cents` is zero."
        PRD §2.10: "State validity**: the target resource is in a legal source
        state for the requested transition (`ERR_INVALID_STATE`, HTTP 409)"

        Design: Corner/state_machines/pay_submitted_claim_rejected
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        claim = create_claim(case_id, emp_id, amount_cents=10000)
        assert claim["status"] == "SUBMITTED"

        resp = api_client.pay_claim(claim["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        claim_after = validate_success(api_client.get_expense_claim(claim["id"], MC))
        assert claim_after["status"] == "SUBMITTED"
        assert claim_after["gross_up_cents"] == 0
        assert claim_after["total_payment_cents"] == 0
        assert_case_ledger(get_case(case_id), committed=0, paid=0, released=0)


class TestGrossUpVariants:
    def test_gross_up_flat_supplemental_claim(self):
        """PRD §3.5: "Under a `FLAT_SUPPLEMENTAL` policy, the gross-up is the
        claim's net `amount_cents` multiplied by `flat_gross_up_rate` and
        divided by one minus that rate, rounded half up to a whole cent; the
        case's payment history plays no part."
        PRD §3.5: "At payment, the claim's `total_payment_cents` is stamped as
        `amount_cents` plus `gross_up_cents`"

        Design: Difficulty/dual_variant_calc/gross_up_flat_vs_marginal
        """
        ctx = create_case_in_progress()  # FLAT_SUPPLEMENTAL, rate 0.22
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        claim = create_claim(case_id, emp_id, category="MEALS",
                             lines=[{"description": "Meals wk1", "amount_cents": 60000},
                                    {"description": "Meals wk2", "amount_cents": 40000}])
        assert claim["amount_cents"] == 100000
        approve_claim(claim["id"], case_id)

        paid = pay_claim(claim["id"])
        # round_half_up(100000 x 0.22 / 0.78) = round_half_up(28205.128...) = 28205
        assert paid["gross_up_cents"] == 28205
        assert paid["total_payment_cents"] == 128205
        assert paid["status"] == "PAID"

    def test_gross_up_marginal_aggregate_claim(self):
        """PRD §3.5: "Under `MARGINAL_AGGREGATE`, the case's
        `cumulative_taxable_paid_cents` — the running total of the case's
        already-paid taxable claim amounts, accumulated in `paid_at` order — is
        set against the policy's `marginal_bracket_threshold_cents`."
        PRD §3.5: "The below-bracket portion is grossed up at
        `marginal_rate_low` and the above-bracket portion at
        `marginal_rate_high`, each rounded half up to a whole cent on its own,
        and the two rounded results are summed into `gross_up_cents`."

        Design: Difficulty/dual_variant_calc/gross_up_flat_vs_marginal
        """
        ctx = create_case_in_progress(
            policy_overrides={"job_level": "DIRECTOR",
                              "gross_up_method": "MARGINAL_AGGREGATE",
                              "marginal_bracket_threshold_cents": 100000,
                              "marginal_rate_low": 0.25,
                              "marginal_rate_high": 0.4},
            employee_overrides={"job_level": "DIRECTOR"})
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        claim = create_claim(case_id, emp_id, category="MEALS",
                             lines=[{"description": "Meals wk1", "amount_cents": 60000},
                                    {"description": "Meals wk2", "amount_cents": 40000}])
        assert claim["amount_cents"] == 100000
        approve_claim(claim["id"], case_id)

        paid = pay_claim(claim["id"])
        # Cumulative is 0: below = min(100000, 100000 - 0) = 100000, above = 0.
        # round_half_up(100000 x 0.25 / 0.75) = round_half_up(33333.33...) = 33333
        assert paid["gross_up_cents"] == 33333
        assert paid["total_payment_cents"] == 133333
        case_after = get_case(case_id)
        assert case_after["cumulative_taxable_paid_cents"] == 100000
        assert case_after["total_paid_cents"] == 133333


class TestGrossUpEvaluationOrder:
    def test_gross_up_circular_evaluation_order(self):
        """PRD §3.5: "The gross-up principle is that tax is levied on the gross
        payment, so each grossed-up portion equals its net portion multiplied by
        the applicable rate and divided by one minus that rate."
        PRD §3.5: "Under a `FLAT_SUPPLEMENTAL` policy, the gross-up is the
        claim's net `amount_cents` multiplied by `flat_gross_up_rate` and
        divided by one minus that rate, rounded half up to a whole cent"

        Design: Difficulty/combinatorial_formula/gross_up_circular_evaluation_order
        """
        ctx = create_case_in_progress(
            policy_overrides={"job_level": "ASSOCIATE",
                              "hhg_cap_cents": 300000,
                              "temp_housing_cap_cents": 150000,
                              "temp_housing_max_nights": 14,
                              "travel_cap_cents": 60000,
                              "misc_cap_cents": 100000,
                              "repayment_window_months": 12},
            employee_overrides={"job_level": "ASSOCIATE"})
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        claim = create_approved_claim(case_id, emp_id, amount_cents=50000,
                                      category="TRANSPORT")

        paid = pay_claim(claim["id"])
        # Tax on the GROSS: round_half_up(50000 x 0.22 / 0.78) = 14103.
        assert paid["gross_up_cents"] == 14103
        # The naive net-times-rate order (50000 x 0.22 = 11000) is wrong.
        assert paid["gross_up_cents"] != 11000
        assert paid["total_payment_cents"] == 64103
        assert get_case(case_id)["total_paid_cents"] == 64103

    def test_gross_up_evaluation_order_second_amount(self):
        """PRD §3.5: "The gross-up principle is that tax is levied on the gross
        payment, so each grossed-up portion equals its net portion multiplied by
        the applicable rate and divided by one minus that rate."
        PRD §3.5: "for taxable claims the case's `cumulative_taxable_paid_cents`
        additionally grows by `amount_cents`."

        Design: Difficulty/combinatorial_formula/gross_up_circular_evaluation_order
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        claim = create_approved_claim(case_id, emp_id, amount_cents=45000)

        paid = pay_claim(claim["id"])
        # round_half_up(45000 x 0.22 / 0.78) = round_half_up(12692.307...) = 12692.
        assert paid["gross_up_cents"] == 12692
        assert paid["gross_up_cents"] != 9900  # naive 45000 x 0.22
        assert paid["total_payment_cents"] == 57692
        case_after = get_case(case_id)
        assert case_after["cumulative_taxable_paid_cents"] == 45000
        assert case_after["total_paid_cents"] == 57692


class TestMarginalBracketOrdering:
    def test_marginal_gross_up_applies_bracket_by_payment_order(self):
        """PRD §3.5: "The portion of the new claim that still fits under the
        bracket is the smaller of the net amount and the threshold minus the
        cumulative total, floored at zero; whatever remains of the net amount
        sits above the bracket."
        PRD §3.5: "Two identical claims can therefore gross up differently
        depending on the order in which they are paid."

        Design: Corner/calculations/marginal_gross_up_applies_bracket_by_payment_order
        """
        ctx = create_case_in_progress(
            policy_overrides={"job_level": "DIRECTOR",
                              "gross_up_method": "MARGINAL_AGGREGATE",
                              "marginal_bracket_threshold_cents": 100000,
                              "marginal_rate_low": 0.25,
                              "marginal_rate_high": 0.4},
            employee_overrides={"job_level": "DIRECTOR"})
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        claim_a = create_approved_claim(case_id, emp_id, amount_cents=60000)
        claim_b = create_approved_claim(case_id, emp_id, amount_cents=50000)

        paid_a = pay_claim(claim_a["id"])
        # Fully below the bracket: round_half_up(60000 x 0.25 / 0.75) = 20000.
        assert paid_a["gross_up_cents"] == 20000
        assert paid_a["total_payment_cents"] == 80000

        paid_b = pay_claim(claim_b["id"])
        # Cumulative is now 60000: below = min(50000, 100000 - 60000) = 40000,
        # above = 10000. 40000 x 0.25/0.75 -> 13333; 10000 x 0.40/0.60 -> 6667.
        assert paid_b["gross_up_cents"] == 20000
        assert paid_b["total_payment_cents"] == 70000

        case_after = get_case(case_id)
        assert case_after["cumulative_taxable_paid_cents"] == 110000
        assert case_after["total_paid_cents"] == 150000


class TestDirectBill:
    def test_direct_bill_claim_gets_zero_gross_up(self):
        """PRD §3.5: "Payment (`APPROVED` → `PAID`, by a `FinanceSpecialist`) is
        where the tax gross-up runs, and only taxable claims earn one — a
        `DIRECT_BILL` claim's `gross_up_cents` is zero."
        PRD §3.5: "a claim is taxable exactly when its payment method is
        `REIMBURSEMENT`."

        Design: Corner/calculations/direct_bill_claim_gets_zero_gross_up
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        claim = create_claim(case_id, emp_id, amount_cents=40000,
                             category="LODGING", payment_method="DIRECT_BILL")
        assert claim["taxable"] is False
        approve_claim(claim["id"], case_id)

        paid = pay_claim(claim["id"])
        assert paid["gross_up_cents"] == 0
        assert paid["total_payment_cents"] == 40000
        case_after = get_case(case_id)
        assert case_after["total_paid_cents"] == 40000
        assert case_after["cumulative_taxable_paid_cents"] == 0


class TestResubmissionCycle:
    def test_expense_claim_resubmit_cycle(self):
        """PRD §3.5: "The owning employee may resubmit a rejected claim
        (`REJECTED` → `SUBMITTED`); when replacement `lines` are supplied they
        supplant the old ones and `amount_cents` is recomputed, and in every
        resubmission `reject_reason` is cleared."
        PRD §3.5: "At payment, the claim's `total_payment_cents` is stamped as
        `amount_cents` plus `gross_up_cents`"

        Design: Difficulty/non_linear_state_machine/expense_claim_resubmit_cycle
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        claim = create_claim(case_id, emp_id, amount_cents=60000, category="MISC")
        rejected = reject_claim(claim["id"], "receipt missing")
        assert rejected["status"] == "REJECTED"
        assert rejected["reject_reason"] == "receipt missing"

        resubmitted = get_success_data(api_client.resubmit_claim(
            claim["id"],
            {"lines": [{"description": "Supplies (corrected)", "amount_cents": 45000}]},
            make_employee_headers(emp_id)))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["amount_cents"] == 45000
        assert resubmitted["reject_reason"] is None

        approve_claim(claim["id"], case_id)
        paid = pay_claim(claim["id"])
        # round_half_up(45000 x 0.22 / 0.78) = 12692
        assert paid["gross_up_cents"] == 12692
        assert paid["total_payment_cents"] == 57692
        assert paid["status"] == "PAID"
        assert get_case(case_id)["total_paid_cents"] == 57692

    def test_resubmit_without_lines_keeps_amount(self):
        """PRD §3.5: "The owning employee may resubmit a rejected claim
        (`REJECTED` → `SUBMITTED`); when replacement `lines` are supplied they
        supplant the old ones and `amount_cents` is recomputed, and in every
        resubmission `reject_reason` is cleared."
        PRD §3.5: "A claim may bounce between submission and rejection any
        number of times."

        Design: Difficulty/non_linear_state_machine/expense_claim_resubmit_cycle
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        claim = create_claim(case_id, emp_id, amount_cents=60000, category="MISC")
        reject_claim(claim["id"], "wrong cost center")

        # No replacement lines: the original lines (and amount) stand.
        resubmitted = get_success_data(api_client.resubmit_claim(
            claim["id"], {}, make_employee_headers(emp_id)))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["amount_cents"] == 60000
        assert resubmitted["reject_reason"] is None

        approve_claim(claim["id"], case_id)
        paid = pay_claim(claim["id"])
        # round_half_up(60000 x 0.22 / 0.78) = round_half_up(16923.07...) = 16923.
        assert paid["gross_up_cents"] == 16923
        assert paid["total_payment_cents"] == 76923


class TestMixedLifecycleReconciliation:
    def test_case_totals_reconcile_after_mixed_lifecycle(self):
        """PRD §2.6: "`total_paid_cents` tracks funds actually disbursed: the
        `final_invoice_cents` of `PAID` assignments, the `total_cents` of
        `COMPLETED` bookings, the `total_payment_cents` of `PAID` claims, and
        the `capped_benefit_cents` of `SETTLED` home-sale transactions."
        PRD §3.5: "for taxable claims the case's `cumulative_taxable_paid_cents`
        additionally grows by `amount_cents`."

        Design: Corner/cross_cutting_complexity_layers/case_totals_reconcile_after_mixed_lifecycle
        """
        ctx = setup_case_with_vendor({"name": "Mix Movers"})
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        vendor_id = ctx["vendor"]["id"]

        # Paid taxable claim: 100000 + 28205 gross-up = 128205.
        claim = create_approved_claim(
            case_id, emp_id, category="MEALS",
            lines=[{"description": "Meals", "amount_cents": 60000},
                   {"description": "More meals", "amount_cents": 40000}])
        pay_claim(claim["id"])

        # Completed travel booking: 61000.
        create_completed_travel_booking(case_id, emp_id, 61000)

        # Paid move invoice: 78000 against an 80000 estimate.
        ma = create_assignment_in_state(case_id, vendor_id, "INVOICED",
                                        estimated_cents=80000,
                                        final_invoice_cents=78000)
        paid_ma = get_success_data(api_client.mark_paid(ma["id"], FIN))
        assert paid_ma["status"] == "PAID"

        case_after = get_case(case_id)
        # 128205 (claim incl. gross-up) + 61000 (travel) + 78000 (invoice).
        assert case_after["total_paid_cents"] == 267205
        assert case_after["total_committed_cents"] == 0
        assert case_after["total_released_cents"] == 0
        # Only the taxable claim amount feeds the cumulative taxable total.
        assert case_after["cumulative_taxable_paid_cents"] == 100000

        vendor = validate_success(api_client.get_vendor(vendor_id, MC))
        assert vendor["completed_moves"] == 1
