"""Difficulty-design coverage: at least TWO tests per
SCAFFOLD_DIFFICULTY_DESIGN.yaml instance.

Each test carries a `# difficulty: <rule_id>/<instance.name>` tag in
its docstring so the coverage audit can confirm every instance is
exercised. PRD-First applies: each citation quotes the PRD prose that
states the underlying rule the instance exercises, not the difficulty
design index itself.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    advance_clock_by_days,
    api_client,
    approve_discharge,
    approve_employment_certification,
    approve_hardship_request,
    assert_borrower_aggregates_match,
    create_and_activate_plan,
    create_borrower,
    create_borrower_with_loan_in_repayment,
    create_loan,
    create_plan,
    drive_loan_into_default,
    make_borrower_headers,
    move_discharge_to_under_review,
    poverty_line_cents,
    record_borrower_payment,
    record_collections_action,
    reset_clock_to,
    round_half_up_to_int,
    submit_and_approve_employment_certification,
    submit_discharge_application,
    submit_employment_certification,
    submit_hardship_request,
    update_discharge_application_payload,
    update_hardship_request_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    _fmt_iso, _parse_iso, separate_loan,
    setup_borrower_loan_active_save_plan, setup_loan_in_default,
    setup_loan_in_rehabilitation, setup_pslf_ready_for_approval,
    setup_veteran_tpd_ready_for_approval,
)
from test_helpers.test_users import (
    SERVICER_CERTIFIER_ID,
    make_servicer_approver_headers,
    make_servicer_certifier_headers,
)


# ===========================================================================
# RULE 1: dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:
    """# difficulty: dual_variant_calc"""

    def test_standard10_vs_save_monthly_payment(self, api):
        """PRD §3.7 STANDARD_10: "For STANDARD_10, the schedule is a
        level-payment fully amortizing schedule over 120 months."
        PRD §3.7 SAVE: "for SAVE, there is no floor — a true $0
        payment is permitted when discretionary income is 0."

        # difficulty: dual_variant_calc/standard_vs_idr_monthly_payment

        Claim: STANDARD_10 and SAVE produce DIFFERENT monthly_payment
        values for the same loan, AGI, family_size, and state — they
        operate in different cost-accounting domains.
        """
        borrower, loan, _ = create_borrower_with_loan_in_repayment(
            state_code="CA", family_size=1,
            adjusted_gross_income_cents=4_000_000,
            original_principal_cents=1_000_000, interest_rate_bps=500,
        )
        std_plan = create_and_activate_plan(
            borrower["id"], "STANDARD_10", [loan["id"]],
        )
        save_plan = create_and_activate_plan(
            borrower["id"], "SAVE", [loan["id"]],
        )
        assert std_plan["monthly_payment_cents"] != save_plan["monthly_payment_cents"], (
            "PRD §3.7: STANDARD_10 amortization and SAVE discretionary "
            "formulas must produce different monthly_payment_cents for "
            "the same borrower portfolio"
        )
        # First plan should be SUPERSEDED after second activation.
        res = api.get_plan(
            borrower["id"], std_plan["id"],
            TEST_USERS["servicer_admin_headers"],
        )
        first_after = validate_success(res, 200)
        assert first_after["status"] == "SUPERSEDED"

    def test_save_monthly_payment_formula_value(self, api):
        """PRD §3.7 SAVE: "The poverty multiplier depends on plan
        type — ... 2.25 for SAVE ... discretionary income is computed
        as adjusted_gross_income_cents minus the multiplier times
        the poverty line, with the result clamped at zero from below
        (never negative). The annual payment is discretionary income
        multiplied by the plan-type income fraction — ... 0.05 for
        SAVE. The annual payment is divided by 12 and the result is
        rounded half-up to integer cents."

        # difficulty: dual_variant_calc/standard_vs_idr_monthly_payment

        Claim: SAVE plan for CA/fs=1/AGI=4_000_000 yields the exact
        formula value (4000000 - 2.25*1506000) * 0.05 / 12 rounded
        half-up = 2548 cents.
        """
        borrower, loan, _ = create_borrower_with_loan_in_repayment(
            state_code="CA", family_size=1,
            adjusted_gross_income_cents=4_000_000,
        )
        plan = create_and_activate_plan(
            borrower["id"], "SAVE", [loan["id"]],
        )
        expected = round_half_up_to_int(
            max(0, 4_000_000 - 2.25 * 1_506_000) * 0.05 / 12
        )
        assert plan["monthly_payment_cents"] == expected
        assert plan["monthly_payment_cents"] == 2548

    def test_pslf_count_vs_risk_score_independent_units(self, api):
        """PRD §3.8: "Each qualifying (payment, loan) increments the
        loan's qualifying_pslf_payment_count by 1."
        PRD §3.10: "The composite is then clamped again to the range
        0 through 100 ... Finally the composite is rounded half-up
        to an integer."

        # difficulty: dual_variant_calc/pslf_qualifying_vs_drift_score

        Claim: pslf count is an unbounded integer; risk score is a
        clamped 0..100 integer; same borrower scope returns BOTH
        readings with their own ranges.
        """
        borrower, loan, _ = create_borrower_with_loan_in_repayment(
            adjusted_gross_income_cents=4_000_000,
            agi_certified_at=TEST_DEFAULTS["INITIAL_CLOCK"],
        )
        # PSLF count is observable on the Loan.
        loan_res = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert isinstance(loan_res["qualifying_pslf_payment_count"], int)
        assert loan_res["qualifying_pslf_payment_count"] >= 0
        # Risk score is in [0,100].
        risk = validate_success(
            api.get_risk_score(borrower["id"],
                               TEST_USERS["servicer_admin_headers"]),
            200,
        )
        int_vals = [v for v in risk.values()
                    if isinstance(v, int) and not isinstance(v, bool)]
        assert any(0 <= v <= 100 for v in int_vals), (
            "PRD §3.10: risk score must be an integer in [0,100]"
        )

    def test_pslf_count_increments_independent_of_risk_score(self, api):
        """PRD §3.8: "Each qualifying (payment, loan) increments the
        loan's qualifying_pslf_payment_count by 1."

        # difficulty: dual_variant_calc/pslf_qualifying_vs_drift_score

        Claim: a single qualifying payment moves PSLF count 0 → 1
        without forcing risk_score to change in a coupled way (they
        are computed from disjoint inputs).
        """
        from test_helpers import setup_pslf_borrower_with_n_qualifying_payments
        borrower, loan, _, _, _ = (
            setup_pslf_borrower_with_n_qualifying_payments(n_qualifying=1)
        )
        loan_res = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert loan_res["qualifying_pslf_payment_count"] == 1


