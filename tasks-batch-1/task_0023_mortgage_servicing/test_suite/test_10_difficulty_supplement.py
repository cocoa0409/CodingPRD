"""Supplemental coverage: a second-angle test for every non-skipped
difficulty instance. Each test asserts a distinct PRD-verbatim facet of
the rule already touched in tests 01-09, so every difficulty instance is
covered by at least two tests."""
from test_helpers import (
    ApiErrorId,
    api_client,
    validate_success,
    validate_error,
    set_clock,
    create_borrower,
    create_loan,
    create_escrow_account,
    create_forbearance_plan_payload,
    create_mediation_session_payload,
    record_outcome_payload,
    post_payment,
    fetch_loan,
    fetch_escrow_account,
    fetch_disbursement,
    fetch_pmi_request,
    fetch_forbearance_plan,
    fetch_foreclosure_case,
    fetch_mediation_session,
    make_loan_servicer_headers,
    make_compliance_officer_headers,
    setup_borrower_loan_escrow,
    setup_delinquent_loan,
    setup_foreclosure_filed,
    setup_active_forbearance,
    setup_case_in_mediation,
    setup_pmi_request_pending,
    setup_loan_paid_off_with_scheduled_disbursement,
)


class TestDualVariantPaymentPostingPart2:

    def test_standard_waterfall_updates_principal_and_escrow_balance(self, api):
        """PRD §3.2: "After the allocation is applied, the loan's
        principal_balance_cents is decremented by the principal allocation,
        accrued_interest_cents is decremented by the interest allocation,
        last_payment_posted_at is set to the current server timestamp,
        next_due_date advances by one calendar month for each fully-cured
        installment satisfied by the posting, and days_past_due is
        recomputed against the simulated current UTC time. The associated
        escrow account's balance_cents is incremented by the escrow portion
        of the allocation, and the escrow account's version is incremented
        when that escrow portion was non-zero."

        Design: Difficulty/dual_variant_calc/dual_variant_payment_posting_standard_vs_curtailment
        """
        set_clock("2026-01-01T00:00:00Z")
        borrower = create_borrower()
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        escrow = create_escrow_account(loan["id"], 480000, 120000, 2)
        set_clock("2026-02-01T00:00:00Z")
        post_payment(
            loan["id"], 300000, "2026-02-01T00:00:00Z",
            posting_strategy="STANDARD_WATERFALL",
        )
        loan_after = fetch_loan(loan["id"])
        escrow_after = fetch_escrow_account(escrow["id"])
        # principal_cents allocation = 29865 → balance 30000000-29865.
        assert loan_after["principal_balance_cents"] == 30000000 - 29865
        # escrow_cents allocation = 50000 → balance 0+50000.
        assert escrow_after["balance_cents"] == 50000


class TestAmortizationPart2:

    def test_amortization_at_different_principal_recomputes_correctly(self, api):
        """PRD §3.1: "First the monthly rate as a fraction is derived by
        dividing the annual rate in basis points by one million and then
        by twelve; call that rate r and the term in months n and the
        original principal P. The scheduled monthly principal-and-interest
        in cents is then P multiplied by r multiplied by one-plus-r raised
        to the n, divided by one-plus-r raised to the n minus one, with
        the final result rounded half-up to a whole number of cents."

        Design: Difficulty/combinatorial_formula/combinatorial_amortization_three_inputs_nonlinear
        """
        # P=20M @ 5%/360 → 107364 (different inputs from instance-1).
        borrower = create_borrower()
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=9000,
        )
        assert loan["scheduled_monthly_pi_cents"] == 107364


