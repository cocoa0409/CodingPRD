"""Parallel/branching state machines and cross-entity state dependencies.

Difficulty queue A: non_linear_state_machine and cross_entity_state_dependency.
"""
import pytest

from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    make_borrower_headers,
    make_cosigner_headers,
    make_disbursement_officer_headers,
    setup_funded_loan,
    setup_prequalified_application,
    get_application,
    get_loan,
    get_cosigner,
    start_forbearance,
    schedule_disbursement,
    api_client,
)


class TestLoanParallelDimensions:
    def test_forbearance_leaves_release_dimension_untouched(self, api):
        """PRD 3.11: "This touches only the repayment dimension; the
        cosigner-release dimension is untouched."
        PRD 3.7: "The loan carries two independent status dimensions."

        Funded loan with a CONSENTED cosigner: repayment CURRENT, release PENDING.
        Placing into FORBEARANCE moves repayment_status but leaves
        cosigner_release_status PENDING.

        Design: Difficulty/non_linear_state_machine/loan_parallel_repayment_and_release_dimensions
        """
        bundle = setup_funded_loan(
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-PAR1", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
            with_cosigner=True,
        )
        loan = bundle["loan"]
        assert loan["repayment_status"] == "CURRENT"
        assert loan["cosigner_release_status"] == "PENDING"

        start_forbearance(loan, reason_code="JOB_LOSS", months_requested=3)
        loan_after = get_loan(loan["id"])
        assert loan_after["repayment_status"] == "FORBEARANCE", (
            f"repayment_status should be FORBEARANCE, got {loan_after['repayment_status']}"
        )
        assert loan_after["cosigner_release_status"] == "PENDING", (
            f"release dimension must be untouched (PENDING), got {loan_after['cosigner_release_status']}"
        )

    def test_repayment_transition_independent_of_release_status(self, api):
        """PRD 3.7: "The loan carries two independent status dimensions. The
        repayment dimension, repayment_status, begins CURRENT and ranges over
        CURRENT, FORBEARANCE, DELINQUENT, PAID_OFF, and CHARGED_OFF, with
        PAID_OFF and CHARGED_OFF terminal."

        Design: Difficulty/non_linear_state_machine/loan_parallel_repayment_and_release_dimensions
        """
        bundle = setup_funded_loan(
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-PAR2", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
            with_cosigner=True,
        )
        loan = bundle["loan"]
        release_before = loan["cosigner_release_status"]
        start_forbearance(loan, reason_code="MEDICAL", months_requested=2)
        loan_after = get_loan(loan["id"])
        assert loan_after["repayment_status"] == "FORBEARANCE"
        assert loan_after["cosigner_release_status"] == release_before


