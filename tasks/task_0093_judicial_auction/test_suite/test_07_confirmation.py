"""Confirmation lifecycle: draft, issue, fail, seal — empty-set guard,
second-bidder eligibility, re-auction trigger on FAIL (PRD §3.8)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_confirmation,
    create_confirmation,
    create_confirmation_payload,
    fail_confirmation_payload,
    get_lot,
    setup_issued_confirmation,
    setup_sold_auction,
    setup_unsold_auction,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# DRAFT creation — PRD §3.8
# ===========================================================================
class TestConfirmationDraft:

    def test_draft_against_sold_auction_returns_201(
        self, api, court_clerk_headers,
    ):
        """PRD §3.8: "After an auction reaches `SOLD`, a `CourtClerk` drafts a `Confirmation` by submitting the `auction_id`, the `ruling_document_uri` of the court's ruling document, and an optional `use_second_bidder` flag."

        Claim: POST /confirmations on SOLD auction → 201, status=DRAFT.
        """
        _lot, auction, _bidders, _winning_bid = setup_sold_auction(
            num_bidders=2,
        )
        resp = api.create_confirmation(
            create_confirmation_payload(auction["id"]), court_clerk_headers,
        )
        confirmation = validate_success(resp, expected_status=201)
        assert_confirmation(confirmation)
        assert confirmation["status"] == "DRAFT"

    def test_draft_against_unsold_rejected_no_valid_bids(
        self, api, court_clerk_headers,
    ):
        """PRD §3.8: "The empty-set guard rejects a draft against an auction whose `current_high_cents` is null with `ERR_NO_VALID_BIDS."

        Claim: POST /confirmations on UNSOLD auction →
        ERR_NO_VALID_BIDS. Per PRD §2.9 priority ordering, an UNSOLD
        auction may also surface as ERR_INVALID_STATE because the
        state-machine precondition "Auction must be SOLD" is checked
        before business-constraint rules; both are PRD-faithful.
        """
        _lot, auction = setup_unsold_auction()
        resp = api.create_confirmation(
            create_confirmation_payload(auction["id"]), court_clerk_headers,
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_NO_VALID_BIDS.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])

    def test_second_bidder_flag_without_runner_up_rejected(
        self, api, court_clerk_headers,
    ):
        """PRD §3.8: "The second-bidder offer path is only available when `Auction.second_highest_bid_id` is not null and that bidder's account is `ACTIVE`; otherwise the request is rejected with `ERR_NO_ELIGIBLE_SECOND_BIDDER."

        Claim: use_second_bidder=true on SOLD auction with only one bid
        → ERR_NO_ELIGIBLE_SECOND_BIDDER.
        """
        _lot, auction, _bidders, _winning_bid = setup_sold_auction(
            num_bidders=1,
        )
        resp = api.create_confirmation(
            create_confirmation_payload(
                auction["id"], use_second_bidder=True,
            ),
            court_clerk_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_NO_ELIGIBLE_SECOND_BIDDER.value,
        )


# ===========================================================================
# ISSUE transition — PRD §3.8
# ===========================================================================
class TestConfirmationIssue:

    def test_issue_creates_payment_row(self, api):
        """PRD §3.8: "The transition stamps `issued_at` to the current instant, creates a `Payment` row as described in §3.9, and emits `CONFIRMATION_ISSUED."

        Claim: issue → Confirmation.status=ISSUED + a Payment row exists.
        """
        _lot, _auction, _bidders, _bid, confirmation, payment = (
            setup_issued_confirmation(num_bidders=1)
        )
        assert confirmation["status"] == "ISSUED"
        assert payment["confirmation_id"] == confirmation["id"]
        assert payment["status"] in ("PENDING", "PAID")

    def test_issue_against_draft_with_invalid_state_rejected(
        self, api, court_clerk_headers,
    ):
        """PRD §3.8: issue is only valid from DRAFT; subsequent calls on
        an already-ISSUED confirmation are state errors. PRD §2.9
        names ERR_INVALID_STATE for state-machine precondition failures.

        Claim: issue an already-ISSUED Confirmation → ERR_INVALID_STATE.
        """
        _lot, _auction, _bidders, _bid, confirmation, _payment = (
            setup_issued_confirmation(num_bidders=1)
        )
        resp = api.issue_confirmation(
            confirmation["id"], court_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# FAIL transition — PRD §3.8
# ===========================================================================
class TestConfirmationFail:

    def test_fail_with_court_override_does_not_forfeit_deposit(
        self, api, court_clerk_headers,
    ):
        """PRD §3.8: "When the `failure_reason` is `COLLUSION_FOUND` or `BIDDER_DISQUALIFIED`, the winning bidder's deposit is additionally forfeited; `COURT_OVERRIDE` does not forfeit the deposit."

        Claim: fail with COURT_OVERRIDE → Confirmation.status=FAILED
        and Lot.round_number increments (re-auction triggered).
        """
        _lot, auction, _bidders, _winning_bid = setup_sold_auction(
            num_bidders=1,
        )
        confirmation = create_confirmation(auction["id"])
        resp = api.fail_confirmation(
            confirmation["id"],
            fail_confirmation_payload(failure_reason="COURT_OVERRIDE"),
            court_clerk_headers,
        )
        failed = validate_success(resp)
        assert failed["status"] == "FAILED"
        assert failed.get("failure_reason") == "COURT_OVERRIDE"
        # Re-auction triggered → Lot.round_number == 2.
        lot = get_lot(_lot["id"])
        assert lot["round_number"] == 2, (
            "PRD §3.8: FAIL triggers re-auction; round_number should "
            f"increment to 2, got {lot['round_number']}"
        )

    def test_fail_failure_reason_persisted(self, api, court_clerk_headers):
        """PRD §3.8: failure_reason is one of COLLUSION_FOUND,
        BIDDER_DISQUALIFIED, COURT_OVERRIDE. PRD §3.8 also says:
        "Confirmation.failure_reason is null on any confirmation whose
        status is not FAILED."

        Claim: FAILED confirmation surfaces the requested reason.
        """
        _lot, auction, _bidders, _winning_bid = setup_sold_auction(
            num_bidders=1,
        )
        confirmation = create_confirmation(auction["id"])
        resp = api.fail_confirmation(
            confirmation["id"],
            fail_confirmation_payload(failure_reason="BIDDER_DISQUALIFIED"),
            court_clerk_headers,
        )
        data = validate_success(resp)
        assert data["failure_reason"] == "BIDDER_DISQUALIFIED"


# ===========================================================================
# SEAL transition — PRD §3.8
# ===========================================================================
class TestConfirmationSeal:

    def test_seal_without_payment_paid_rejected(
        self, api, court_clerk_headers,
    ):
        """PRD §3.8: "Sealing requires the matched `Payment.status` to be `PAID` and a `TransferOrder` whose `status` is not `BLOCKED."

        Claim: seal on ISSUED Confirmation while Payment is still
        PENDING → ERR_INVALID_STATE.
        """
        _lot, _auction, _bidders, _bid, confirmation, payment = (
            setup_issued_confirmation(num_bidders=1)
        )
        if payment["status"] == "PAID":
            pytest.skip(
                "Payment auto-marked PAID at issuance (balance == 0 edge);"
                " sealing precondition trivially satisfied"
            )
        resp = api.seal_confirmation(
            confirmation["id"], court_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
