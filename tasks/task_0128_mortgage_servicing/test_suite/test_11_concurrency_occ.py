"""Optimistic concurrency control and named race conditions.

Coverage targets (PRD §2.5):
- When `version` is supplied and matches Loan.version, mutation succeeds.
- When `version` is supplied and mismatches -> ERR_CONCURRENT_UPDATE / 409.
- Two concurrent ForeclosureCase opens on the same loan -> exactly one
  succeeds; the loser receives ERR_FORECLOSURE_CASE_EXISTS / 409.
- Concurrent extend-offer on an already OFFER_ACCEPTED case ->
  ERR_INVALID_STATE / 409.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_exactly_one_succeeds,
    get_loan,
    open_mediation,
    post_payment,
    request_mediation,
    run_race,
    setup_borrower_and_current_loan,
    setup_foreclosure_case_at_noi_issued,
    setup_loan_in_default,
    setup_mediation_offer_extended,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestOptimisticConcurrency:
    def test_payment_with_wrong_version_rejected(self, api, servicer_headers):
        """PRD §2.5: "When the caller supplies version, the server
        compares it against the persisted version on the target
        resource at commit time; a mismatch is rejected with
        ERR_CONCURRENT_UPDATE and HTTP 409."

        Claim: POST /payments with body version=999 (mismatch) ->
        ERR_CONCURRENT_UPDATE / 409.
        """
        b, loan = setup_borrower_and_current_loan()
        advance_clock(30)
        resp = api.create_payment(
            loan["id"],
            {"received_date": "2026-05-17T00:00:00.000Z",
             "amount_cents": int(loan["scheduled_payment_cents"]),
             "version": 999},
            servicer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CONCURRENT_UPDATE.value)

    def test_payment_with_correct_version_succeeds(
        self, api, servicer_headers,
    ):
        """PRD §2.5: "When the caller omits version, the optimistic
        check is skipped and the request applies last-writer-wins."
        PRD §2.5: "When the caller supplies version, the server
        compares it against the persisted version on the target
        resource at commit time".

        Claim: supplying the current Loan.version satisfies the OCC
        check and the request succeeds.
        """
        b, loan = setup_borrower_and_current_loan()
        advance_clock(30)
        loan_now = get_loan(loan["id"])
        resp = api.create_payment(
            loan["id"],
            {"received_date": "2026-05-17T00:00:00.000Z",
             "amount_cents": int(loan_now["scheduled_payment_cents"]),
             "version": int(loan_now["version"])},
            servicer_headers,
        )
        assert resp.status_code in (200, 201), (
            f"correct version must succeed; got {resp.status_code}"
        )


class TestForeclosureCaseRace:
    def test_two_open_attempts_at_most_one_succeeds(
        self, api, foreclosure_attorney_headers,
    ):
        """PRD §2.5: "When two ForeclosureAttorney operators try to
        open a ForeclosureCase on the same Loan simultaneously, the
        second attempt is rejected with ERR_FORECLOSURE_CASE_EXISTS
        and HTTP 409."

        Claim: two concurrent POST /foreclosure-cases on the same loan
        -> exactly one 2xx and one 409 with
        ERR_FORECLOSURE_CASE_EXISTS.
        """
        b, loan = setup_loan_in_default(with_hardship=False)
        # Two concurrent open attempts.
        results = run_race(
            lambda: api.create_foreclosure_case(
                {"loan_id": loan["id"]},
                foreclosure_attorney_headers,
            ),
            lambda: api.create_foreclosure_case(
                {"loan_id": loan["id"]},
                foreclosure_attorney_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        # PRD §2.5 names the loser error_id explicitly.
        validate_error(loser, ApiErrorId.ERR_FORECLOSURE_CASE_EXISTS.value)


class TestMediationExtendAfterAcceptedRace:
    def test_extend_offer_on_accepted_mediation_rejected(
        self, api, lmu_headers,
    ):
        """PRD §2.5: "When extending an offer races with completing a
        different already-accepted offer on the same MediationCase,
        the second extend is rejected with ERR_INVALID_STATE and HTTP
        409."

        Claim: sequential — accept first, then attempt /extend-offer
        on the same case -> ERR_INVALID_STATE.
        """
        from test_helpers import accept_mediation_offer
        b, loan, fc, m = setup_mediation_offer_extended()
        accept_mediation_offer(m["id"])
        # Now extending again -> ERR_INVALID_STATE.
        resp = api.extend_mediation_offer(
            m["id"],
            {"offered_new_rate_bps": 300,
             "offered_term_extension_months": 12,
             "offered_principal_forbearance_cents": 100_000},
            lmu_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
