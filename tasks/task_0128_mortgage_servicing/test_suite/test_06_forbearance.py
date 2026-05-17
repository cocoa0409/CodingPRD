"""Forbearance plan lifecycle: create, cancel, complete, breach.

Coverage targets (PRD §3.4):
- ERR_HARDSHIP_AFFIDAVIT_MISSING when borrower has no hardship attestation.
- ERR_FORBEARANCE_PLAN_EXISTS when loan already has an ACTIVE plan.
- ERR_FORBEARANCE_DATE_INVALID when start_date > Loan.next_due_date.
- Loan.posture transitions to FORBEARANCE on plan creation.
- /cancel transitions ACTIVE to CANCELED.
- After end_date, DEFERRAL path -> COMPLETED, principal += total_paused.
- After end_date+30d with cure_balance > 0 -> BREACHED, posture := DEFAULT.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    FORBEARANCE_BREACH_GRACE_DAYS,
    advance_clock,
    assert_forbearance_plan,
    cancel_forbearance_plan,
    create_borrower,
    create_forbearance_plan,
    create_loan,
    create_loan_payload,
    get_loan,
    iso_datetime_utc_midnight,
    run_sweep,
    setup_active_forbearance_plan,
    setup_borrower_and_current_loan,
    setup_borrower_with_hardship,
    today_utc,
    validate_error,
    validate_success,
)


class TestForbearanceCreatePreconditions:
    def test_without_hardship_rejected(self, api, servicer_headers):
        """PRD §3.4: "The borrower must have a non-null
        hardship_attested_at — otherwise the request is rejected with
        ERR_HARDSHIP_AFFIDAVIT_MISSING."

        Claim: borrower with hardship_attested_at == null -> POST
        /forbearance-plans -> ERR_HARDSHIP_AFFIDAVIT_MISSING.
        """
        b, loan = setup_borrower_and_current_loan(with_hardship=False)
        resp = api.create_forbearance_plan(
            loan["id"],
            {"start_date": iso_datetime_utc_midnight(today_utc()),
             "months": 3, "repayment_method": "LUMP_SUM"},
            # LMU role per PRD §4.
            headers={"X-User-ID": "lmu-001",
                     "X-User-Role": "LossMitigationUnderwriter"},
        )
        validate_error(resp,
                       ApiErrorId.ERR_HARDSHIP_AFFIDAVIT_MISSING.value)

    def test_second_active_plan_rejected(self, api, lmu_headers):
        """PRD §3.4: "The loan must not already have another plan in
        status ACTIVE — otherwise the request is rejected with
        ERR_FORBEARANCE_PLAN_EXISTS."

        Claim: a second forbearance-plan create on a loan with an
        ACTIVE plan -> ERR_FORBEARANCE_PLAN_EXISTS.
        """
        b, loan, plan = setup_active_forbearance_plan()
        # Try to create a second plan.
        resp = api.create_forbearance_plan(
            loan["id"],
            {"start_date": iso_datetime_utc_midnight(today_utc()),
             "months": 3, "repayment_method": "LUMP_SUM"},
            lmu_headers,
        )
        validate_error(resp,
                       ApiErrorId.ERR_FORBEARANCE_PLAN_EXISTS.value)

    def test_start_date_after_next_due_date_rejected(
        self, api, lmu_headers,
    ):
        """PRD §3.4: "the start_date must be on or before
        Loan.next_due_date, since the plan cannot start in the future
        of arrears — otherwise the request is rejected with
        ERR_FORBEARANCE_DATE_INVALID."

        Claim: start_date > Loan.next_due_date ->
        ERR_FORBEARANCE_DATE_INVALID.
        """
        b, loan = setup_borrower_and_current_loan(with_hardship=True)
        # next_due_date defaults to origination_date + 1 month ~= today
        # + 30d. Pick start_date = today + 60d (clearly after).
        future = iso_datetime_utc_midnight(today_utc() + timedelta(days=60))
        resp = api.create_forbearance_plan(
            loan["id"],
            {"start_date": future, "months": 3,
             "repayment_method": "LUMP_SUM"},
            lmu_headers,
        )
        validate_error(resp,
                       ApiErrorId.ERR_FORBEARANCE_DATE_INVALID.value)


class TestForbearanceActivation:
    def test_loan_posture_cascades_to_forbearance(
        self, api, servicer_headers,
    ):
        """PRD §3.4: "Loan.posture cascades to FORBEARANCE while
        next_due_date is frozen until the plan's end_date."

        Claim: after creating an ACTIVE plan, Loan.posture == FORBEARANCE.
        """
        b, loan, plan = setup_active_forbearance_plan()
        assert plan["status"] == "ACTIVE"
        loan_after = get_loan(loan["id"])
        assert loan_after["posture"] == "FORBEARANCE"

    def test_total_paused_equals_months_times_scheduled_plus_escrow(
        self, api, servicer_headers,
    ):
        """PRD §3.4: "total_paused_cents is set to months multiplied by
        the sum of Loan.scheduled_payment_cents and
        Loan.monthly_escrow_payment_cents".

        Claim: total_paused_cents == months *
        (scheduled_payment_cents + monthly_escrow_payment_cents).
        """
        b, loan, plan = setup_active_forbearance_plan(
            months=3,
            monthly_escrow_payment_cents=20_000,
        )
        expected = 3 * (
            int(loan["scheduled_payment_cents"])
            + int(loan["monthly_escrow_payment_cents"])
        )
        assert int(plan["total_paused_cents"]) == expected, (
            f"total_paused_cents={plan['total_paused_cents']} != "
            f"expected {expected}"
        )


class TestForbearanceCancel:
    def test_cancel_active_plan_transitions_to_canceled(
        self, api, lmu_headers,
    ):
        """PRD §3.4: "cancellation transitions the plan to CANCELED
        and Loan.posture reverts to DELINQUENT or CURRENT based on
        the recomputed delinquency_days."

        Claim: /cancel on ACTIVE -> status=CANCELED.
        """
        b, loan, plan = setup_active_forbearance_plan()
        cancelled = cancel_forbearance_plan(loan["id"], plan["id"])
        assert cancelled["status"] == "CANCELED"


class TestForbearanceBreach:
    def test_30_days_past_end_with_cure_balance_breaches(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: "When the clock advances at least thirty days past
        end_date and cure_balance_cents is still strictly positive, the
        plan transitions to BREACHED and Loan.posture cascades to
        DEFAULT."

        Claim: LUMP_SUM plan with no payment, advance clock past
        end_date + 30d -> plan.status=BREACHED, loan.posture=DEFAULT.
        """
        # months=1 => end_date = start_date + 1 month (~30d)
        b, loan, plan = setup_active_forbearance_plan(
            months=1, repayment_method="LUMP_SUM",
        )
        # Advance well past end_date + 30d grace.
        advance_clock(30 + 31)
        # Re-read via the loan endpoint (which surfaces the cascade).
        loan_after = get_loan(loan["id"])
        # And read the plan via list.
        resp = api.list_forbearance_plans(loan["id"],
                                          {"X-User-ID": "servicer-001",
                                           "X-User-Role": "Servicer"})
        data = validate_success(resp, expected_status=200)
        items = data if isinstance(data, list) else data.get("data", data)
        matched = next(p for p in items if p["id"] == plan["id"])
        assert matched["status"] == "BREACHED", (
            f"after end_date + 30d with cure_balance > 0, plan must be "
            f"BREACHED; got status={matched['status']}"
        )
        assert loan_after["posture"] == "DEFAULT", (
            f"Loan.posture must cascade to DEFAULT on BREACHED plan; "
            f"got posture={loan_after['posture']}"
        )
