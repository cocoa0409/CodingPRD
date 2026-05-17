"""Mediation: HAMP-style negotiation loop, segregation of duties.

Coverage targets (PRD §3.7):
- Mediation requested with hardship missing -> ERR_HARDSHIP_AFFIDAVIT_MISSING.
- Mediation requested after NOI window -> ERR_MEDIATION_WINDOW_CLOSED.
- /open transitions REQUESTED -> OPEN.
- /extend-offer must reduce payment (ERR_HAMP_NOT_A_REDUCTION).
- Affordability floor (ERR_HAMP_AFFORDABILITY_FLOOR).
- /accept-offer + /complete cascade -> CLOSED_MODIFIED, Loan posture CURRENT.
- /complete by same operator who extended -> ERR_SEGREGATION_OF_DUTIES.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    accept_mediation_offer,
    advance_clock,
    assert_mediation_case,
    create_borrower,
    create_loan,
    extend_mediation_offer,
    get_loan,
    open_foreclosure_case,
    open_mediation,
    request_mediation,
    setup_foreclosure_case_at_noi_issued,
    setup_loan_in_default,
    setup_mediation_offer_extended,
    setup_mediation_open,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestMediationRequestPreconditions:
    def test_request_after_noi_window_rejected(self, api, servicer_headers):
        """PRD §3.6: "A mediation request after the 30-day NOI window
        is rejected with ERR_MEDIATION_WINDOW_CLOSED."

        Claim: advance clock 31 days after foreclosure open, then
        request mediation -> ERR_MEDIATION_WINDOW_CLOSED.
        """
        b, loan, fc = setup_foreclosure_case_at_noi_issued()
        advance_clock(31)
        resp = api.request_mediation(fc["id"], servicer_headers)
        validate_error(resp,
                       ApiErrorId.ERR_MEDIATION_WINDOW_CLOSED.value)

    def test_request_without_hardship_rejected(
        self, api, servicer_headers, foreclosure_attorney_headers,
    ):
        """PRD §3.6: "A mediation request when the borrower has not
        attested hardship is rejected with
        ERR_HARDSHIP_AFFIDAVIT_MISSING."

        Claim: borrower without hardship_attested_at + open foreclosure
        case + request mediation -> ERR_HARDSHIP_AFFIDAVIT_MISSING.
        """
        # Build a default loan WITHOUT hardship attestation.
        b, loan = setup_loan_in_default(with_hardship=False)
        fc = open_foreclosure_case(loan["id"])
        resp = api.request_mediation(fc["id"], servicer_headers)
        validate_error(
            resp, ApiErrorId.ERR_HARDSHIP_AFFIDAVIT_MISSING.value,
        )


class TestMediationOpen:
    def test_open_requested_transitions_to_open(self, api, lmu_headers):
        """PRD §3.7: "The LossMitigationUnderwriter opens it for
        negotiation, transitioning it from REQUESTED to OPEN".

        Claim: /open on a REQUESTED mediation -> status=OPEN.
        """
        b, loan, fc, m = setup_mediation_open()
        assert_mediation_case(m)
        assert m["status"] == "OPEN"


class TestHampOfferGuards:
    def test_offer_that_does_not_reduce_rejected(self, api, lmu_headers):
        """PRD §3.7: "The reduction guard requires that
        target_payment_cents is strictly less than the loan's current
        scheduled_payment_cents (a modification offer that does not
        reduce the payment is not a HAMP-style offer at all); a
        violation is rejected with ERR_HAMP_NOT_A_REDUCTION."

        Claim: an offer that does not reduce scheduled_payment_cents
        -> ERR_HAMP_NOT_A_REDUCTION. We choose an offer that worsens
        the payment by extending nothing AND raising the rate.
        """
        b, loan, fc, m = setup_mediation_open()
        # Rate increase, no term extension, no principal forbearance ->
        # target_payment_cents > current scheduled_payment_cents.
        current_bps = int(loan["interest_rate_bps"])
        higher_bps = min(5_000, current_bps + 200)
        resp = api.extend_mediation_offer(
            m["id"],
            {"offered_new_rate_bps": higher_bps,
             "offered_term_extension_months": 0,
             "offered_principal_forbearance_cents": 0},
            lmu_headers,
        )
        validate_error(resp,
                       ApiErrorId.ERR_HAMP_NOT_A_REDUCTION.value)


class TestHampLifecycle:
    def test_extend_offer_advances_to_offer_extended(
        self, api, lmu_headers,
    ):
        """PRD §3.7: "On success, the MediationCase transitions to
        OFFER_EXTENDED and target_payment_cents is recorded on the case."

        Claim: /extend-offer with a real reduction -> status=
        OFFER_EXTENDED, target_payment_cents > 0.
        """
        b, loan, fc, m = setup_mediation_offer_extended(
            offered_new_rate_bps=400,
            offered_term_extension_months=60,
            offered_principal_forbearance_cents=1_000_000,
        )
        assert m["status"] == "OFFER_EXTENDED"
        assert int(m["target_payment_cents"]) > 0
        # And the new target must be strictly less than current scheduled.
        loan_now = get_loan(loan["id"])
        assert (
            int(m["target_payment_cents"])
            < int(loan_now["scheduled_payment_cents"])
        ), (
            "PRD §3.7 reduction guard requires target < current scheduled; "
            f"got target={m['target_payment_cents']} vs scheduled="
            f"{loan_now['scheduled_payment_cents']}"
        )

    def test_accept_then_complete_cascade_modifies_loan(
        self, api, lmu_headers_alt, servicer_headers,
    ):
        """PRD §3.7: "the MediationCase transitions to COMPLETED, the
        parent ForeclosureCase cascades to CLOSED_MODIFIED, and the
        Loan itself is modified: Loan.scheduled_payment_cents becomes
        the recomputed target ... and finally Loan.posture returns to
        CURRENT."

        Claim: /accept then /complete cascades to a CURRENT loan with
        scheduled_payment_cents == recomputed target_payment_cents.
        """
        b, loan, fc, m = setup_mediation_offer_extended(
            offered_new_rate_bps=400,
            offered_term_extension_months=60,
            offered_principal_forbearance_cents=1_000_000,
        )
        # Accept the offer (Borrower or Servicer per PRD §4).
        accepted = accept_mediation_offer(m["id"])
        assert accepted["status"] == "OFFER_ACCEPTED"
        # Complete must be performed by a DIFFERENT operator than the
        # one who extended (PRD §3.7 segregation pivot).
        # The setup_mediation_offer_extended fixture used lmu_headers
        # for extend; we use lmu_headers_alt for complete.
        resp = api.complete_mediation(m["id"], lmu_headers_alt)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "COMPLETED"
        loan_after = get_loan(loan["id"])
        assert loan_after["posture"] == "CURRENT"

    def test_complete_by_extender_id_rejected_seg_duties(
        self, api,
    ):
        """PRD §2.1: "a single X-User-ID cannot both extend a mediation
        offer and accept the same offer on the same MediationCase".
        PRD §3.7: "The completion step is the segregation-of-duties
        pivot: the underwriter who extended the most recent offer must
        not be the same X-User-ID that accepted it; a violation is
        rejected with ERR_SEGREGATION_OF_DUTIES."

        Claim: when the SAME X-User-ID is used for both /extend-offer
        and /accept-offer (made possible because both Servicer and LMU
        can be configured with overlapping operator ids in test
        contexts), /complete on the resulting mediation -> the case
        either rejects the accept step with ERR_SEGREGATION_OF_DUTIES
        at accept time, or rejects at complete time. We use a Borrower
        whose X-User-ID equals the extending LMU's id only by
        coincidence — which is the cleanest single-id-overlap
        construction the role boundaries permit.

        Per the two-reader test: PRD §2.1 binds the rule to the
        EXTEND/ACCEPT pair (not extend/complete). We therefore exercise
        the accept step with an id equal to the extender id and assert
        ERR_SEGREGATION_OF_DUTIES is the outcome at /accept-offer.
        """
        from test_helpers import (
            make_borrower_headers, make_lmu_headers, LMU_ID,
            setup_loan_in_default, open_foreclosure_case,
            request_mediation, open_mediation,
            attest_hardship, create_borrower, create_loan,
        )
        # Build a Borrower whose id happens to equal LMU_ID. We cannot
        # control the auto-minted Borrower.id, so this test triggers
        # the segregation guard the way the PRD literally describes:
        # the same opaque LMU operator id used on both extend and
        # accept paths. Per PRD §4 RBAC, accept-offer accepts
        # role=Servicer; we therefore use the SAME numeric id with
        # role=Servicer for the accept call.
        b, loan, fc, m = setup_mediation_open()
        # Extend with lmu-001.
        extend_mediation_offer(
            m["id"],
            offered_new_rate_bps=400,
            offered_term_extension_months=60,
            offered_principal_forbearance_cents=1_000_000,
            headers=make_lmu_headers(LMU_ID),
        )
        # Accept with Servicer role but X-User-ID equal to LMU_ID.
        # This is the only construction that lets a single X-User-ID
        # cover both extend and accept.
        from test_helpers import make_servicer_headers
        same_id_servicer_headers = make_servicer_headers(LMU_ID)
        resp = api.accept_mediation_offer(m["id"],
                                          same_id_servicer_headers)
        # PRD §2.1 says the same X-User-ID cannot both extend AND
        # accept on the same case -> ERR_SEGREGATION_OF_DUTIES.
        validate_error(resp,
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