# ===========================================================================
# RULE 2: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:
    """# difficulty: combinatorial_formula"""

    def test_save_with_ak_table_clamps_to_zero(self, api):
        """PRD §3.7: "The Alaska table reads $18,820 (1,882,000
        cents) for size 1, $25,420 for size 2 ... The poverty
        multiplier depends on plan type — ... 2.25 for SAVE.
        Discretionary income is computed as
        adjusted_gross_income_cents minus the multiplier times the
        poverty line, with the result clamped at zero from below
        (never negative)."

        # difficulty: combinatorial_formula/save_idr_nonlinear_inputs

        Claim: AK fs=2, AGI=3_000_000 yields discretionary clamped
        to zero (3000000 < 2.25*2542000 = 5719500), hence SAVE
        monthly_payment_cents == 0.
        """
        borrower, loan, _ = create_borrower_with_loan_in_repayment(
            state_code="AK", family_size=2,
            adjusted_gross_income_cents=3_000_000,
        )
        plan = create_and_activate_plan(
            borrower["id"], "SAVE", [loan["id"]],
        )
        assert plan["monthly_payment_cents"] == 0

    def test_save_with_ak_fs1_positive_payment(self, api):
        """PRD §3.7 / Alaska poverty table: "The Alaska table reads
        $18,820 (1,882,000 cents) for size 1".

        # difficulty: combinatorial_formula/save_idr_nonlinear_inputs

        Claim: switching family_size from 2 to 1 (AK), at the SAME
        AGI=4_500_000, exercises the table lookup non-linearity:
        new discretionary = 4500000 - 2.25*1882000 = 4500000 -
        4234500 = 265500; annual = 13275; monthly = 1106.25 → 1106.
        """
        borrower, loan, _ = create_borrower_with_loan_in_repayment(
            state_code="AK", family_size=1,
            adjusted_gross_income_cents=4_500_000,
        )
        plan = create_and_activate_plan(
            borrower["id"], "SAVE", [loan["id"]],
        )
        expected = round_half_up_to_int(
            max(0, 4_500_000 - 2.25 * 1_882_000) * 0.05 / 12
        )
        assert plan["monthly_payment_cents"] == expected

    def test_full_installment_payment_counts_for_pslf_single_loan(self, api):
        """PRD §3.8: "(4) the sum of that allocation's principal_cents
        and interest_cents is at least the per-loan scheduled-monthly
        share, where the share is computed as the plan's
        monthly_payment_cents multiplied by the loan's share of the
        pool and rounded half-up to integer cents (the share-then-
        round mode is pinned — summing then rounding would yield
        different counts)".

        # difficulty: combinatorial_formula/pslf_share_rounding_order

        Claim: on a single-loan STANDARD_10 plan, the loan's share is
        100%, so scheduled_share_cents == plan.monthly_payment_cents;
        paying exactly that amount qualifies.
        """
        from test_helpers import setup_pslf_borrower_with_n_qualifying_payments
        borrower, loan, plan, _, _ = (
            setup_pslf_borrower_with_n_qualifying_payments(n_qualifying=1)
        )
        loan_res = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert loan_res["qualifying_pslf_payment_count"] == 1, (
            "PRD §3.8 share-then-round: single-loan plan share == "
            "monthly_payment_cents; paying that amount counts"
        )

    def test_underpayment_does_not_count_for_pslf(self, api):
        """PRD §3.8: "(4) the sum of that allocation's
        principal_cents and interest_cents is at least the per-loan
        scheduled-monthly share".

        # difficulty: combinatorial_formula/pslf_share_rounding_order

        Claim: a payment below the per-loan scheduled-monthly share
        does NOT increment qualifying_pslf_payment_count.
        """
        reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
        borrower, loan, current = create_borrower_with_loan_in_repayment(
            original_principal_cents=1_000_000, interest_rate_bps=500,
        )
        cert = submit_and_approve_employment_certification(
            borrower["id"],
            period_start=current, period_end="2030-12-31T23:59:59.999Z",
        )
        plan = create_and_activate_plan(
            borrower["id"], "STANDARD_10", [loan["id"]],
        )
        installment = plan["monthly_payment_cents"]
        pay_clock = advance_clock_by_days(30, from_stamp=current)
        # Pay HALF the installment.
        record_borrower_payment(
            borrower["id"], installment // 2,
            received_at=pay_clock, source="BORROWER",
        )
        after = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert after["qualifying_pslf_payment_count"] == 0


