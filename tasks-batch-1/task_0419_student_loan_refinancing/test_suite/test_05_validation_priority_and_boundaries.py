"""Validation-priority precedence pairs and numeric boundary precision.

Difficulty queue A: priority_pair_validation_conflict and boundary_precision_check.
"""
import pytest

from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_disbursement_officer_headers,
    make_underwriter_headers,
    setup_funded_loan,
    setup_loan_with_eligible_cosigner,
    set_clock,
    schedule_disbursement,
    send_disbursement,
    confirm_disbursement,
    get_cosigner,
    api_client,
)


class TestStateBeforeSegregation:
    def test_confirmed_disbursement_resend_returns_invalid_state_not_segregation(self, api):
        """PRD 2.6: "then that the target is in a legal source state for the
        transition (ERR_INVALID_STATE), then optimistic-concurrency staleness on
        offer lock (ERR_STALE_APPLICATION_VERSION), and only then the business
        rules specific to each operation."
        PRD 3.8: "From SENT, a payoff may be confirmed by the servicer, moving it
        to CONFIRMED with a disbursement audit event"

        A CONFIRMED disbursement re-sent by the approving underwriter's id fails the
        state check (ERR_INVALID_STATE) before the segregation-of-duties check.

        Design: Difficulty/priority_pair_validation_conflict/state_before_segregation_on_disbursement_send
        """
        shared_uw = "uw-shared-sb"
        bundle = setup_funded_loan(
            underwriter_id=shared_uw,
            officer_id="do-sb-5",
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-P5", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        loan = bundle["loan"]
        disb = schedule_disbursement(loan, "do-sb-5", prior_servicer_name="Old Servicer",
                                     payoff_amount_cents=3_000_000)
        send_disbursement(disb["id"], "do-sb-5")
        confirm_disbursement(disb["id"], "do-sb-5")

        # Re-send under the approving underwriter's id: state is CONFIRMED, so the
        # state precondition fires before the segregation check.
        resp = api.send_disbursement(disb["id"], make_disbursement_officer_headers(shared_uw))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    def test_state_precedence_on_confirmed_disbursement_is_409(self, api):
        """PRD 2.6: "If the target resource is not in a state from which the
        requested transition is defined, the request is rejected with
        ERR_INVALID_STATE (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_before_segregation_on_disbursement_send
        """
        shared_uw = "uw-shared-sb2"
        bundle = setup_funded_loan(
            underwriter_id=shared_uw,
            officer_id="do-sb-6",
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-P5B", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        loan = bundle["loan"]
        disb = schedule_disbursement(loan, "do-sb-6", prior_servicer_name="Old Servicer",
                                     payoff_amount_cents=3_000_000)
        send_disbursement(disb["id"], "do-sb-6")
        confirm_disbursement(disb["id"], "do-sb-6")
        resp = api.send_disbursement(disb["id"], make_disbursement_officer_headers(shared_uw))
        assert resp.status_code == 409, f"expected HTTP 409, got {resp.status_code}"


class TestNotFoundBeforeDti:
    def test_approve_nonexistent_application_returns_not_found(self, api):
        """PRD 2.6: "then existence of every referenced resource (ERR_NOT_FOUND),
        then that the target is in a legal source state for the transition"
        PRD 2.5: "the first reference that fails to resolve yields ERR_NOT_FOUND
        (HTTP 404)."

        Approving a non-existent application id returns ERR_NOT_FOUND, never the
        fiscal ERR_DTI_EXCEEDED.

        Design: Difficulty/priority_pair_validation_conflict/not_found_before_dti_on_approve
        """
        resp = api.approve_application(NON_EXISTENT_UUID, make_underwriter_headers("uw-nf-9"))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)

    def test_approve_nonexistent_application_status_is_404(self, api):
        """PRD 2.5: "When a request names a resource through a path identifier or
        through a foreign-key field in the body, each referenced resource must
        resolve to an existing record, checked in order of appearance; the first
        reference that fails to resolve yields ERR_NOT_FOUND (HTTP 404)."

        Design: Difficulty/priority_pair_validation_conflict/not_found_before_dti_on_approve
        """
        resp = api.approve_application(NON_EXISTENT_UUID, make_underwriter_headers("uw-nf-10"))
        assert resp.status_code == 404, f"expected HTTP 404, got {resp.status_code}"


class TestOnTimeGraceBoundary:
    def test_paid_exactly_at_grace_boundary_is_on_time_and_increments_streak(self, api):
        """PRD 3.9: "A payment is on time if and only if its paid_at is at or before
        its due_date plus a grace window of 5 days; a payment whose paid_at falls
        exactly on the due date plus 5 days is on time, while one second past that
        boundary is late."
        PRD 3.9: "When the payment is on time and the loan's repayment_status is
        CURRENT, and a CONSENTED cosigner exists, that cosigner's on_time_streak is
        incremented by 1."

        due_date 2026-07-01, paid_at 2026-07-06 (exactly +5 days) -> on_time true,
        streak 0 -> 1.

        Design: Difficulty/boundary_precision_check/on_time_grace_boundary_exact_vs_one_second
        """
        set_clock("2026-07-06T00:00:00Z")
        bundle = setup_funded_loan(
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-P6", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
            with_cosigner=True,
        )
        loan = bundle["loan"]
        cosigner = bundle["cosigner"]
        from test_helpers import post_payment
        payment = post_payment(loan, 50_000, "2026-07-01T00:00:00Z", paid_at="2026-07-06T00:00:00Z")
        assert payment["on_time"] is True, (
            f"paid_at exactly due_date+5 days must be on_time, got {payment['on_time']}"
        )
        cosigner_after = get_cosigner(cosigner["id"])
        assert cosigner_after["on_time_streak"] == 1, (
            f"streak should be 1 after the exact-boundary on-time payment, got {cosigner_after['on_time_streak']}"
        )

    def test_paid_one_second_past_boundary_is_late_and_resets_streak(self, api):
        """PRD 3.9: "a payment whose paid_at falls exactly on the due date plus 5
        days is on time, while one second past that boundary is late."
        PRD 3.9: "A late payment, or any payment posted while the loan is not
        CURRENT, resets the on_time_streak to 0."

        due_date 2026-07-01, paid_at 2026-07-06T00:00:01 (one second past +5 days)
        -> on_time false, streak resets to 0.

        Design: Difficulty/boundary_precision_check/on_time_grace_boundary_exact_vs_one_second
        """
        set_clock("2026-07-06T00:00:01Z")
        bundle = setup_funded_loan(
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-P6C", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
            with_cosigner=True,
        )
        loan = bundle["loan"]
        cosigner = bundle["cosigner"]
        from test_helpers import post_payment
        payment = post_payment(loan, 50_000, "2026-07-01T00:00:00Z", paid_at="2026-07-06T00:00:01Z")
        assert payment["on_time"] is False, (
            f"paid_at one second past due_date+5 days must be late, got {payment['on_time']}"
        )
        cosigner_after = get_cosigner(cosigner["id"])
        assert cosigner_after["on_time_streak"] == 0, (
            f"streak should reset to 0 on a late payment, got {cosigner_after['on_time_streak']}"
        )


class TestPayoffExceedsPrincipalBoundary:
    def test_payoff_sum_one_cent_over_principal_rejected(self, api):
        """PRD 3.8: "The sum of payoff_amount_cents across all disbursements
        scheduled against a loan must not exceed that loan's
        original_principal_cents; a scheduling request that would push the running
        total past the original principal is rejected with
        ERR_PAYOFF_EXCEEDS_PRINCIPAL (HTTP 422)."

        original 5,000,000; first disbursement 3,000,000; a second of 2,000,001
        pushes the total to 5,000,001 > 5,000,000 -> rejected.

        Design: Difficulty/boundary_precision_check/payoff_exceeds_principal_empty_vs_at_limit
        """
        bundle = setup_funded_loan(
            autopay_elected=True,
            officer_id="do-p6b",
            pool_overrides={"pool_code": "POOL-P6B", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        loan = bundle["loan"]
        schedule_disbursement(loan, "do-p6b", prior_servicer_name="Servicer A",
                              payoff_amount_cents=3_000_000)
        from test_helpers import create_disbursement_payload
        resp = api.create_disbursement(
            create_disbursement_payload(loan["id"], prior_servicer_name="Servicer B",
                                        payoff_amount_cents=2_000_001),
            make_disbursement_officer_headers("do-p6b"))
        validate_error(resp, ApiErrorId.ERR_PAYOFF_EXCEEDS_PRINCIPAL.value, 422)

    def test_payoff_sum_exactly_at_principal_succeeds(self, api):
        """PRD 3.8: "The sum of payoff_amount_cents across all disbursements
        scheduled against a loan must not exceed that loan's
        original_principal_cents"

        original 5,000,000; first 3,000,000; a second of exactly 2,000,000 brings
        the total to 5,000,000 (at the limit) and is accepted.

        Design: Difficulty/boundary_precision_check/payoff_exceeds_principal_empty_vs_at_limit
        """
        bundle = setup_funded_loan(
            autopay_elected=True,
            officer_id="do-p6c",
            pool_overrides={"pool_code": "POOL-P6D", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        loan = bundle["loan"]
        schedule_disbursement(loan, "do-p6c", prior_servicer_name="Servicer A",
                              payoff_amount_cents=3_000_000)
        second = schedule_disbursement(loan, "do-p6c", prior_servicer_name="Servicer B",
                                       payoff_amount_cents=2_000_000)
        assert second["status"] == "SCHEDULED", (
            f"a disbursement summing exactly to original principal must be accepted, got {second['status']}"
        )
        assert second["payoff_amount_cents"] == 2_000_000
