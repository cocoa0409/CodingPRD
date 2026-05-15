"""Auction lifecycle: open, cancel, starting-price computation across
rounds, deposit-amount calc, second-bidder field pinning (PRD §3.3,
§3.4, §3.5)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    assert_auction,
    cancel_auction,
    cancel_auction_payload,
    create_lot,
    create_lot_payload,
    DEPOSIT_MAX_PERCENT_BPS,
    DEPOSIT_MIN_PERCENT_BPS,
    FIRST_AUCTION_DISCOUNT_BPS,
    get_auction,
    iso_utc,
    open_auction,
    place_bid,
    REAUCTION_DISCOUNT_BPS,
    setup_announced_lot,
    setup_bidder_with_paid_deposit,
    setup_live_auction,
    setup_lot_with_auction,
    setup_unsold_auction,
    utcnow,
    validate_error,
    validate_success,
)


def _parse(value):
    from datetime import datetime
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


# ===========================================================================
# Starting price calc — PRD §3.3
# ===========================================================================
class TestStartingPriceCalc:

    def test_first_auction_70pct_of_assessment(self, api):
        """PRD §3.3: "`starting_price_cents` is the result of multiplying `Lot.assessment_value_cents` by ten thousand minus three thousand (the basis-point representation of the first-auction discount), then dividing by ten thousand, then rounding half up to integer cents."

        Claim: starting = round_half_up(assessment * 7000 / 10000).
        With assessment = 100_000_000 → 70_000_000 exactly.
        """
        _, auction = setup_lot_with_auction(
            assessment_value_cents=100_000_000,
        )
        assert auction["starting_price_cents"] == 70_000_000

    def test_round_two_starting_price_uses_prior_round_base(self, api):
        """PRD §3.3: "Re-auction rounds discount further. When `round_number` is greater than one, `starting_price_cents` is computed from the prior round's `starting_price_cents` — not from the original `assessment_value_cents` — by multiplying that prior value by ten thousand minus two thousand."

        Claim: round-2 starting == round_half_up(round-1 starting * 0.80).
        With assessment=100_000_000 → round-1=70_000_000 →
        round-2=56_000_000 exactly.
        """
        from test_helpers import get_lot
        lot, auction1 = setup_unsold_auction(
            assessment_value_cents=100_000_000,
        )
        # The system has bubbled Lot to AUCTIONED and triggered re-auction.
        lot = get_lot(lot["id"])
        # Find the round-2 auction id off the lot.
        auction2_id = (
            lot.get("auction_id")
            or lot.get("current_auction_id")
            or (lot.get("auctions") or [None])[-1]
        )
        if isinstance(auction2_id, dict):
            auction2_id = auction2_id.get("id")
        auction2 = get_auction(auction2_id)
        assert auction2["starting_price_cents"] == 56_000_000, (
            f"Expected 56_000_000 (= 70_000_000 * 0.80), "
            f"got {auction2['starting_price_cents']}"
        )

    def test_lot_round_number_increments_to_2_on_unsold(self, api):
        """PRD §3.3: "The `Lot.round_number` starts at one on registration and is incremented by one each time a re-auction is triggered."

        Claim: UNSOLD → Lot.round_number == 2.
        """
        from test_helpers import get_lot
        lot, _auction = setup_unsold_auction()
        lot = get_lot(lot["id"])
        assert lot["round_number"] == 2


# ===========================================================================
# Deposit amount calc — PRD §3.4
# ===========================================================================
class TestDepositAmountCalc:

    def test_percent_mode_deposit_uses_basis_points(self, api):
        """PRD §3.4: "If `deposit_mode` is `PERCENT`, `deposit_amount_cents` is computed as the `starting_price_cents` multiplied by `deposit_percent_bps`, divided by ten thousand, and rounded half up to integer cents."

        Claim: 10% on a 70_000_000 starting price → 7_000_000.
        """
        _, auction = setup_announced_lot(
            assessment_value_cents=100_000_000,
            deposit_mode="PERCENT",
            deposit_percent_bps=1000,  # 10%
        )
        # deposit_amount_cents pinned at announce
        assert auction["deposit_amount_cents"] == 7_000_000

    def test_fixed_mode_deposit_uses_literal_value(self, api):
        """PRD §3.4: "If `deposit_mode` is `FIXED`, `deposit_amount_cents` is taken literally from `deposit_fixed_cents."

        Claim: FIXED mode with deposit_fixed_cents=5_000_000 →
        deposit_amount_cents == 5_000_000.
        """
        _, auction = setup_announced_lot(
            assessment_value_cents=100_000_000,
            deposit_mode="FIXED",
            deposit_fixed_cents=5_000_000,
        )
        assert auction["deposit_amount_cents"] == 5_000_000


# ===========================================================================
# Auction open transition — PRD §3.5
# ===========================================================================
class TestAuctionOpen:

    def test_open_before_scheduled_start_rejected(self, api):
        """PRD §3.5: "Opening is only permitted when the current instant has reached `scheduled_start_at`, the parent lot is `ANNOUNCED`, and the auction's `starting_price_cents` and `deposit_amount_cents` are both pinned."

        Claim: open with now < scheduled_start_at → ERR_INVALID_STATE.
        """
        _lot, auction = setup_announced_lot()
        # Do NOT advance the clock; auction.scheduled_start_at is in future.
        resp = api.open_auction(
            auction["id"], headers={"X-User-ID": "admin-001",
                                    "X-User-Role": "AuctionAdmin",
                                    "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_open_transitions_status_to_live(self, api):
        """PRD §3.5: "an `AuctionAdmin` opens the auction, advancing it from `SCHEDULED` to `LIVE`."
        PRD §3.5: "The transition also sets `effective_end_at` equal to `scheduled_end_at`; the effective end may later drift forward through soft-close extensions but never backward."

        Claim: open after scheduled_start → status=LIVE and
        effective_end_at == scheduled_end_at.
        """
        _lot, auction, _bidders = setup_live_auction(num_bidders=1)
        assert auction["status"] == "LIVE"
        assert auction["effective_end_at"] == auction["scheduled_end_at"], (
            "PRD §3.5: on open, effective_end_at = scheduled_end_at"
        )


# ===========================================================================
# Auction cancellation — PRD §3.5
# ===========================================================================
class TestAuctionCancel:

    def test_cancel_scheduled_auction_with_no_bids_succeeds(
        self, api, court_clerk_headers,
    ):
        """PRD §3.5: "A `CourtClerk` may cancel a `SCHEDULED` auction so long as no bid has yet been placed (that is, `current_high_cents` is still null). Cancellation accepts a `reason` and moves `status` to `CANCELLED."

        Claim: cancel a SCHEDULED auction (no bids) → status=CANCELLED.
        """
        _lot, auction = setup_announced_lot()
        resp = api.cancel_auction(
            auction["id"],
            cancel_auction_payload(reason="testing"),
            court_clerk_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"

    def test_cancel_live_auction_rejected(self, api, court_clerk_headers):
        """PRD §3.5: cancel only valid in SCHEDULED state (the §3.5
        "may cancel a SCHEDULED auction" condition is the only valid
        precondition stated).

        Claim: cancel on a LIVE auction → ERR_INVALID_STATE.
        """
        _lot, auction, _bidders = setup_live_auction(num_bidders=1)
        resp = api.cancel_auction(
            auction["id"], cancel_auction_payload(reason="x"),
            court_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Auction close → SOLD / UNSOLD — PRD §3.5
# ===========================================================================
class TestAuctionClose:

    def test_auction_with_no_bids_closes_unsold(self, api):
        """PRD §3.5: "If no valid bid exists, the auction instead moves from `LIVE` to `UNSOLD`, the parent `Lot.status` still bubbles to `AUCTIONED`, the platform schedules a re-auction subject to the round limit, and every `PAID` deposit on this auction also cascades to `REFUNDED."

        Claim: clock-advance past effective_end_at with no bids →
        status=UNSOLD.
        """
        _lot, auction = setup_unsold_auction()
        assert auction["status"] == "UNSOLD"

    def test_auction_with_one_bid_closes_sold(self, api):
        """PRD §3.5: "If at least one `VALID` bid exists (`current_high_cents` is not null), the auction moves from `LIVE` to `SOLD."

        Claim: clock-advance past effective_end_at with ≥1 valid bid →
        status=SOLD.
        """
        from test_helpers import setup_sold_auction
        _lot, auction, _bidders, _bid = setup_sold_auction(num_bidders=1)
        assert auction["status"] == "SOLD"

    def test_sold_auction_records_winner_account_id(self, api):
        """PRD §3.5: "`outcome_winner_account_id` is recorded as the `bidder_account_id` of the highest-bid winner, `highest_bid_id` and `second_highest_bid_id` are pinned, and the parent `Lot.status` bubbles to `AUCTIONED`."

        Claim: SOLD auction carries outcome_winner_account_id = winner's id.
        """
        from test_helpers import setup_sold_auction
        _lot, auction, bidders, _bid = setup_sold_auction(num_bidders=2)
        winner_account = bidders[-1][0]
        assert auction["outcome_winner_account_id"] == winner_account["id"]