class TestCosignerBranchingMachine:
    def test_cosigner_decline_is_terminal_and_does_not_recompute_dti(self, api):
        """PRD 3.3: "A Cosigner may instead decline from INVITED to DECLINED,
        which is also defined only from INVITED and records a cosigner audit
        event but changes no income."

        Borrower income 4,000,000, principal 8,000,000, term 60 -> borrower-only
        dti 0.4512. Declining the cosigner does NOT recompute with cosigner income,
        so dti stays 0.4512.

        Design: Difficulty/non_linear_state_machine/cosigner_invited_consent_release_with_terminal_decline
        """
        bundle = setup_prequalified_application(
            grid_overrides={"rate_type": "FIXED", "term_months": 60, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 4_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 8_000_000,
                                   "requested_term_months": 60, "requested_rate_type": "FIXED"},
            with_cosigner=True,
            cosigner_overrides={"cosigner_annual_income_cents": 2_000_000},
            cosigner_consents=False,
        )
        cosigner = bundle["cosigner"]
        cos_headers = make_cosigner_headers(cosigner["id"])
        declined = get_success_data(api.decline_cosigner(cosigner["id"], cos_headers))
        assert declined["consent_status"] == "DECLINED", (
            f"consent_status should be DECLINED, got {declined['consent_status']}"
        )
        app_after = get_application(bundle["application"]["id"])
        assert app_after["dti_ratio"] == pytest.approx(0.4512, abs=1e-9), (
            f"decline must not recompute dti with cosigner income; got {app_after['dti_ratio']}"
        )

    def test_declined_cosigner_cannot_consent(self, api):
        """PRD 3.3: "Consent is defined only from INVITED, and only while the
        parent application is still in DRAFT or PREQUALIFIED; outside those parent
        states or from a non-INVITED consent status the transition is rejected
        with ERR_INVALID_STATE."

        Design: Difficulty/non_linear_state_machine/cosigner_invited_consent_release_with_terminal_decline
        """
        bundle = setup_prequalified_application(
            grid_overrides={"rate_type": "FIXED", "term_months": 60, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 4_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 8_000_000,
                                   "requested_term_months": 60, "requested_rate_type": "FIXED"},
            with_cosigner=True,
            cosigner_overrides={"cosigner_annual_income_cents": 2_000_000},
            cosigner_consents=False,
        )
        cosigner = bundle["cosigner"]
        cos_headers = make_cosigner_headers(cosigner["id"])
        get_success_data(api.decline_cosigner(cosigner["id"], cos_headers))
        resp = api.consent_cosigner(cosigner["id"], cos_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestCrossEntityStateDependency:
    def test_offer_lock_blocked_by_invited_cosigner(self, api):
        """PRD 3.4: "If a cosigner is attached to the application, that cosigner's
        consent_status must be CONSENTED; a lock attempted while the attached
        cosigner is INVITED, DECLINED, or otherwise not consented is rejected with
        ERR_COSIGNER_NOT_CONSENTED (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/offer_lock_requires_cosigner_consented
        """
        bundle = setup_prequalified_application(
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
            with_cosigner=True,
            cosigner_overrides={"cosigner_annual_income_cents": 4_000_000},
            cosigner_consents=False,
        )
        borrower = bundle["borrower"]
        app = bundle["application"]
        offer = bundle["offers"][0]
        headers = make_borrower_headers(borrower["id"])
        resp = api.lock_offer(
            offer["id"], {"expected_application_version": app["version"], "autopay_elected": True}, headers)
        validate_error(resp, ApiErrorId.ERR_COSIGNER_NOT_CONSENTED.value)
        app_after = get_application(app["id"])
        assert app_after["status"] == "PREQUALIFIED", (
            f"application must stay PREQUALIFIED when lock is blocked, got {app_after['status']}"
        )

    def test_offer_lock_blocked_leaves_cosigner_invited(self, api):
        """PRD 3.4: "a lock attempted while the attached cosigner is INVITED,
        DECLINED, or otherwise not consented is rejected with
        ERR_COSIGNER_NOT_CONSENTED (HTTP 409)."

        The blocked lock is a read-only rejection: the attached cosigner stays in
        consent_status INVITED.

        Design: Difficulty/cross_entity_state_dependency/offer_lock_requires_cosigner_consented
        """
        bundle = setup_prequalified_application(
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
            with_cosigner=True,
            cosigner_overrides={"cosigner_annual_income_cents": 4_000_000},
            cosigner_consents=False,
        )
        borrower = bundle["borrower"]
        app = bundle["application"]
        offer = bundle["offers"][0]
        cosigner = bundle["cosigner"]
        resp = api.lock_offer(
            offer["id"], {"expected_application_version": app["version"], "autopay_elected": False},
            make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_COSIGNER_NOT_CONSENTED.value)
        cosigner_after = get_cosigner(cosigner["id"])
        assert cosigner_after["consent_status"] == "INVITED", (
            f"cosigner must remain INVITED after the blocked lock, got {cosigner_after['consent_status']}"
        )

    def test_disbursement_send_blocked_when_loan_in_forbearance(self, api):
        """PRD 3.8: "The transition is defined only from SCHEDULED, and only while
        the parent loan's repayment_status is CURRENT."

        A SCHEDULED disbursement on a loan placed into FORBEARANCE cannot be sent;
        the send is rejected with ERR_INVALID_STATE.

        Design: Difficulty/cross_entity_state_dependency/disbursement_send_requires_loan_current
        """
        bundle = setup_funded_loan(
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-CESD", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        loan = bundle["loan"]
        officer_id = bundle["officer_id"]
        disb = schedule_disbursement(loan, officer_id, prior_servicer_name="Servicer X",
                                     payoff_amount_cents=3_000_000)
        start_forbearance(loan, reason_code="MEDICAL", months_requested=2)
        resp = api.send_disbursement(disb["id"], make_disbursement_officer_headers(officer_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        disb_after = get_success_data(api.get_disbursement(
            disb["id"], make_disbursement_officer_headers(officer_id)))
        assert disb_after["status"] == "SCHEDULED", (
            f"disbursement must stay SCHEDULED, got {disb_after['status']}"
        )

    def test_disbursement_send_succeeds_once_loan_returns_to_current(self, api):
        """PRD 3.8: "The transition is defined only from SCHEDULED, and only while
        the parent loan's repayment_status is CURRENT."
        PRD 3.11: "the plan's status becomes ENDED, the loan's repayment_status
        returns to CURRENT, and a loan audit event is recorded."

        The send depends specifically on the Loan being CURRENT: after ending
        forbearance the loan is CURRENT again and the same SCHEDULED disbursement
        can be sent.

        Design: Difficulty/cross_entity_state_dependency/disbursement_send_requires_loan_current
        """
        bundle = setup_funded_loan(
            officer_id="do-cesd-2",
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-CESD2", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        loan = bundle["loan"]
        officer_id = "do-cesd-2"
        disb = schedule_disbursement(loan, officer_id, prior_servicer_name="Servicer Y",
                                     payoff_amount_cents=3_000_000)
        sa_id = "sa-cesd-2"
        start_forbearance(loan, servicing_agent_id=sa_id, reason_code="MEDICAL", months_requested=2)
        # End forbearance: loan returns to CURRENT.
        from test_helpers import list_forbearance_plans, make_servicing_agent_headers
        plan = list_forbearance_plans(loan["id"], status="ACTIVE", servicing_agent_id=sa_id)[0]
        get_success_data(api.end_forbearance(plan["id"], make_servicing_agent_headers(sa_id)))
        assert get_loan(loan["id"])["repayment_status"] == "CURRENT"

        sent = get_success_data(api.send_disbursement(
            disb["id"], make_disbursement_officer_headers(officer_id)))
        assert sent["status"] == "SENT", (
            f"send should succeed once the loan is CURRENT again, got {sent['status']}"
        )
