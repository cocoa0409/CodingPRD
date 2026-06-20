"""Valid transitions, invalid-from rejection, terminal lockdown, idempotency,
initial states.

Corner queue B: section state_machines (non-stub instances only;
parallel_loan_repayment_and_release_dimensions is owned by the §1.8 difficulty
instance and is not re-translated here).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_borrower_headers,
    make_cosigner_headers,
    make_underwriter_headers,
    make_servicing_agent_headers,
    setup_prequalified_application,
    setup_approved_application,
    setup_funded_loan,
    create_borrower,
    create_application,
    prequalify,
    invite_cosigner,
    schedule_disbursement,
    send_disbursement,
    get_loan,
    api_client,
)


def test_prequalify_from_draft_moves_to_prequalified(api):
    """PRD 3.2: "Prequalification moves the application from DRAFT to
    PREQUALIFIED and is the heart of intake."
    PRD 3.2: "a borrower at position two or three is moved down one position (so
    PRIME becomes NEAR_PRIME and SUPER_PRIME becomes PRIME)."

    Design: Corner/state_machines/prequalify_from_draft_moves_to_prequalified
    """
    bundle = setup_prequalified_application(
        grid_overrides={"rate_type": "FIXED", "term_months": 60, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 4_000_000,
                               "requested_term_months": 60, "requested_rate_type": "FIXED"},
    )
    app = bundle["application"]
    assert app["status"] == "PREQUALIFIED"
    assert app["soft_pull_fico_band"] == "NEAR_PRIME", (
        f"PRIME corrected one notch toward center should be NEAR_PRIME, got {app['soft_pull_fico_band']}"
    )


def test_prequalify_from_draft_twice_invalid_state(api):
    """PRD 3.2: "It is defined only from DRAFT; a request from any other state is
    rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/prequalify_from_draft_twice_invalid_state
    """
    bundle = setup_prequalified_application(
        grid_overrides={"rate_type": "FIXED", "term_months": 60, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 4_000_000,
                               "requested_term_months": 60, "requested_rate_type": "FIXED"},
    )
    borrower = bundle["borrower"]
    resp = api.prequalify_application(bundle["application"]["id"], make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_approve_from_draft_invalid_state(api):
    """PRD 3.5: "Approval is defined only from UNDER_REVIEW; from any other state
    ERR_INVALID_STATE applies."

    Design: Corner/state_machines/approve_from_draft_invalid_state
    """
    borrower = create_borrower(email="corner.b9@x.com", full_name="Corner B9",
                               annual_income_cents=12_000_000, fico_band="PRIME")
    application = create_application(borrower, requested_principal_cents=4_000_000,
                                     requested_term_months=60, requested_rate_type="FIXED")
    resp = api.approve_application(application["id"], make_underwriter_headers("uw-corner-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_withdraw_from_approved_invalid_state(api):
    """PRD 3.6: "A Borrower may withdraw an application while it is in DRAFT,
    PREQUALIFIED, or UNDER_REVIEW; from any other state the withdrawal is rejected
    with ERR_INVALID_STATE."

    Design: Corner/state_machines/withdraw_from_approved_invalid_state
    """
    bundle = setup_approved_application(
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    borrower = bundle["borrower"]
    resp = api.withdraw_application(bundle["application"]["id"], make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_cosigner_consent_from_declined_invalid_state(api):
    """PRD 3.3: "Consent is defined only from INVITED, and only while the parent
    application is still in DRAFT or PREQUALIFIED; outside those parent states or
    from a non-INVITED consent status the transition is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/cosigner_consent_from_declined_invalid_state
    """
    borrower = create_borrower(email="corner.b11@x.com", full_name="Corner B11",
                               annual_income_cents=5_000_000, fico_band="PRIME")
    application = create_application(borrower, requested_principal_cents=4_000_000,
                                     requested_term_months=60, requested_rate_type="FIXED")
    cosigner = invite_cosigner(borrower, application, cosigner_email="corner.c11@x.com",
                               cosigner_annual_income_cents=2_000_000)
    cos_headers = make_cosigner_headers(cosigner["id"])
    get_success_data(api.decline_cosigner(cosigner["id"], cos_headers))
    resp = api.consent_cosigner(cosigner["id"], cos_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_disbursement_confirm_from_scheduled_invalid_state(api):
    """PRD 3.8: "From SENT, a payoff may be confirmed by the servicer, moving it
    to CONFIRMED with a disbursement audit event, or marked returned, moving it to
    RETURNED with a disbursement audit event; both are defined only from SENT."

    Design: Corner/state_machines/disbursement_confirm_from_scheduled_invalid_state
    """
    bundle = setup_funded_loan(
        officer_id="do-corner-3",
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-CFM", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    loan = bundle["loan"]
    disb = schedule_disbursement(loan, "do-corner-3", prior_servicer_name="Old Co",
                                 payoff_amount_cents=2_000_000)
    from test_helpers import make_disbursement_officer_headers
    resp = api.confirm_disbursement(disb["id"], make_disbursement_officer_headers("do-corner-3"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_disbursement_send_then_return_valid_transition(api):
    """PRD 3.8: "or marked returned, moving it to RETURNED with a disbursement
    audit event; both are defined only from SENT."

    Design: Corner/state_machines/disbursement_send_then_return_valid_transition
    """
    bundle = setup_funded_loan(
        officer_id="do-corner-4",
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-RET", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    loan = bundle["loan"]
    disb = schedule_disbursement(loan, "do-corner-4", prior_servicer_name="Old Co",
                                 payoff_amount_cents=2_000_000)
    send_disbursement(disb["id"], "do-corner-4")
    from test_helpers import make_disbursement_officer_headers
    resp = api.return_disbursement(disb["id"], make_disbursement_officer_headers("do-corner-4"))
    data = validate_success(resp, 200)
    assert data["status"] == "RETURNED", f"status should be RETURNED, got {data['status']}"


def test_charge_off_from_current_invalid_state(api):
    """PRD 3.11: "Charge-off is defined only from repayment_status DELINQUENT and
    moves the loan to the terminal CHARGED_OFF state, sets cosigner_release_status
    to NOT_APPLICABLE, and records a loan audit event."

    Design: Corner/state_machines/charge_off_from_current_invalid_state
    """
    bundle = setup_funded_loan(
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-CHG", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    loan = bundle["loan"]
    resp = api.charge_off(loan["id"], make_servicing_agent_headers("sa-corner-5"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_loan_funded_initial_states_current_and_pending(api):
    """PRD 3.7: "The repayment dimension, repayment_status, begins CURRENT"
    PRD 3.7: "it begins PENDING when a CONSENTED cosigner exists on the
    application and NOT_APPLICABLE otherwise."

    A loan funded with no cosigner: repayment CURRENT, release NOT_APPLICABLE.

    Design: Corner/state_machines/loan_funded_initial_states_current_and_pending
    """
    bundle = setup_funded_loan(
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-INIT", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    loan = bundle["loan"]
    assert loan["repayment_status"] == "CURRENT"
    assert loan["cosigner_release_status"] == "NOT_APPLICABLE", (
        f"no CONSENTED cosigner -> NOT_APPLICABLE, got {loan['cosigner_release_status']}"
    )
