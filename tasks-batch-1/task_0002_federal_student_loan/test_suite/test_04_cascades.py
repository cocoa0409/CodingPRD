"""Cascade tests — depth-2 and depth-3 chains triggered by single API calls."""
from test_helpers import (
    api_client, validate_success,
    set_clock, create_borrower, create_loan, walk_loan_to_repayment,
    setup_borrower_and_loan_in_repayment,
    setup_discharge_application_under_review,
    setup_loan_with_active_standard_plan,
    post_payment, file_and_begin_review_discharge,
    make_borrower_headers,
    TEST_USERS,
)


LS = TEST_USERS["loan_servicer_headers"]
CA = TEST_USERS["collections_agent_headers"]


def test_discharge_approve_cascades_to_loan_and_reverses_pending_payment(api):
    """Depth-3 cascade: approve DischargeApplication → Loan to DISCHARGED →
    every PENDING Payment to REVERSED.

    PRD §3.9: "On a successful approve, review_notes is persisted, the
    application's status advances to APPROVED, and a two-step cascade fires.
    First, the parent loan transitions from REPAYMENT to DISCHARGED, with
    principal_balance_cents and accrued_interest_cents both being set to zero,
    and a StatusChange is written with reason_code DISCHARGE_APPROVED. Second,
    that loan transition itself triggers the cascade that moves every payment
    for the loan whose status is PENDING to REVERSED."

    Design: Difficulty/transitive_cascade/discharge_approve_depth3_app_loan_payment
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Casc V", ssn_last4="0020",
        is_veteran=True,
        loan_type="DIRECT_UNSUB", principal_cents=500_000,
        interest_rate_bps=500,
    )
    pay = post_payment(
        loan["id"], borrower["id"],
        amount_cents=10_000, payment_date="2026-06-01T00:00:00Z",
    )
    assert pay["status"] == "PENDING"
    app = file_and_begin_review_discharge(
        loan["id"], borrower["id"],
        discharge_type="VETERAN_TOTAL_DISABILITY",
    )

    validate_success(
        api.approve_discharge(
            app["id"],
            {"review_notes": "approved",
             "expected_application_version": app["version"]},
            LS,
        ),
        200,
    )

    loan_after = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_after["status"] == "DISCHARGED"

    pay_after = validate_success(api.get_payment(pay["id"], LS), 200)
    assert pay_after["status"] == "REVERSED"


def test_declare_default_cascades_active_plan_to_superseded(api):
    """Depth-2 cascade: declare-default on Loan → ACTIVE RepaymentPlan moves to
    SUPERSEDED with superseded_by_plan_id null.

    PRD §3.8: "The transition also fires a cascade against any RepaymentPlan
    for that loan whose status is ACTIVE: each such plan is moved from ACTIVE
    to SUPERSEDED, has its superseded_by_plan_id set to null to mark the
    supersession as statutory rather than competitive, and has its version
    incremented independently of the loan's increment."

    Design: Difficulty/transitive_cascade/default_declare_depth2_loan_plan
    """
    borrower, loan, plan = setup_loan_with_active_standard_plan(
        clock_iso="2025-06-01T00:00:00Z",
        full_name="Def B", ssn_last4="0030",
        loan_type="DIRECT_UNSUB", principal_cents=1_000_000,
        interest_rate_bps=500,
        disbursement_date="2025-06-01T00:00:00Z",
        plan_effective_date="2025-06-01T00:00:00Z",
    )
    # Advance clock past 270-day delinquency threshold.
    set_clock("2026-03-10T00:00:00Z")
    loan_after = validate_success(api.declare_default(loan["id"], CA), 200)
    assert loan_after["status"] == "DEFAULT"

    plan_after = validate_success(api.get_repayment_plan(plan["id"], LS), 200)
    assert plan_after["status"] == "SUPERSEDED"
