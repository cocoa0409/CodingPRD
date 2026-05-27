"""Forbearance plans: proposal, activation, completion, termination,
window validation, deferred-total calc, DELINQUENT↔FORBEARANCE cycle."""
from test_helpers import (
    ApiErrorId,
    api_client,
    validate_success,
    validate_error,
    set_clock,
    create_forbearance_plan_payload,
    fetch_loan,
    fetch_forbearance_plan,
    make_loan_servicer_headers,
    setup_delinquent_loan,
    setup_proposed_forbearance,
    setup_active_forbearance,
)


class TestForbearanceCycle:

    def test_terminate_active_plan_returns_loan_to_delinquent(self, api):
        """PRD §3.4: "The plan may instead be terminated early, in which
        case it moves to TERMINATED_EARLY and the loan reverts to
        DELINQUENT."

        Design: Difficulty/non_linear_state_machine/non_linear_loan_cycle_delinquent_forbearance_delinquent
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
        loan_in_forbearance = fetch_loan(ctx["loan"]["id"])
        assert loan_in_forbearance["status"] == "FORBEARANCE"
        # Terminate the active plan.
        resp = api.terminate_forbearance_plan(
            ctx["forbearance_plan"]["id"], make_loan_servicer_headers(),
        )
        plan_terminated = validate_success(resp)
        assert plan_terminated["status"] == "TERMINATED_EARLY"
        # Loan reverts to DELINQUENT.
        loan_after = fetch_loan(ctx["loan"]["id"])
        assert loan_after["status"] == "DELINQUENT"


class TestForbearanceWindowValidation:

    def test_forbearance_window_exceeded_returns_error(self, api):
        """PRD §3.4: "The window validation enforces that the end_date
        strictly exceeds the start_date and that the duration of the window
        does not exceed twelve months — specifically, the difference in
        days between end_date and start_date must be at most three hundred
        and sixty days. A plan that violates either bound is rejected with
        ERR_FORBEARANCE_WINDOW_EXCEEDED."

        Design: Corner/validations/validation_forbearance_window_exceeded
        """
        ctx = setup_delinquent_loan(
            clock_iso="2026-01-01T00:00:00Z",
            after_grace_iso="2026-02-20T00:00:00Z",
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        # 2026-03-01..2027-04-01 = > 360 days.
        resp = api.create_forbearance_plan(
            ctx["loan"]["id"],
            create_forbearance_plan_payload(
                start_date="2026-03-01T00:00:00Z",
                end_date="2027-04-01T00:00:00Z",
                reduced_payment_cents=50000,
            ),
            make_loan_servicer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_FORBEARANCE_WINDOW_EXCEEDED)


class TestForbearanceDeferralCalc:

    def test_deferred_total_pinned_at_activation(self, api):
        """PRD §3.4: "the deferred-per-month is the maximum of zero and the
        total monthly payment minus the reduced payment; the number of
        months in the window is computed inclusively from the start and end
        months by taking the end year minus the start year times twelve,
        plus the end month minus the start month, plus one; and the
        deferred total is the deferred-per-month multiplied by that month
        count. The pinned value is integer cents and is never recomputed
        thereafter."

        Design: Corner/calculations/calc_forbearance_deferral_total
        """
        ctx = setup_proposed_forbearance(
            clock_iso="2026-01-01T00:00:00Z",
            after_grace_iso="2026-02-20T00:00:00Z",
            start_date="2026-02-01T00:00:00Z",
            end_date="2026-04-30T00:00:00Z",
            reduced_payment_cents=50000,
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        # Activate to pin deferred_total_cents.
        resp = api.activate_forbearance_plan(
            ctx["forbearance_plan"]["id"], make_loan_servicer_headers(),
        )
        plan_active = validate_success(resp)
        assert plan_active["status"] == "ACTIVE"
        # total_monthly_payment_cents = 179865 + 50000 + 12500 = 242365.
        # deferred_per_month = 242365 - 50000 = 192365.
        # months: (2026-2026)*12 + (4-2) + 1 = 3.
        # deferred_total = 192365 * 3 = 577095.
        assert plan_active["deferred_total_cents"] == 577095


class TestForbearanceInvalidTransitions:

    def test_completed_plan_cannot_be_terminated(self, api):
        """PRD §3.4: "The plan's terminal states are COMPLETED and
        TERMINATED_EARLY."
        PRD §2.9: "State-transition admissibility is evaluated fifth,
        producing ERR_INVALID_STATE when the resource is not in a state
        from which the requested transition is permitted."

        Design: Corner/state_machines/sm_forbearance_invalid_from_completed_to_terminate
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
        # Advance past end_date and complete.
        set_clock("2025-09-01T00:00:00Z")
        validate_success(api.complete_forbearance_plan(
            ctx["forbearance_plan"]["id"], make_loan_servicer_headers(),
        ))
        plan_after_complete = fetch_forbearance_plan(
            ctx["forbearance_plan"]["id"],
        )
        assert plan_after_complete["status"] == "COMPLETED"
        # Now attempt to terminate the COMPLETED plan.
        resp = api.terminate_forbearance_plan(
            ctx["forbearance_plan"]["id"], make_loan_servicer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestForbearanceBlocksForeclosure:

    def test_loan_with_active_forbearance_cannot_be_foreclosed(self, api):
        """PRD §3.5: "Foreclosure may only be filed against a loan that is
        DELINQUENT, whose days_past_due is at least one hundred and twenty,
        and that has no ACTIVE forbearance plan attached."
        PRD §2.9: "State-transition admissibility is evaluated fifth,
        producing ERR_INVALID_STATE when the resource is not in a state
        from which the requested transition is permitted."

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
        set_clock("2025-10-01T00:00:00Z")
        loan = fetch_loan(ctx["loan"]["id"])
        assert loan["status"] == "FORBEARANCE"
        resp = api.file_foreclosure(
            ctx["loan"]["id"], loan["version"],
            make_loan_servicer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_second_overlapping_forbearance_rejected_while_first_active(self, api):
        """PRD §3.4: "Activation may only proceed against a loan that is in
        DELINQUENT or FORECLOSURE status."
        PRD §2.9: "State-transition admissibility is evaluated fifth,
        producing ERR_INVALID_STATE when the resource is not in a state
        from which the requested transition is permitted."

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
        # Loan is now in FORBEARANCE. Propose a second plan and try to
        # activate; activation precondition requires DELINQUENT/FORECLOSURE.
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
