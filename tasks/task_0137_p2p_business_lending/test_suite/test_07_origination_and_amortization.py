"""Origination, amortization schedule, and disbursement.

PRD §3.4.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    assert_amortization_principal_invariant,
    assert_loan,
    create_listing,
    find_disclosure,
    get_investment,
    get_investor,
    get_listing,
    list_installments,
    originate_listing,
    setup_funded_listing,
    setup_open_listing,
    setup_originated_loan,
    suspend_borrower,
    validate_error,
)


# ===========================================================================
# Origination requires APPROVED borrower — PRD §3.4
# ===========================================================================
class TestOriginationGates:

    def test_originate_rejected_if_borrower_suspended_after_fund(
        self, api, platform_operator_headers,
    ):
        """PRD §3.4: "Origination is also rejected if the underlying
        borrower is not in APPROVED status (ERR_BORROWER_NOT_APPROVED)".

        Claim: a FUNDED listing whose borrower is later suspended
        rejects originate with ERR_BORROWER_NOT_APPROVED.
        """
        (platform, officer, b, investor, listing,
         investment) = setup_funded_listing(principal_cents=100_000)
        assert listing["status"] == "FUNDED"
        # Suspend borrower BEFORE originate.
        suspend_borrower(platform["id"], b["id"], officer["id"])
        resp = api.originate_listing(
            platform["id"], listing["id"], platform_operator_headers,
        )
        validate_error(resp, "ERR_BORROWER_NOT_APPROVED")


# ===========================================================================
# Origination side effects — PRD §3.4
# ===========================================================================
class TestOriginationSideEffects:

    def test_originate_creates_active_loan(self, api):
        """PRD §3.4: "A new Loan is created ... the loan's status is
        set to ACTIVE".

        Claim: after originate, the resulting Loan has status ==
        'ACTIVE'.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(principal_cents=100_000)
        assert_loan(loan)
        assert loan["status"] == "ACTIVE"

    def test_originate_copies_listing_terms(self, api):
        """PRD §3.4: "with principal_cents, interest_rate_bps, and
        term_months copied verbatim from the listing's locked values".

        Claim: loan.{principal_cents, interest_rate_bps, term_months}
        equal listing's locked values.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(
            principal_cents=100_000, term_months=12,
        )
        assert loan["principal_cents"] == listing["principal_cents"]
        assert loan["interest_rate_bps"] == listing["interest_rate_bps"]
        assert loan["term_months"] == listing["term_months"]

    def test_originate_converts_investments(self, api):
        """PRD §3.4: "Every Investment on the listing transitions
        COMMITTED -> CONVERTED in the same operation".

        Claim: after originate, the originating investment has status
        == 'CONVERTED' and share_bps > 0.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(principal_cents=100_000)
        refreshed_inv = get_investment(platform["id"], investment["id"])
        assert refreshed_inv["status"] == "CONVERTED"
        assert refreshed_inv["share_bps"] > 0

    def test_originate_listing_transitions_to_originated(self, api):
        """PRD §3.4: "The listing transitions FUNDED -> ORIGINATED".

        Claim: listing.status == 'ORIGINATED' after originate.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(principal_cents=100_000)
        refreshed = get_listing(platform["id"], listing["id"])
        assert refreshed["status"] == "ORIGINATED"

    def test_originate_emits_loan_originated_disclosure(self, api):
        """PRD §3.4: "a draft Disclosure with kind LOAN_ORIGINATED is
        emitted."

        Claim: a DRAFT LOAN_ORIGINATED disclosure exists for the new
        loan.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(principal_cents=100_000)
        d = find_disclosure(
            platform["id"], subject_type="LOAN",
            subject_id=loan["id"], kind="LOAN_ORIGINATED",
            published=False,
        )
        assert d is not None

    def test_originate_increments_investor_outstanding_principal(self, api):
        """PRD §3.4: "Each affected investor's outstanding_principal_cents
        is incremented by the corresponding amount_cents."

        Claim: investor.outstanding_principal_cents grows by the pledge
        amount after origination.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(principal_cents=100_000)
        refreshed = get_investor(platform["id"], investor["id"])
        assert refreshed["outstanding_principal_cents"] == 100_000


# ===========================================================================
# Amortization schedule — PRD §3.4
# ===========================================================================
class TestAmortizationSchedule:

    def test_installment_count_matches_term_months(self, api):
        """PRD §3.4: "The schedule then produces term_months Installment
        records".

        Claim: list_installments returns term_months rows.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(
            principal_cents=100_000, term_months=12,
        )
        body = list_installments(platform["id"], loan["id"])
        # `body` is data; the framework returns whatever the helper
        # returns. For list endpoints get_success_data may return the
        # payload directly; iterate accordingly.
        installments = body if isinstance(body, list) else body.get(
            "data", body,
        )
        if isinstance(installments, dict) and "data" in installments:
            installments = installments["data"]
        assert isinstance(installments, list)
        assert len(installments) == 12

    def test_installments_sequence_numbers_1_to_n(self, api):
        """PRD §3.4: "each numbered by sequence_number from 1 to n".

        Claim: sequence_numbers are exactly [1..n].
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(
            principal_cents=100_000, term_months=12,
        )
        body = list_installments(platform["id"], loan["id"])
        installments = body if isinstance(body, list) else body.get(
            "data", body,
        )
        if isinstance(installments, dict) and "data" in installments:
            installments = installments["data"]
        seqs = sorted(it["sequence_number"] for it in installments)
        assert seqs == list(range(1, 13))

    def test_installment_due_day_index_formula(self, api):
        """PRD §3.4: "each with due_day_index set to
        origination_day_index plus sequence_number multiplied by 30."

        Claim: installment[k].due_day_index == loan.origination_day_index
        + k * 30 for each k.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(
            principal_cents=100_000, term_months=12,
        )
        body = list_installments(platform["id"], loan["id"])
        installments = body if isinstance(body, list) else body.get(
            "data", body,
        )
        if isinstance(installments, dict) and "data" in installments:
            installments = installments["data"]
        origin = loan["origination_day_index"]
        for it in installments:
            assert it["due_day_index"] == origin + 30 * it[
                "sequence_number"
            ], (
                f"installment {it['sequence_number']} due_day_index "
                f"expected {origin + 30 * it['sequence_number']}, "
                f"got {it['due_day_index']}"
            )

    def test_principal_sum_equals_loan_principal_exactly(self, api):
        """PRD §3.4: "The final installment absorbs the residual cents
        so that the sum of scheduled_principal_cents across all
        installments equals principal_cents exactly."

        Claim: sum(scheduled_principal_cents) == loan.principal_cents.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(
            principal_cents=100_000, term_months=12,
        )
        body = list_installments(platform["id"], loan["id"])
        installments = body if isinstance(body, list) else body.get(
            "data", body,
        )
        if isinstance(installments, dict) and "data" in installments:
            installments = installments["data"]
        assert_amortization_principal_invariant(
            loan["monthly_payment_cents"], installments,
            loan["principal_cents"],
        )

    def test_installments_start_in_scheduled_state(self, api):
        """PRD §3.4: "Every installment starts with status SCHEDULED,
        paid_principal_cents, paid_interest_cents, and paid_fees_cents
        all initialized to zero."

        Claim: every installment of a freshly originated loan has
        status=SCHEDULED and zero paid fields.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_originated_loan(
            principal_cents=100_000, term_months=12,
        )
        body = list_installments(platform["id"], loan["id"])
        installments = body if isinstance(body, list) else body.get(
            "data", body,
        )
        if isinstance(installments, dict) and "data" in installments:
            installments = installments["data"]
        for it in installments:
            assert it["status"] == "SCHEDULED"
            assert it["paid_principal_cents"] == 0
            assert it["paid_interest_cents"] == 0
            assert it["paid_fees_cents"] == 0