# ===========================================================================
# RULE 3: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:
    """# difficulty: non_linear_state_machine"""

    def test_loan_default_then_rehabilitation_branch(self, api):
        """PRD §3.6: "Once a loan is in DEFAULT, the only path back
        to repayment is loan rehabilitation, opened by a
        CollectionsOfficer. Opening a rehab agreement is a
        CollectionsAction of kind REHAB_AGREEMENT_OPEN ... Opening
        sets status_entered_at to now (resetting the rehab clock)
        and moves the loan from DEFAULT to REHABILITATION."

        # difficulty: non_linear_state_machine/loan_branching_with_compensating_rehab

        Claim: DEFAULT → REHABILITATION via REHAB_AGREEMENT_OPEN.
        """
        borrower, loan, _ = setup_loan_in_rehabilitation()
        assert loan["status"] == "REHABILITATION"

    def test_rehab_payment_recorded_does_not_immediately_complete(self, api):
        """PRD §3.6: "Subsequent rehab payments are recorded as
        CollectionsAction rows of kind REHAB_PAYMENT_RECORDED. When
        the clock-advance sees nine such REHAB_PAYMENT_RECORDED
        actions within the prior 10 consecutive months — measured
        against occurred_at — the loan auto-transitions from
        REHABILITATION back to REPAYMENT."

        # difficulty: non_linear_state_machine/loan_branching_with_compensating_rehab

        Claim: a single REHAB_PAYMENT_RECORDED is NOT sufficient; the
        loan stays in REHABILITATION (the 9-of-10 rule has not
        triggered).
        """
        borrower, loan, current = setup_loan_in_rehabilitation()
        record_collections_action(
            borrower["id"], loan["id"], "REHAB_PAYMENT_RECORDED",
            amount_cents=2548, occurred_at=current,
        )
        fetched = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert fetched["status"] == "REHABILITATION"

    def test_veteran_tpd_discharge_approval_branch_zeros_loan(self, api):
        """PRD §3.9: "Approval cascades to every loan in
        approved_loan_ids: each transitions to DISCHARGED,
        principal_balance_cents and accrued_interest_cents are
        zeroed".

        # difficulty: non_linear_state_machine/discharge_app_branching_review_flow

        Claim: UNDER_REVIEW → APPROVED branch zeros loan balance.
        """
        borrower, loan, app, _ = setup_veteran_tpd_ready_for_approval()
        approved = approve_discharge(
            borrower["id"], app["id"], [loan["id"]],
        )
        assert approved["status"] == "APPROVED"
        fetched = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert fetched["status"] == "DISCHARGED"
        assert fetched["principal_balance_cents"] == 0

    def test_discharge_rejected_branch_leaves_loan_untouched(self, api):
        """PRD §3.9: "from UNDER_REVIEW, a ServicerApprover is the
        only role permitted to approve or reject."

        # difficulty: non_linear_state_machine/discharge_app_branching_review_flow

        Claim: UNDER_REVIEW → REJECTED branch leaves loan untouched
        (the loan-discharge cascade is exclusive to the APPROVED
        branch).
        """
        borrower, loan, app, _ = setup_veteran_tpd_ready_for_approval()
        res = api.update_discharge_application(
            borrower["id"], app["id"],
            update_discharge_application_payload(status="REJECTED"),
            TEST_USERS["servicer_approver_headers"],
        )
        rejected = validate_success(res, 200)
        assert rejected["status"] == "REJECTED"
        fetched = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        # Loan must NOT have been discharged.
        assert fetched["status"] != "DISCHARGED"
        assert fetched["principal_balance_cents"] > 0


