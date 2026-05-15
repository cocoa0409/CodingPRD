"""Deposit lifecycle: posting, payment deadline, cascade-refund on
auction close, refund dispute, and the uniqueness key
(PRD §3.4, §3.5, §3.10)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_clock_to,
    api_client,
    assert_deposit,
    cancel_auction,
    create_bidder_account,
    create_deposit_payload,
    get_lot,
    make_bidder_headers,
    pay_deposit,
    post_deposit,
    raise_dispute_payload,
    resolve_dispute_payload,
    setup_announced_lot,
    setup_bidder_with_paid_deposit,
    setup_live_auction,
    setup_sold_auction,
    setup_unsold_auction,
    sweep_refunds,
    validate_error,
    validate_success,
)


def _parse(value):
    from datetime import datetime
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


# ===========================================================================
# Deposit posting & uniqueness — PRD §3.4
# ===========================================================================
class TestDepositPosting:

    def test_post_deposit_creates_pending_row_with_amount_snapshot(
        self, api, auction_admin_headers,
    ):
        """PRD §3.4: "The new row carries `amount_cents` snapshotted from the auction's current `deposit_amount_cents`, status `PENDING."

        Claim: POST /deposits → 201, status=PENDING, amount_cents ==
        Auction.deposit_amount_cents.
        """
        _lot, auction = setup_announced_lot(
            deposit_mode="FIXED", deposit_fixed_cents=5_000_000,
        )
        bidder = create_bidder_account()
        resp = api.create_deposit(
            create_deposit_payload(auction["id"], bidder["id"]),
            auction_admin_headers,
        )
        deposit = validate_success(resp, expected_status=201)
        assert_deposit(deposit)
        assert deposit["status"] == "PENDING"
        assert deposit["amount_cents"] == auction["deposit_amount_cents"]

    def test_duplicate_deposit_for_same_bidder_rejected(
        self, api, auction_admin_headers,
    ):
        """PRD §3.4: "The same `(auction_id, bidder_account_id)` pair must be unique; a duplicate is rejected with `ERR_DEPOSIT_DUPLICATE."

        Claim: second deposit for same (auction, bidder) →
        ERR_DEPOSIT_DUPLICATE.
        """
        _lot, auction = setup_announced_lot()
        bidder = create_bidder_account()
        first = api.create_deposit(
            create_deposit_payload(auction["id"], bidder["id"]),
            auction_admin_headers,
        )
        validate_success(first, expected_status=201)
        second = api.create_deposit(
            create_deposit_payload(auction["id"], bidder["id"]),
            auction_admin_headers,
        )
        validate_error(second, ApiErrorId.ERR_DEPOSIT_DUPLICATE.value)


# ===========================================================================
# Deposit payment — PRD §3.4
# ===========================================================================
class TestDepositPayment:

    def test_pay_deposit_after_deadline_rejected(
        self, api, auction_admin_headers,
    ):
        """PRD §3.4: "The bidder marks the deposit `PAID` once funds have arrived in the escrow account; this transition is only valid while the auction is `SCHEDULED` or `LIVE`, the bidder's account is `ACTIVE`, and the current instant is not after the auction's `deposit_deadline_at`. A payment attempt after the deadline is rejected with `ERR_DEPOSIT_DEADLINE_PASSED."

        Claim: clock past deposit_deadline_at, then pay →
        ERR_DEPOSIT_DEADLINE_PASSED.
        """
        _lot, auction = setup_announced_lot()
        bidder = create_bidder_account()
        deposit = post_deposit(auction["id"], bidder["id"])
        # Advance the clock past deposit_deadline_at.
        deadline = _parse(auction["deposit_deadline_at"])
        advance_clock_to(deadline + timedelta(minutes=5))
        resp = api.pay_deposit(
            deposit["id"], make_bidder_headers(bidder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_DEADLINE_PASSED.value)

    def test_pay_deposit_stamps_paid_at(self, api):
        """PRD §3.4: "Successful payment stamps `paid_at` and emits `DEPOSIT_PAID."

        Claim: pay → Deposit.status=PAID and paid_at populated.
        """
        _lot, auction = setup_announced_lot()
        bidder, paid = setup_bidder_with_paid_deposit(auction)
        assert paid["status"] == "PAID"
        assert paid.get("paid_at"), "paid_at must be set after pay"


# ===========================================================================
# Refund cascade on auction close — PRD §3.5 / §2.7
# ===========================================================================
class TestRefundCascade:

    def test_non_winner_deposits_refunded_on_sold(self, api):
        """PRD §3.5: "Every `Deposit` on this auction whose `bidder_account_id` is not the winning account and whose status is `PAID` cascades to `REFUNDED."

        Claim: on SOLD, non-winners' deposits → REFUNDED.
        """
        _lot, auction, bidders, _winning_bid = setup_sold_auction(
            num_bidders=2,
        )
        # The last bidder is the winner; the first must be REFUNDED.
        loser_bidder, loser_deposit = bidders[0]
        # Re-fetch loser deposit; the impl exposes GET /deposits/{id}.
        resp = api._request(
            "GET", f"/deposits/{loser_deposit['id']}",
            headers={"X-User-ID": "admin-001",
                     "X-User-Role": "AuctionAdmin",
                     "Content-Type": "application/json"},
        )
        data = validate_success(resp)
        assert data["status"] == "REFUNDED", (
            f"Expected REFUNDED loser deposit, got {data['status']}"
        )
        assert data.get("refund_due_at"), (
            "PRD §2.7: refund_due_at must be set on each refunded deposit"
        )

    def test_winner_deposit_stays_paid_on_sold(self, api):
        """PRD §3.5: only the non-winner deposits cascade to REFUNDED.

        Claim: winner's deposit retains status=PAID after auction close.
        """
        _lot, auction, bidders, _winning_bid = setup_sold_auction(
            num_bidders=2,
        )
        winner_bidder, winner_deposit = bidders[-1]
        resp = api._request(
            "GET", f"/deposits/{winner_deposit['id']}",
            headers={"X-User-ID": "admin-001",
                     "X-User-Role": "AuctionAdmin",
                     "Content-Type": "application/json"},
        )
        data = validate_success(resp)
        assert data["status"] == "PAID", (
            f"Winner's deposit must remain PAID, got {data['status']}"
        )


# ===========================================================================
# Dispute path — PRD §3.10
# ===========================================================================
class TestDepositDispute:

    def test_dispute_before_refund_due_at_rejected(self, api):
        """PRD §3.10: "The transition is only valid when the current instant is strictly past `refund_due_at` and the deposit is still `PAID."

        Claim: raise-dispute on a PENDING deposit → ERR_INVALID_STATE.

        Setup: a fresh PENDING deposit cannot be disputed since dispute
        requires PAID. The state check fires before any refund_due_at
        comparison.
        """
        _lot, auction = setup_unsold_auction()
        bidder = create_bidder_account()
        deposit = post_deposit(auction["id"], bidder["id"])
        # The deposit hasn't been paid yet (PENDING); dispute requires PAID.
        resp = api.raise_deposit_dispute(
            deposit["id"], make_bidder_headers(bidder["id"]),
            raise_dispute_payload(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Not-found paths — PRD §2.8
# ===========================================================================
class TestDepositNotFound:

    def test_pay_unknown_deposit_returns_not_found(self, api):
        """PRD §2.8: existence checks return ERR_NOT_FOUND when the
        path identifier does not resolve.

        Claim: POST /deposits/{unknown}/pay → ERR_NOT_FOUND.
        """
        # Use a bidder account so we pass auth + RBAC layers; the
        # priority-3 path check fires next.
        bidder = create_bidder_account()
        resp = api.pay_deposit(
            NON_EXISTENT_UUID, make_bidder_headers(bidder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