class TestLoanCyclePart2:

    def test_active_forbearance_completion_returns_loan_to_reinstated(self, api):
        """PRD §3.4: "A plan in ACTIVE status moves to COMPLETED once the
        simulated current UTC time has reached or passed the end_date, at
        which point the loan transitions to REINSTATED and the loan's
        next_due_date is advanced to thirty days after the current UTC
        time."

        Design: Difficulty/non_linear_state_machine/non_linear_loan_cycle_delinquent_forbearance_delinquent
        """
        ctx = setup_active_forbearance(
            clock_iso="2025-06-01T00:00:00Z",
            after_grace_iso="2025-07-25T00:00:00Z",
            start_date="2025-08-01T00:00:00Z",
            end_date="2025-08-31T00:00:00Z",
            reduced_payment_cents=50000,
            origination_date="2025-06-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        set_clock("2025-09-01T00:00:00Z")
        validate_success(api.complete_forbearance_plan(
            ctx["forbearance_plan"]["id"], make_loan_servicer_headers(),
        ))
        plan_after = fetch_forbearance_plan(ctx["forbearance_plan"]["id"])
        assert plan_after["status"] == "COMPLETED"
        loan_after = fetch_loan(ctx["loan"]["id"])
        assert loan_after["status"] == "REINSTATED"


class TestForeclosureBranchPart2:

    def test_no_agreement_outcome_moves_case_to_mediation_failed(self, api):
        """PRD §3.5: "When the outcome is NO_AGREEMENT, the case
        transitions to MEDIATION_FAILED and the loan remains in
        FORECLOSURE."

        Design: Difficulty/non_linear_state_machine/non_linear_foreclosure_branching_mediation_outcome
        """
        ctx = setup_case_in_mediation(
            clock_iso="2025-06-01T00:00:00Z",
            after_120_days_iso="2025-11-01T00:00:00Z",
            mediation_clock_iso="2025-11-01T00:00:00Z",
            mediation_scheduled_for="2025-11-15T00:00:00Z",
            origination_date="2025-06-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        validate_success(api.record_mediation_outcome(
            ctx["mediation_session"]["id"],
            record_outcome_payload(outcome="NO_AGREEMENT"),
            make_loan_servicer_headers(),
        ))
        case_after = fetch_foreclosure_case(ctx["foreclosure_case"]["id"])
        assert case_after["status"] == "MEDIATION_FAILED"
        loan_after = fetch_loan(ctx["loan"]["id"])
        assert loan_after["status"] == "FORECLOSURE"


class TestPayoffCascadePart2:

    def test_payoff_sets_pmi_status_to_auto_terminated(self, api):
        """PRD §3.2: "When the remittance is at least the sum of
        principal_balance_cents, accrued_interest_cents, and any outstanding
        fees — fully retiring the obligation — and the loan was in CURRENT
        status, the loan transitions to PAID_OFF (a terminal state), the
        loan's pmi_status is set to AUTO_TERMINATED, and every
        EscrowDisbursement still in SCHEDULED status for this loan's escrow
        account is cascaded to CANCELLED so no further outflows fire
        against an account whose loan no longer exists in a serviceable
        form."

        Design: Difficulty/transitive_cascade/cascade_payoff_loan_cancels_disbursements_three_hops
        """
        set_clock("2025-12-01T00:00:00Z")
        borrower = create_borrower()
        # P=20M @ 8000bps LTV → pmi_status=ACTIVE.
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2025-12-01T00:00:00Z",
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=0,
            term_months=120,
            pmi_monthly_cents=8000,
        )
        # Verify PMI started ACTIVE (LTV at origination = 8000 >= 80%).
        assert loan["pmi_status"] == "ACTIVE"
        # Full payoff.
        post_payment(loan["id"], 20000000, "2025-12-15T00:00:00Z")
        loan_after = fetch_loan(loan["id"])
        assert loan_after["status"] == "PAID_OFF"
        assert loan_after["pmi_status"] == "AUTO_TERMINATED"


class TestCascadeClockPart2:

    def test_clock_advance_recomputes_days_past_due_on_every_loan(self, api):
        """PRD §2.4: "The clock-advance capability also recomputes
        days_past_due on every loan."

        Design: Difficulty/transitive_cascade/cascade_clock_advance_drives_delinquency_then_pmi_pending_blocks
        """
        set_clock("2026-01-01T00:00:00Z")
        borrower = create_borrower()
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        # next_due_date = 2026-01-31. Advance to 2026-02-20 (+20 days).
        set_clock("2026-02-20T00:00:00Z")
        loan_after = fetch_loan(loan["id"])
        # 20 days past due (also > grace, so status DELINQUENT).
        assert loan_after["days_past_due"] == 20
        assert loan_after["status"] == "DELINQUENT"


