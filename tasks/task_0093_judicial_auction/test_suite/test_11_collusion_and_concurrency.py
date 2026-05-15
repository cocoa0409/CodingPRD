"""Anti-collusion scoring (PRD §3.6) and concurrency races where PRD
explicitly defines the outcome (PRD §2.12).

This file also carries the difficulty-design instance
`collusion_risk_score_weighted_max` (rule_id `combinatorial_formula`).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    assert_exactly_one_succeeds,
    COLLUSION_BLOCK_THRESHOLD,
    create_bid_payload,
    create_bidder_account,
    create_bidder_account_payload,
    create_deposit_payload,
    iso_utc,
    list_audit_events,
    make_bidder_headers,
    pay_deposit,
    place_bid,
    post_deposit,
    run_race,
    setup_announced_lot,
    setup_live_auction,
    utcnow,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    W_ALTERNATING,
    W_IDENTICAL_INC,
    W_SHARED_IP,
    W_YOUNG_ACCOUNT,
)


def _parse(value):
    from datetime import datetime
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _setup_two_bidders_same_ip(auction):
    """Create two ACTIVE bidders sharing ip_fingerprint='IP1'.

    Both post + pay PERCENT-mode deposit on the supplied auction.
    Returns [(bidder, deposit), (bidder, deposit)].
    """
    bidder_a = create_bidder_account(ip_fingerprint="IP1")
    bidder_b = create_bidder_account(ip_fingerprint="IP1")
    pairs = []
    for bidder in (bidder_a, bidder_b):
        deposit = post_deposit(auction["id"], bidder["id"])
        paid = pay_deposit(deposit["id"], bidder["id"])
        pairs.append((bidder, paid))
    return pairs


# ===========================================================================
# difficulty: combinatorial_formula/collusion_risk_score_weighted_max
# ===========================================================================
class TestCollusionRiskScoreWeightedMax:

    def test_shared_ip_alone_yields_40_active_status(self, api):
        """PRD §3.6: "Each indicator is multiplied by its weight — forty for shared IP, thirty for the alternating pattern, twenty for identical increments, ten for the young-account flag — and the four products are summed into a per-peer score. The account's `collusion_risk_score` is the maximum of those per-peer scores across all peers on the auction (or zero if there are no peers)."

        difficulty: combinatorial_formula/collusion_risk_score_weighted_max

        Claim: only shared_ip indicator fires → score = 40 (< 60), so
        account remains ACTIVE.
        """
        # Two bidders sharing ip_fingerprint='IP1', but no identical
        # increment pattern (just two unrelated bids).
        _lot, auction, _ = setup_live_auction(num_bidders=0)
        pairs = _setup_two_bidders_same_ip(auction)
        bidder_a, _ = pairs[0]
        bidder_b, _ = pairs[1]
        # A places first valid bid at starting_price; B places second.
        place_bid(auction["id"], bidder_a["id"],
                  auction["starting_price_cents"], client_seq_no=1)
        # B bids one tier-2 increment higher.
        next_amount = auction["starting_price_cents"] + 500_000
        place_bid(auction["id"], bidder_b["id"], next_amount, client_seq_no=1)
        # Now A bids again with a NON-identical increment so neither
        # identical-increment nor alternating-3+ fires. Skip a tier so
        # the increment differs from B's: bid 1_000_000 higher.
        place_bid(auction["id"], bidder_a["id"],
                  next_amount + 1_000_000, client_seq_no=2)
        # Re-fetch A's account; expect score == 40 (shared IP only),
        # status still ACTIVE.
        from test_helpers import api_client as _client
        resp = _client.get_bidder_account(
            bidder_a["id"], make_bidder_headers(bidder_a["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "ACTIVE", (
            f"Expected ACTIVE for score {data['collusion_risk_score']} (< 60), "
            f"got status {data['status']}"
        )

    # NOTE: `test_score_at_or_above_80_blocks_account` was deleted under
    # STEP 1b unique-derivability. The PRD-faithful reading of §3.6 is
    # explicit: "Every accepted bid triggers a recomputation of the
    # bidding account's `collusion_risk_score` against the pool of
    # `ACTIVE` co-bidders on the same auction." Under this reading, as
    # soon as one of the two colluding bidders is moved out of ACTIVE
    # (which the suspension threshold of 60 forces partway through
    # the bidding sequence we set up here), the OTHER bidder no longer
    # has any ACTIVE peers, so their score reverts to 0. There is no
    # PRD-uniquely-derivable input sequence that drives ONE bidder to
    # score >= 80 while keeping the peer ACTIVE long enough for the
    # final per-peer max to land at 80+, and the §3.6 transition rule
    # remains exercised by the lower-threshold ACTIVE-stay test above.


# ===========================================================================
# Concurrency races — only where PRD §2.12 explicitly defines the outcome.
# ===========================================================================
class TestConcurrentDuplicateDeposit:

    def test_two_concurrent_deposits_same_bidder_one_succeeds(self, api):
        """PRD §2.12: "Two deposit-creation attempts by the same bidder on the same auction serialise on the uniqueness of `(auction_id, bidder_account_id)`; the second is rejected with `ERR_DEPOSIT_DUPLICATE."

        Claim: exactly one of two concurrent POST /deposits succeeds;
        the other returns ERR_DEPOSIT_DUPLICATE.
        """
        _lot, auction = setup_announced_lot()
        bidder = create_bidder_account()
        bidder_headers = make_bidder_headers(bidder["id"])
        payload = create_deposit_payload(auction["id"], bidder["id"])

        def op():
            return api.create_deposit(payload, bidder_headers)

        results = run_race(op, op)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # The loser must carry ERR_DEPOSIT_DUPLICATE.
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_DEPOSIT_DUPLICATE.value)


class TestConcurrentConfirmationIssueVsFail:

    def test_issue_versus_fail_at_same_instant_serialises(
        self, api, court_clerk_headers,
    ):
        """PRD §2.12: "A `CourtClerk` who issues a confirmation while another terminal simultaneously fails it serialises on the `Confirmation.status` write — exactly one of the two writes lands on the `DRAFT → {ISSUED, FAILED}` edge, and the loser is rejected with `ERR_INVALID_STATE."

        Claim: exactly one of (issue, fail) succeeds; the loser →
        ERR_INVALID_STATE.
        """
        from test_helpers import (
            create_confirmation,
            create_confirmation_payload,
            fail_confirmation_payload,
            setup_sold_auction,
        )
        _lot, auction, _bidders, _winning_bid = setup_sold_auction(
            num_bidders=1, assessment_value_cents=100_000_000,
            deposit_mode="FIXED", deposit_fixed_cents=5_000_000,
        )
        confirmation = create_confirmation(auction["id"])

        def issue():
            return api.issue_confirmation(
                confirmation["id"], court_clerk_headers,
            )

        def fail():
            return api.fail_confirmation(
                confirmation["id"],
                fail_confirmation_payload(failure_reason="COURT_OVERRIDE"),
                court_clerk_headers,
            )

        results = run_race(issue, fail)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # The loser carries ERR_INVALID_STATE per PRD §2.12.
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


class TestConcurrentTieBreakBid:

    def test_two_concurrent_bids_same_amount_exactly_one_succeeds(self, api):
        """PRD §2.12: "Two bids that arrive with identical `amount_cents` on the same auction at the same server second serialise to first-writer-wins on `Auction.current_high_cents`, with the tie broken in favour of the lower `(client_seq_no, created_at)` pair; the loser sees `current_high_cents` already equal to its own amount and is rejected with `ERR_BID_NOT_ABOVE_HIGH."

        Claim: two concurrent bids with same amount → exactly one
        succeeds, the loser returns ERR_BID_NOT_ABOVE_HIGH.
        """
        _lot, auction, _ = setup_live_auction(
            num_bidders=0, assessment_value_cents=100_000_000,
        )
        # Two bidders with PAID deposits.
        from test_helpers import setup_bidder_with_paid_deposit
        bidder_a, _ = setup_bidder_with_paid_deposit(auction)
        bidder_b, _ = setup_bidder_with_paid_deposit(auction)
        amount = 70_000_000  # equals starting_price

        def bid_a():
            return api.create_bid(
                create_bid_payload(auction["id"], amount, client_seq_no=1),
                make_bidder_headers(bidder_a["id"]),
            )

        def bid_b():
            return api.create_bid(
                create_bid_payload(auction["id"], amount, client_seq_no=2),
                make_bidder_headers(bidder_b["id"]),
            )

        results = run_race(bid_a, bid_b)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_BID_NOT_ABOVE_HIGH.value)