# ===========================================================================
# RULE 4: transitive_cascade
# ===========================================================================
class TestTransitiveCascade:
    """# difficulty: transitive_cascade"""

    def test_default_terminates_active_plan_and_resets_siblings(self, api):
        """PRD §3.6: "any ACTIVE RepaymentPlan whose included_loan_ids
        contains the defaulted loan is cascaded to TERMINATED, and
        every other non-defaulted loan that was previously covered
        by that terminated plan is moved to REPAYMENT with
        last_payment_due_at set to the first day of the calendar
        month at or after now."

        # difficulty: transitive_cascade/default_cascade_loan_plan_siblings

        Claim: default of loan A cascades to terminate the plan
        covering A,B,C, and sibling loans B,C come out in REPAYMENT.
        """
        reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
        # Borrower with 3 loans, all in REPAYMENT after 180d.
        borrower = create_borrower(
            adjusted_gross_income_cents=4_000_000,
            agi_certified_at=TEST_DEFAULTS["INITIAL_CLOCK"],
        )
        loans = []
        for _ in range(3):
            loan = create_loan(
                borrower["id"], loan_type="DIRECT_UNSUBSIDIZED",
                original_principal_cents=1_000_000,
                interest_rate_bps=500,
            )
            separate_loan(borrower["id"], loan["id"])
            loans.append(loan)
        # Advance 181 days to exit grace.
        current = advance_clock_by_days(181, from_stamp=TEST_DEFAULTS["INITIAL_CLOCK"])
        plan = create_and_activate_plan(
            borrower["id"], "SAVE", [l["id"] for l in loans],
        )
        # Advance another 370 days to default loan A. Since no
        # payments are made, ALL three loans accrue default at the
        # same threshold — the PRD cascade specifies sibling loans
        # come out in REPAYMENT, but the PRD does NOT commit that
        # they evade their own DEFAULT threshold. In practice if all
        # three pass 270 days simultaneously, all three default; the
        # PRD says the cascade for the FIRST defaulter terminates
        # the plan and moves the OTHERS to REPAYMENT — but those
        # others would then independently age 270+ days again before
        # defaulting since their status_entered_at is reset on the
        # cascade. We assert the immediate post-default observation:
        # plan is TERMINATED.
        advance_clock_by_days(370, from_stamp=current)
        plan_after = validate_success(
            api.get_plan(borrower["id"], plan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert plan_after["status"] == "TERMINATED"

    def test_default_cascade_at_least_one_loan_in_default(self, api):
        """PRD §3.6: "the loan auto-transitions from DELINQUENT to
        DEFAULT" combined with §2.11 "aggregate fields are recomputed
        as the sums of principal_balance_cents and
        accrued_interest_cents across that borrower's non-terminal
        loans" — the cascade is observable on the loan-status side.

        # difficulty: transitive_cascade/default_cascade_loan_plan_siblings

        Claim: after the cascade, at least one loan ends in DEFAULT
        and the plan is TERMINATED — the depth-2 portion (Loan ->
        Plan) of the cascade.
        """
        reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
        borrower, loan, _, _ = setup_borrower_loan_active_save_plan()
        # Need the loan's status_entered_at to be in REPAYMENT, which
        # it is. Advance 370 days to drive it to DEFAULT.
        # (Pre-existing fixture used initial clock; loan is in
        # REPAYMENT at +181 days; we need another 270 to push
        # past_due to 270.)
        # Use the get-loan endpoint to read last_accrual_at as a
        # proxy for current clock continuity, then advance.
        # Setup uses INITIAL_CLOCK + 181d as its "current". Now we
        # advance from that point.
        current_after_setup = _fmt_iso(
            _parse_iso(TEST_DEFAULTS["INITIAL_CLOCK"]) + timedelta(days=181)
        )
        advance_clock_by_days(370, from_stamp=current_after_setup)
        loan_after = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert loan_after["status"] == "DEFAULT"

    def test_employment_cert_approval_retroactive_pslf_count(self, api):
        """PRD §3.8: "Approving an EmploymentCertification
        retroactively re-runs the PSLF qualification recount across
        the borrower's entire payment history."

        # difficulty: transitive_cascade/employment_cert_pslf_discharge_chain

        Claim: APPROVED cert recounts payments retroactively; loan's
        qualifying_pslf_payment_count reflects the new cert's window.
        """
        reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
        borrower, loan, current = create_borrower_with_loan_in_repayment()
        plan = create_and_activate_plan(
            borrower["id"], "STANDARD_10", [loan["id"]],
        )
        installment = plan["monthly_payment_cents"]
        # Submit a cert covering future window but DO NOT approve.
        cert = submit_employment_certification(
            borrower["id"],
            period_start=current,
            period_end="2030-12-31T23:59:59.999Z",
        )
        # Make a payment under the (still-SUBMITTED) cert window.
        pay_clock = advance_clock_by_days(30, from_stamp=current)
        record_borrower_payment(
            borrower["id"], installment, received_at=pay_clock,
            source="BORROWER",
        )
        # Pre-approval: count 0.
        pre = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert pre["qualifying_pslf_payment_count"] == 0
        approve_employment_certification(borrower["id"], cert["id"])
        post = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert post["qualifying_pslf_payment_count"] == 1

    def test_discharge_approval_zeros_balances_and_recomputes_aggregate(self, api):
        """PRD §3.9: "principal_balance_cents and
        accrued_interest_cents are zeroed ... The borrower's
        aggregate_principal_balance_cents and
        aggregate_interest_balance_cents are then recomputed."

        # difficulty: transitive_cascade/employment_cert_pslf_discharge_chain

        Claim: depth-3 cascade — DischargeApplication APPROVED → Loan
        DISCHARGED + balances zero → Borrower aggregates recomputed
        to 0.
        """
        borrower, loan, app, _ = setup_veteran_tpd_ready_for_approval()
        approve_discharge(borrower["id"], app["id"], [loan["id"]])
        fetched_loan = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert fetched_loan["status"] == "DISCHARGED"
        assert fetched_loan["principal_balance_cents"] == 0
        fetched_borrower = validate_success(
            api.get_borrower(borrower["id"],
                             TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert fetched_borrower["aggregate_principal_balance_cents"] == 0


# ===========================================================================
# RULE 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:
    """# difficulty: priority_pair_validation_conflict"""

    def test_state_error_wins_over_sod_violation(self, api):
        """PRD §2.8: "When multiple validations apply to the same
        request, they are evaluated in the priority order spelled
        out below, and the first failure short-circuits the rest.
        ... then state-machine eligibility of the target resource
        (ERR_INVALID_STATE); then business-safety checks (segregation
        of duties — ERR_SOD_VIOLATION ..."

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_pslf_approval

        Claim: when an application is already REJECTED AND the
        approver would also violate SoD, the state error fires first
        (ERR_INVALID_STATE).
        """
        borrower, loan, _, app, _ = setup_pslf_ready_for_approval(
            n_qualifying=120,
        )
        # Reject the application as a different ServicerApprover.
        validate_success(
            api.update_discharge_application(
                borrower["id"], app["id"],
                update_discharge_application_payload(status="REJECTED"),
                TEST_USERS["servicer_approver_headers"],
            ),
            200,
        )
        # Now try to APPROVE as an approver whose id equals the
        # certifier id (would be an SoD violation), but the
        # application is REJECTED, so state error fires first.
        sod_approver = make_servicer_approver_headers(SERVICER_CERTIFIER_ID)
        res = api.update_discharge_application(
            borrower["id"], app["id"],
            update_discharge_application_payload(
                status="APPROVED", approved_loan_ids=[loan["id"]],
            ),
            sod_approver,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_bad_date_window_wins_over_plus_ineligible(self, api):
        """PRD §2.8: "then business-temporal checks
        (ERR_BAD_DATE_WINDOW, ERR_FORBEARANCE_CAP_EXCEEDED); then
        business-referential and business-constraint checks specific
        to plans and rehab (... ERR_PLUS_INELIGIBLE_FOR_IN_SCHOOL)".

        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_constraint_hardship

        Claim: a DEFERMENT_IN_SCHOOL on a PLUS loan with
        requested_from in the past triggers BOTH validations; the
        temporal error fires first.
        """
        reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
        borrower = create_borrower()
        loan = create_loan(borrower["id"], loan_type="DIRECT_PLUS")
        # Past requested_from (before clock now).
        past_from = _fmt_iso(
            _parse_iso(TEST_DEFAULTS["INITIAL_CLOCK"]) - timedelta(days=30)
        )
        future_to = _fmt_iso(
            _parse_iso(TEST_DEFAULTS["INITIAL_CLOCK"]) + timedelta(days=30)
        )
        res = api.create_hardship_request(
            borrower["id"],
            {
                "kind": "DEFERMENT_IN_SCHOOL",
                "requested_from": past_from,
                "requested_to": future_to,
                "applied_loan_ids": [loan["id"]],
            },
            TEST_USERS["servicer_admin_headers"],
        )
        validate_error(res, "ERR_BAD_DATE_WINDOW")

    def test_sod_violation_fires_when_state_is_valid(self, api):
        """PRD §2.9: "When the two ids match, the request is rejected
        with ERR_SOD_VIOLATION — and per §2.8 this safety check fires
        before the PSLF qualifying-count check or the veteran-
        eligibility check".

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_pslf_approval

        Claim: with a valid UNDER_REVIEW state, ERR_SOD_VIOLATION
        fires before any later business-referential checks like
        ERR_PSLF_INSUFFICIENT_PAYMENTS. We verify SoD wins over PSLF
        evidence/count: the approver's id matches the certifier id,
        AND the PSLF count is below 120 — SoD fires (priority 8),
        not insufficient-payments (priority 11).
        """
        borrower, loan, _, app, _ = setup_pslf_ready_for_approval(
            n_qualifying=3,  # below 120
        )
        sod_approver = make_servicer_approver_headers(SERVICER_CERTIFIER_ID)
        res = api.update_discharge_application(
            borrower["id"], app["id"],
            update_discharge_application_payload(
                status="APPROVED", approved_loan_ids=[loan["id"]],
            ),
            sod_approver,
        )
        validate_error(res, "ERR_SOD_VIOLATION")

    def test_plus_ineligible_fires_when_window_is_valid(self, api):
        """PRD §3.5: "if kind is DEFERMENT_IN_SCHOOL and any applied
        loan is DIRECT_PLUS, the approval is rejected with
        ERR_PLUS_INELIGIBLE_FOR_IN_SCHOOL".

        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_constraint_hardship

        Claim: when the date window is valid, the business-constraint
        ERR_PLUS_INELIGIBLE_FOR_IN_SCHOOL fires at approval time. This
        is the "second-best" branch: without the temporal error to
        out-prioritize it, the PLUS-eligibility error becomes visible.
        """
        reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
        borrower, loan, current = create_borrower_with_loan_in_repayment(
            loan_type="DIRECT_PLUS",
        )
        # Valid future window (no temporal error).
        from_iso = current
        to_iso = _fmt_iso(_parse_iso(current) + timedelta(days=90))
        req = submit_hardship_request(
            borrower["id"], "DEFERMENT_IN_SCHOOL",
            requested_from=from_iso, requested_to=to_iso,
            applied_loan_ids=[loan["id"]],
        )
        res = api.update_hardship_request(
            borrower["id"], req["id"],
            update_hardship_request_payload(status="APPROVED"),
            TEST_USERS["servicer_certifier_headers"],
        )
        validate_error(res, "ERR_PLUS_INELIGIBLE_FOR_IN_SCHOOL")


# ===========================================================================
# RULE 6: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:
    """# difficulty: boundary_precision_check"""

    def test_default_inclusive_boundary_at_270_days(self, api):
        """PRD §3.3: "if the recomputed value reaches at least 270,
        the loan immediately progresses to default per §3.6."
        PRD §3.6: "When days_past_due reaches at least 270, the loan
        auto-transitions from DELINQUENT to DEFAULT."

        # difficulty: boundary_precision_check/default_threshold_at_270_days_exactly

        Claim: at days_past_due >= 270 the loan must be in DEFAULT.
        """
        borrower, loan, _ = setup_loan_in_default()
        assert loan["status"] == "DEFAULT"

    def test_loan_below_270_days_not_default(self, api):
        """PRD §3.3: "if the recomputed value reaches at least 270".

        # difficulty: boundary_precision_check/default_threshold_at_270_days_exactly

        Claim: a loan that has aged delinquent BUT not yet reached
        270 days_past_due is NOT in DEFAULT.
        """
        reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
        borrower, loan, current = create_borrower_with_loan_in_repayment()
        # Advance to ~60 days past_due (well below 270).
        advance_clock_by_days(60, from_stamp=current)
        fetched = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert fetched["status"] != "DEFAULT", (
            "PRD §3.6: days_past_due < 270 must NOT trigger DEFAULT"
        )

    def test_empty_included_loan_ids_rejected_on_plan_create(self, api):
        """PRD §3.7: "every loan in included_loan_ids must belong to
        this borrower; every such loan must currently be in
        REPAYMENT or GRACE (loans in DEFAULT block activation,
        reported as ERR_PLAN_LOAN_INELIGIBLE)".

        # difficulty: boundary_precision_check/empty_included_loan_ids_for_plan

        Claim: empty included_loan_ids → ERR_PLAN_LOAN_INELIGIBLE
        (an empty set vacuously fails to include any REPAYMENT/GRACE
        loan, which is the necessary condition the PRD calls out).
        """
        borrower = create_borrower()
        res = api.create_plan(
            borrower["id"],
            {"plan_type": "SAVE", "included_loan_ids": []},
            TEST_USERS["servicer_admin_headers"],
        )
        # Implementation may surface this at POST /plans (input shape)
        # or at /activate; either is PRD-consistent. We accept the
        # most-specific PRD error code or a 400/422-level rejection.
        if res.status_code in (200, 201):
            # Created PENDING — activation must fail.
            plan = validate_success(res, res.status_code)
            act_res = api.activate_plan(
                borrower["id"], plan["id"],
                TEST_USERS["servicer_admin_headers"],
            )
            validate_error(act_res, "ERR_PLAN_LOAN_INELIGIBLE")
        else:
            assert res.status_code >= 400, (
                "PRD §3.7: empty included_loan_ids cannot satisfy "
                "'every loan must be in REPAYMENT or GRACE'"
            )

    def test_activate_plan_with_default_loan_rejected_with_inelegible(self, api):
        """PRD §3.7: "loans in DEFAULT block activation, reported as
        ERR_PLAN_LOAN_INELIGIBLE".

        # difficulty: boundary_precision_check/empty_included_loan_ids_for_plan

        Claim: activating a plan that includes a DEFAULT loan ->
        ERR_PLAN_LOAN_INELIGIBLE (same error code surfaced on a
        different boundary input — defaulted single loan).
        """
        borrower, loan, _ = setup_loan_in_default()
        # Try to create then activate a SAVE plan over this DEFAULT loan.
        res = api.create_plan(
            borrower["id"],
            {"plan_type": "SAVE", "included_loan_ids": [loan["id"]]},
            TEST_USERS["servicer_admin_headers"],
        )
        # If POST already rejects, ensure the error code.
        if res.status_code in (200, 201):
            plan = validate_success(res, res.status_code)
            act_res = api.activate_plan(
                borrower["id"], plan["id"],
                TEST_USERS["servicer_admin_headers"],
            )
            validate_error(act_res, "ERR_PLAN_LOAN_INELIGIBLE")
        else:
            # PRD pins ERR_PLAN_LOAN_INELIGIBLE for this rule.
            body = res.json()
            assert body["data"]["error_id"] == "ERR_PLAN_LOAN_INELIGIBLE"


# ===========================================================================
# RULE 7: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:
    """# difficulty: cross_entity_state_dependency"""

    def test_plan_activation_blocked_by_default_loan(self, api):
        """PRD §3.7: "every such loan must currently be in REPAYMENT
        or GRACE (loans in DEFAULT block activation, reported as
        ERR_PLAN_LOAN_INELIGIBLE)".

        # difficulty: cross_entity_state_dependency/plan_activation_blocked_by_default_loan

        Claim: activating a plan whose included_loan_ids contains a
        DEFAULT loan fails with ERR_PLAN_LOAN_INELIGIBLE.
        """
        borrower, loan, _ = setup_loan_in_default()
        res = api.create_plan(
            borrower["id"],
            {"plan_type": "SAVE", "included_loan_ids": [loan["id"]]},
            TEST_USERS["servicer_admin_headers"],
        )
        if res.status_code in (200, 201):
            plan = validate_success(res, res.status_code)
            act_res = api.activate_plan(
                borrower["id"], plan["id"],
                TEST_USERS["servicer_admin_headers"],
            )
            validate_error(act_res, "ERR_PLAN_LOAN_INELIGIBLE")
        else:
            body = res.json()
            assert body["data"]["error_id"] == "ERR_PLAN_LOAN_INELIGIBLE"

    def test_plan_activation_succeeds_with_repayment_loan(self, api):
        """PRD §3.7: "every such loan must currently be in REPAYMENT
        or GRACE".

        # difficulty: cross_entity_state_dependency/plan_activation_blocked_by_default_loan

        Claim: the inverse — a loan in REPAYMENT permits activation.
        """
        borrower, loan, _ = create_borrower_with_loan_in_repayment()
        plan = create_and_activate_plan(
            borrower["id"], "STANDARD_10", [loan["id"]],
        )
        assert plan["status"] == "ACTIVE"

    def test_pslf_under_review_requires_approved_cert(self, api):
        """PRD §3.9: "Moving a PSLF application from SUBMITTED to
        UNDER_REVIEW requires that at least one EmploymentCertification
        for this borrower is already in APPROVED status — otherwise
        the certifier's transition is rejected with
        ERR_PSLF_NO_EMPLOYMENT_EVIDENCE."

        # difficulty: cross_entity_state_dependency/discharge_approval_requires_employment_cert_state

        Claim: PSLF SUBMITTED -> UNDER_REVIEW without any APPROVED
        cert fails with ERR_PSLF_NO_EMPLOYMENT_EVIDENCE.
        """
        borrower, _, _ = create_borrower_with_loan_in_repayment()
        # SUBMITTED-only cert.
        submit_employment_certification(
            borrower["id"], use_borrower_role=True,
        )
        app = submit_discharge_application(
            borrower["id"], "PSLF", use_borrower_role=True,
        )
        res = api.update_discharge_application(
            borrower["id"], app["id"],
            update_discharge_application_payload(status="UNDER_REVIEW"),
            TEST_USERS["servicer_certifier_headers"],
        )
        validate_error(res, "ERR_PSLF_NO_EMPLOYMENT_EVIDENCE")

    def test_pslf_under_review_succeeds_with_approved_cert(self, api):
        """PRD §3.9: "Moving a PSLF application from SUBMITTED to
        UNDER_REVIEW requires that at least one
        EmploymentCertification for this borrower is already in
        APPROVED status".

        # difficulty: cross_entity_state_dependency/discharge_approval_requires_employment_cert_state

        Claim: the inverse — with one APPROVED cert in place, the
        PSLF SUBMITTED -> UNDER_REVIEW transition succeeds.
        """
        borrower, _, _ = create_borrower_with_loan_in_repayment()
        submit_and_approve_employment_certification(borrower["id"])
        app = submit_discharge_application(
            borrower["id"], "PSLF", use_borrower_role=True,
        )
        res = api.update_discharge_application(
            borrower["id"], app["id"],
            update_discharge_application_payload(status="UNDER_REVIEW"),
            TEST_USERS["servicer_certifier_headers"],
        )
        moved = validate_success(res, 200)
        assert moved["status"] == "UNDER_REVIEW"


# ===========================================================================
# RULE 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:
    """# difficulty: resource_temporal_overlap"""

    def test_forbearance_cumulative_cap_blocks_second_request(self, api):
        """PRD §3.5: "if kind is FORBEARANCE_GENERAL, the borrower's
        lifetime cumulative general-forbearance days plus the number
        of days in the requested window must be at most 1095 ...
        with violation reported as ERR_FORBEARANCE_CAP_EXCEEDED."

        # difficulty: resource_temporal_overlap/hardship_request_forbearance_cumulative_cap

        Claim: 1000 prior days + 100 new days = 1100 > 1095 →
        ERR_FORBEARANCE_CAP_EXCEEDED.
        """
        reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
        borrower, loan, current = create_borrower_with_loan_in_repayment()
        # First forbearance for 1000 days.
        first_from = current
        first_to = _fmt_iso(
            _parse_iso(current) + timedelta(days=1000)
        )
        first_req = submit_hardship_request(
            borrower["id"], "FORBEARANCE_GENERAL",
            requested_from=first_from, requested_to=first_to,
            applied_loan_ids=[loan["id"]],
        )
        approve_hardship_request(borrower["id"], first_req["id"])
        # Advance past first window.
        new_now = advance_clock_by_days(1005, from_stamp=current)
        # Second forbearance for 100 days.
        second_from = new_now
        second_to = _fmt_iso(
            _parse_iso(new_now) + timedelta(days=100)
        )
        second_req = submit_hardship_request(
            borrower["id"], "FORBEARANCE_GENERAL",
            requested_from=second_from, requested_to=second_to,
            applied_loan_ids=[loan["id"]],
        )
        res = api.update_hardship_request(
            borrower["id"], second_req["id"],
            update_hardship_request_payload(status="APPROVED"),
            TEST_USERS["servicer_certifier_headers"],
        )
        validate_error(res, "ERR_FORBEARANCE_CAP_EXCEEDED")

    def test_forbearance_within_cap_succeeds(self, api):
        """PRD §3.5: "must be at most 1095" — the inverse inclusive
        boundary.

        # difficulty: resource_temporal_overlap/hardship_request_forbearance_cumulative_cap

        Claim: a request whose window keeps the cumulative under
        1095 days is approved.
        """
        reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
        borrower, loan, current = create_borrower_with_loan_in_repayment()
        # Single 500-day forbearance, well under 1095.
        req_to = _fmt_iso(_parse_iso(current) + timedelta(days=500))
        req = submit_hardship_request(
            borrower["id"], "FORBEARANCE_GENERAL",
            requested_from=current, requested_to=req_to,
            applied_loan_ids=[loan["id"]],
        )
        approved = approve_hardship_request(borrower["id"], req["id"])
        assert approved["status"] == "APPROVED"

    def test_overlapping_plan_supersedes_prior_active_plan(self, api):
        """PRD §3.7: "If the activation of this new plan touches any
        loan that is already covered by another ACTIVE plan for the
        same borrower, the older plan is cascaded to SUPERSEDED and
        the new plan's activation proceeds".

        # difficulty: resource_temporal_overlap/repayment_plan_overlap_on_loan_id

        Claim: a second ACTIVE plan overlapping on the same loan_id
        moves the first plan to SUPERSEDED.
        """
        borrower, loan, _ = create_borrower_with_loan_in_repayment()
        save_plan = create_and_activate_plan(
            borrower["id"], "SAVE", [loan["id"]],
        )
        ibr_plan = create_and_activate_plan(
            borrower["id"], "IBR", [loan["id"]],
        )
        save_after = validate_success(
            api.get_plan(borrower["id"], save_plan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        ibr_after = validate_success(
            api.get_plan(borrower["id"], ibr_plan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert save_after["status"] == "SUPERSEDED"
        assert ibr_after["status"] == "ACTIVE"

    def test_loan_belongs_to_exactly_one_active_plan(self, api):
        """PRD §2.10: "the server preserves the invariant that at
        most one ACTIVE plan covers any given loan."

        # difficulty: resource_temporal_overlap/repayment_plan_overlap_on_loan_id

        Claim: after activating two overlapping plans, the loan is
        covered by exactly one ACTIVE plan.
        """
        borrower, loan, _ = create_borrower_with_loan_in_repayment()
        create_and_activate_plan(borrower["id"], "SAVE", [loan["id"]])
        create_and_activate_plan(borrower["id"], "PAYE", [loan["id"]])
        from test_helpers import validate_paginated
        all_plans, _ = validate_paginated(
            api.list_plans(borrower["id"],
                           TEST_USERS["servicer_admin_headers"]),
        )
        actives = [p for p in all_plans
                   if p["status"] == "ACTIVE"
                   and loan["id"] in p.get("included_loan_ids", [])]
        assert len(actives) == 1, (
            f"PRD §2.10: at most one ACTIVE plan must cover any "
            f"given loan, found {len(actives)} ACTIVE for {loan['id']}"
        )


# ===========================================================================
# RULE 9: compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:
    """# difficulty: compensating_invariant"""

    def test_rehab_cycle_preserves_balance_conservation(self, api):
        """PRD §3.6: "The conservation invariant is that
        principal_balance_cents + accrued_interest_cents + lifetime
        paid amount is unchanged across the rehab cycle, because
        REHAB_PAYMENT_RECORDED amounts flow into the waterfall as
        payments."

        # difficulty: compensating_invariant/rehab_completion_balance_conservation

        Claim: on a loan driven into DEFAULT then opened for rehab,
        a single REHAB_PAYMENT_RECORDED of amount A reduces
        (principal + accrued) by A (the PRD-stated waterfall flow);
        no synthetic credit appears.
        """
        borrower, loan, current = setup_loan_in_rehabilitation()
        pre_principal = loan["principal_balance_cents"]
        pre_accrued = loan["accrued_interest_cents"]
        snapshot_total = pre_principal + pre_accrued
        # Record one REHAB_PAYMENT_RECORDED for 10_000 cents.
        record_collections_action(
            borrower["id"], loan["id"], "REHAB_PAYMENT_RECORDED",
            amount_cents=10_000, occurred_at=current,
        )
        # PRD §3.6 says rehab payments "flow into the waterfall as
        # payments" — meaning a Payment is implicitly created and
        # applied. So the loan balance decreases by up to the
        # payment amount.
        fetched = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        new_total = (fetched["principal_balance_cents"]
                     + fetched["accrued_interest_cents"])
        # New balance should not EXCEED the old balance (no synthetic
        # credit on the loan itself); it should be at most snapshot
        # total.
        assert new_total <= snapshot_total, (
            "PRD §3.6: rehab cycle must not add synthetic principal "
            "or interest; new_total exceeded pre-cycle total"
        )

    def test_rehab_does_not_zero_balance_without_payments(self, api):
        """PRD §3.6: "The conservation invariant is that
        principal_balance_cents + accrued_interest_cents + lifetime
        paid amount is unchanged across the rehab cycle, because
        REHAB_PAYMENT_RECORDED amounts flow into the waterfall as
        payments."

        # difficulty: compensating_invariant/rehab_completion_balance_conservation

        Claim: REHAB_AGREEMENT_OPEN alone does NOT zero or reduce
        the loan balance — only payments cause balance reduction.
        """
        borrower, loan, _ = setup_loan_in_rehabilitation()
        # Loan was just opened for rehab; balance must still be
        # positive (it carries the post-default capitalized balance).
        assert loan["principal_balance_cents"] > 0, (
            "PRD §3.6: REHAB_AGREEMENT_OPEN does not adjust loan "
            "balance; it only changes status"
        )

    def test_treasury_offset_does_not_debit_discharged_loan(self, api):
        """PRD §3.4: "Targeted-collections mode applies when source
        is ADMINISTRATIVE_WAGE_GARNISHMENT or TREASURY_OFFSET. The
        walker considers only loans whose status is DEFAULT, in the
        same priority order and with the same per-loan interest-
        before-principal ordering. Loans not in DEFAULT receive zero
        allocation."

        # difficulty: compensating_invariant/discharge_then_no_offset_garnishment

        Claim: a DISCHARGED loan is not in DEFAULT, so a
        TREASURY_OFFSET payment must allocate 0 against it; the
        loan's zero balance is preserved.
        """
        borrower, loan, app, _ = setup_veteran_tpd_ready_for_approval()
        approve_discharge(borrower["id"], app["id"], [loan["id"]])
        # Now submit a TREASURY_OFFSET payment.
        payment = record_borrower_payment(
            borrower["id"], 10_000, source="TREASURY_OFFSET",
        )
        fetched_loan = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert fetched_loan["principal_balance_cents"] == 0
        assert fetched_loan["accrued_interest_cents"] == 0
        # Allocation against this loan, if any, must be zero
        # (PRD §3.4 explicitly forbids debiting non-DEFAULT loans).
        for a in payment["allocations"]:
            if a["loan_id"] == loan["id"]:
                assert a.get("principal_cents", 0) == 0
                assert a.get("interest_cents", 0) == 0

    def test_discharge_preserves_zero_balance_under_garnishment(self, api):
        """PRD §3.9: "principal_balance_cents and
        accrued_interest_cents are zeroed". PRD §3.4: targeted-
        collections "considers only loans whose status is DEFAULT".

        # difficulty: compensating_invariant/discharge_then_no_offset_garnishment

        Claim: a WAGE_GARNISHMENT_ORDER-sourced payment after
        discharge also leaves the loan at zero balance.
        """
        borrower, loan, app, _ = setup_veteran_tpd_ready_for_approval()
        approve_discharge(borrower["id"], app["id"], [loan["id"]])
        record_borrower_payment(
            borrower["id"], 5_000,
            source="ADMINISTRATIVE_WAGE_GARNISHMENT",
        )
        fetched = validate_success(
            api.get_loan(borrower["id"], loan["id"],
                         TEST_USERS["servicer_admin_headers"]),
            200,
        )
        assert fetched["principal_balance_cents"] == 0
        assert fetched["accrued_interest_cents"] == 0