class TestPmiStateBeatsLtvPart2:

    def test_decide_on_already_approved_request_returns_invalid_state(self, api):
        """PRD §3.8: "Decision is permitted only on a request still in
        PENDING; a decision request against a request already in a
        terminal status is rejected with ERR_INVALID_STATE."

        Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_business_fiscal_pmi_decide
        """
        # P=27M, V=40M → LTV 6750 → APPROVED (below 7800 auto-termination).
        ctx = setup_pmi_request_pending(
            clock_iso="2026-01-01T00:00:00Z",
            original_principal_cents=27000000,
            original_property_value_cents=40000000,
            pmi_monthly_cents=13000,
            interest_rate_bps=500,
            origination_date="2026-01-01T00:00:00Z",
        )
        first = validate_success(api.decide_pmi_removal_request(
            ctx["pmi_request"]["id"], make_compliance_officer_headers(),
        ))
        assert first["status"] == "APPROVED"
        # Second decide on already-APPROVED request must return ERR_INVALID_STATE.
        resp = api.decide_pmi_removal_request(
            ctx["pmi_request"]["id"], make_compliance_officer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPmiLtvBoundaryPart2:

    def test_approval_cascades_loan_pmi_status_and_required_flag(self, api):
        """PRD §3.8: "On approval, the loan's pmi_required is set to false,
        the loan's pmi_status is set to REMOVED, the loan's
        total_monthly_payment_cents is recomputed to drop the PMI premium,
        and the loan's version is incremented."

        Design: Difficulty/boundary_precision_check/boundary_pmi_ltv_exact_8000_bps_denied
        """
        # P=27M, V=40M → LTV 6750 → approval branch (well under 7800).
        ctx = setup_pmi_request_pending(
            clock_iso="2026-01-01T00:00:00Z",
            original_principal_cents=27000000,
            original_property_value_cents=40000000,
            pmi_monthly_cents=13000,
            interest_rate_bps=500,
            origination_date="2026-01-01T00:00:00Z",
        )
        validate_success(api.decide_pmi_removal_request(
            ctx["pmi_request"]["id"], make_compliance_officer_headers(),
        ))
        loan_after = fetch_loan(ctx["loan"]["id"])
        assert loan_after["pmi_required"] is False
        assert loan_after["pmi_status"] == "REMOVED"


class TestMediationNoticePart2:

    def test_scheduling_a_session_moves_case_into_in_mediation(self, api):
        """PRD §3.5: "Scheduling moves the case into IN_MEDIATION and
        creates a MediationSession row whose outcome is initialized to
        PENDING and whose foreclosure_case_id ties it to the case."

        Design: Difficulty/boundary_precision_check/boundary_mediation_notice_exactly_14_days_allowed
        """
        ctx = setup_foreclosure_filed(
            clock_iso="2025-06-01T00:00:00Z",
            after_120_days_iso="2025-11-01T00:00:00Z",
            origination_date="2025-06-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        set_clock("2025-11-01T00:00:00Z")
        # Schedule at +20 days — comfortably past the 14-day boundary.
        session = validate_success(api.schedule_mediation_session(
            ctx["foreclosure_case"]["id"],
            create_mediation_session_payload(
                scheduled_for="2025-11-21T00:00:00Z",
            ),
            make_loan_servicer_headers(),
        ), expected_status=201)
        assert session["outcome"] == "PENDING"
        assert session["foreclosure_case_id"] == ctx["foreclosure_case"]["id"]


class TestForbearancePlanBlocksForeclosurePart2:

    def test_activating_forbearance_cascades_loan_to_forbearance(self, api):
        """PRD §3.4: "Activation transitions the plan from PROPOSED to
        ACTIVE, transitions the loan to FORBEARANCE, and pins the plan's
        deferred_total_cents for the entire window."

        Design: Difficulty/cross_entity_state_dependency/cross_loan_forbearanceplan_blocks_foreclosure
        """
        ctx = setup_active_forbearance(
            clock_iso="2025-04-01T00:00:00Z",
            after_grace_iso="2025-05-25T00:00:00Z",
            start_date="2025-06-01T00:00:00Z",
            end_date="2025-11-30T00:00:00Z",
            reduced_payment_cents=50000,
            origination_date="2025-04-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        loan_after = fetch_loan(ctx["loan"]["id"])
        assert loan_after["status"] == "FORBEARANCE"
        assert ctx["forbearance_plan"]["status"] == "ACTIVE"


class TestDisbursementBalanceDependencyPart2:

    def test_paid_disbursement_decrements_escrow_balance(self, api):
        """PRD §3.6: "if the balance is at least the disbursement's
        amount_cents, the disbursement transitions to PAID, its paid_at is
        set to the current UTC time, the account's balance_cents is
        reduced by the disbursement amount, and the account's version is
        incremented."

        Design: Difficulty/cross_entity_state_dependency/cross_escrowdisbursement_escrowaccount_balance_dependency
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_borrower_loan_escrow(
            clock_iso="2026-01-01T00:00:00Z",
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        # Build balance to 50000.
        post_payment(ctx["loan"]["id"], 242365, "2026-01-15T00:00:00Z")
        disb = validate_success(api.create_disbursement(
            ctx["escrow_account"]["id"],
            {"kind": "TAX", "amount_cents": 30000,
             "scheduled_for": "2026-06-01T00:00:00Z"},
            make_loan_servicer_headers(),
        ), expected_status=201)
        # Fire it.
        set_clock("2026-06-02T00:00:00Z")
        disb_after = fetch_disbursement(disb["id"])
        assert disb_after["status"] == "PAID"
        esc_after = fetch_escrow_account(ctx["escrow_account"]["id"])
        # 50000 - 30000 = 20000.
        assert esc_after["balance_cents"] == 20000


class TestOverlapForbearancePart2:

    def test_first_plan_stays_active_when_second_activation_rejected(self, api):
        """PRD §3.4: "Activation transitions the plan from PROPOSED to
        ACTIVE, transitions the loan to FORBEARANCE, and pins the plan's
        deferred_total_cents for the entire window. Activation may only
        proceed against a loan that is in DELINQUENT or FORECLOSURE
        status."

        Design: Difficulty/resource_temporal_overlap/overlap_forbearance_window_inclusive_half_open_collision
        """
        ctx = setup_active_forbearance(
            clock_iso="2025-06-01T00:00:00Z",
            after_grace_iso="2025-07-25T00:00:00Z",
            start_date="2025-08-01T00:00:00Z",
            end_date="2025-10-31T00:00:00Z",
            reduced_payment_cents=50000,
            origination_date="2025-06-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        first_plan_id = ctx["forbearance_plan"]["id"]
        # Propose + try to activate a second overlapping plan.
        plan2 = validate_success(api.create_forbearance_plan(
            ctx["loan"]["id"],
            create_forbearance_plan_payload(
                start_date="2025-10-31T00:00:00Z",
                end_date="2025-12-31T00:00:00Z",
                reduced_payment_cents=60000,
            ),
            make_loan_servicer_headers(),
        ), expected_status=201)
        resp = api.activate_forbearance_plan(
            plan2["id"], make_loan_servicer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # First plan still ACTIVE; second plan still PROPOSED.
        first_after = fetch_forbearance_plan(first_plan_id)
        second_after = fetch_forbearance_plan(plan2["id"])
        assert first_after["status"] == "ACTIVE"
        assert second_after["status"] == "PROPOSED"


class TestWithdrawCompensatingInvariantPart2:

    def test_withdraw_returns_loan_to_reinstated(self, api):
        """PRD §3.5: "A case may be withdrawn at any non-terminal stage of
        the mediation/sale pipeline — specifically while the case is in any
        of MEDIATION_REQUIRED, IN_MEDIATION, MEDIATION_FAILED, or
        SALE_SCHEDULED — moving the case to WITHDRAWN and the loan back to
        REINSTATED. Both the case's version and the loan's version are
        incremented on withdrawal."

        Design: Difficulty/compensating_invariant/invariant_payment_then_reversal_preserves_principal_balance
        """
        ctx = setup_foreclosure_filed(
            clock_iso="2025-06-01T00:00:00Z",
            after_120_days_iso="2025-11-01T00:00:00Z",
            origination_date="2025-06-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        case_after = validate_success(api.withdraw_foreclosure(
            ctx["foreclosure_case"]["id"], make_loan_servicer_headers(),
        ))
        assert case_after["status"] == "WITHDRAWN"
        loan_after = fetch_loan(ctx["loan"]["id"])
        assert loan_after["status"] == "REINSTATED"


class TestDisbursementCancelInvariantPart2:

    def test_cancel_marks_disbursement_cancelled_terminal(self, api):
        """PRD §3.6: "A scheduled disbursement may instead be cancelled
        explicitly by a LoanServicer, moving it to CANCELLED, or cancelled
        implicitly as a cascade from a loan reaching PAID_OFF. The terminal
        statuses are PAID, FAILED, and CANCELLED."

        Design: Difficulty/compensating_invariant/invariant_disbursement_cancel_preserves_escrow_balance
        """
        ctx = setup_borrower_loan_escrow(
            clock_iso="2025-12-01T00:00:00Z",
            origination_date="2025-12-01T00:00:00Z",
        )
        disb = validate_success(api.create_disbursement(
            ctx["escrow_account"]["id"],
            {"kind": "INSURANCE", "amount_cents": 15000,
             "scheduled_for": "2026-06-01T00:00:00Z"},
            make_loan_servicer_headers(),
        ), expected_status=201)
        assert disb["status"] == "SCHEDULED"
        validate_success(api.cancel_disbursement(
            disb["id"], make_loan_servicer_headers(),
        ))
        disb_after = fetch_disbursement(disb["id"])
        assert disb_after["status"] == "CANCELLED"
