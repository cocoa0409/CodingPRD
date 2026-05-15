"""Discharge applications: PSLF + Veteran-TPD flows, SoD enforcement,
state-machine guards, balance-zeroing cascade.

Anchors: PRD §3.9, §2.9.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    api_client,
    approve_discharge,
    assert_borrower_aggregates_match,
    assert_discharge_application,
    create_borrower_with_loan_in_repayment,
    create_discharge_application_payload,
    make_borrower_headers,
    move_discharge_to_under_review,
    submit_discharge_application,
    submit_employment_certification,
    submit_and_approve_employment_certification,
    update_discharge_application_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    setup_pslf_ready_for_approval,
    setup_veteran_tpd_ready_for_approval,
)
from test_helpers.test_users import (
    SERVICER_APPROVER_ID,
    SERVICER_CERTIFIER_ID,
    make_servicer_approver_headers,
    make_servicer_certifier_headers,
)


# ---------------------------------------------------------------------------
# 1. Submission + state transitions (PRD §3.9)
# ---------------------------------------------------------------------------
def test_submit_discharge_application_initial_state(api):
    """PRD §3.9: "Submission is performed by the borrower (or by a
    ServicerAdmin acting on their behalf) and carries program set to
    either PSLF or VETERAN_TPD; the application enters SUBMITTED."

    Claim: POST yields status=SUBMITTED.
    """
    borrower, _, _ = create_borrower_with_loan_in_repayment()
    app = submit_discharge_application(borrower["id"], "PSLF",
                                       use_borrower_role=True)
    assert_discharge_application(app)
    assert app["status"] == "SUBMITTED"


def test_pslf_under_review_without_approved_cert_rejected(api):
    """PRD §3.9: "Moving a PSLF application from SUBMITTED to
    UNDER_REVIEW requires that at least one EmploymentCertification
    for this borrower is already in APPROVED status — otherwise the
    certifier's transition is rejected with
    ERR_PSLF_NO_EMPLOYMENT_EVIDENCE."

    Claim: PSLF SUBMITTED -> UNDER_REVIEW without any APPROVED cert
    fires ERR_PSLF_NO_EMPLOYMENT_EVIDENCE.
    """
    borrower, _, _ = create_borrower_with_loan_in_repayment()
    # Submit a cert but DO NOT approve it.
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


def test_servicer_approver_only_role_to_approve_under_review(api):
    """PRD §3.9: "from UNDER_REVIEW, a ServicerApprover is the only
    role permitted to approve or reject."

    Claim: a ServicerCertifier attempting to PATCH
    status=APPROVED from UNDER_REVIEW is rejected with
    ERR_FORBIDDEN.
    """
    borrower, loan, _, app, _ = setup_pslf_ready_for_approval(
        n_qualifying=120,
    )
    res = api.update_discharge_application(
        borrower["id"], app["id"],
        update_discharge_application_payload(
            status="APPROVED", approved_loan_ids=[loan["id"]],
        ),
        TEST_USERS["servicer_certifier_headers"],
    )
    validate_error(res, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# 2. Segregation of duties (PRD §2.9)
# ---------------------------------------------------------------------------
def test_sod_violation_when_approver_equals_certifier(api):
    """PRD §2.9: "The ServicerApprover whose X-User-ID accompanies
    the request that moves a DischargeApplication to APPROVED must
    not equal any ServicerCertifier's X-User-ID recorded as
    reviewed_by on an EmploymentCertification that is in APPROVED
    status for this borrower. When the two ids match, the request
    is rejected with ERR_SOD_VIOLATION."

    Claim: approver X-User-ID == certifier X-User-ID who reviewed
    the supporting evidence → ERR_SOD_VIOLATION.
    """
    borrower, loan, _, app, _ = setup_pslf_ready_for_approval(
        n_qualifying=120,
    )
    # Use an approver header whose X-User-ID equals the
    # SERVICER_CERTIFIER_ID that approved the EmploymentCertification.
    sod_approver = make_servicer_approver_headers(SERVICER_CERTIFIER_ID)
    res = api.update_discharge_application(
        borrower["id"], app["id"],
        update_discharge_application_payload(
            status="APPROVED", approved_loan_ids=[loan["id"]],
        ),
        sod_approver,
    )
    validate_error(res, "ERR_SOD_VIOLATION")


# ---------------------------------------------------------------------------
# 3. PSLF threshold (PRD §3.9, PRD §3.8)
# ---------------------------------------------------------------------------
def test_pslf_insufficient_payments_rejected(api):
    """PRD §3.9: "For a PSLF approval, the qualification check (§3.8)
    must yield qualifying_pslf_payment_count of at least 120 for every
    loan in approved_loan_ids; failure for any loan is reported as
    ERR_PSLF_INSUFFICIENT_PAYMENTS."

    Claim: PSLF approval with <120 qualifying payments triggers
    ERR_PSLF_INSUFFICIENT_PAYMENTS.
    """
    borrower, loan, _, app, _ = setup_pslf_ready_for_approval(
        n_qualifying=3,  # well under 120
    )
    res = api.update_discharge_application(
        borrower["id"], app["id"],
        update_discharge_application_payload(
            status="APPROVED", approved_loan_ids=[loan["id"]],
        ),
        TEST_USERS["servicer_approver_headers"],
    )
    validate_error(res, "ERR_PSLF_INSUFFICIENT_PAYMENTS")


# ---------------------------------------------------------------------------
# 4. Veteran TPD path (PRD §3.9)
# ---------------------------------------------------------------------------
def test_veteran_tpd_approval_zeros_loan_balances(api):
    """PRD §3.9: "Approval cascades to every loan in approved_loan_ids:
    each transitions to DISCHARGED, principal_balance_cents and
    accrued_interest_cents are zeroed, status_entered_at is set to
    now, and the application captures the pre-discharge sums into
    discharged_principal_cents and discharged_interest_cents."

    Claim: VETERAN_TPD approval moves loan to DISCHARGED with
    balances at 0 and captures the pre-discharge principal+interest
    sums on the application.
    """
    borrower, loan, app, _ = setup_veteran_tpd_ready_for_approval()
    pre_principal = loan["principal_balance_cents"]
    pre_interest = loan["accrued_interest_cents"]
    approved = approve_discharge(
        borrower["id"], app["id"], [loan["id"]],
    )
    assert approved["status"] == "APPROVED"
    assert approved["discharged_principal_cents"] == pre_principal, (
        "PRD §3.9: discharged_principal_cents must equal pre-discharge "
        "principal"
    )
    fetched_loan = validate_success(
        api.get_loan(borrower["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert fetched_loan["status"] == "DISCHARGED"
    assert fetched_loan["principal_balance_cents"] == 0
    assert fetched_loan["accrued_interest_cents"] == 0


def test_veteran_tpd_on_non_veteran_rejected(api):
    """PRD §3.9: "For a VETERAN_TPD approval, the borrower's
    veteran_status must be TPD_VETERAN; failure is reported as
    ERR_VETERAN_INELIGIBLE."

    Claim: VETERAN_TPD approval on a borrower whose veteran_status
    is NONE triggers ERR_VETERAN_INELIGIBLE.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment(
        veteran_status="NONE",
    )
    app = submit_discharge_application(
        borrower["id"], "VETERAN_TPD", use_borrower_role=True,
    )
    move_discharge_to_under_review(borrower["id"], app["id"])
    res = api.update_discharge_application(
        borrower["id"], app["id"],
        update_discharge_application_payload(
            status="APPROVED", approved_loan_ids=[loan["id"]],
        ),
        TEST_USERS["servicer_approver_headers"],
    )
    validate_error(res, "ERR_VETERAN_INELIGIBLE")


def test_discharge_recomputes_borrower_aggregates(api):
    """PRD §3.9: "The borrower's aggregate_principal_balance_cents
    and aggregate_interest_balance_cents are then recomputed."
    PRD §2.11: "A loan that has reached either of the two terminal
    statuses (PAID_OFF or DISCHARGED) drops out of the aggregate."

    Claim: after VETERAN_TPD approval the borrower's aggregates are
    zero (the only loan was discharged).
    """
    borrower, loan, app, _ = setup_veteran_tpd_ready_for_approval()
    approve_discharge(borrower["id"], app["id"], [loan["id"]])
    fetched = validate_success(
        api.get_borrower(borrower["id"],
                         TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert fetched["aggregate_principal_balance_cents"] == 0
    assert fetched["aggregate_interest_balance_cents"] == 0
