"""Default and runner-up flow (PRD §3.4 last paragraphs)."""
import pytest

from test_helpers import (
    api_client, ApiErrorId,
    place_bid_payload,
    TEST_USERS, make_seller_headers, make_bidder_headers,
    create_seller, create_bidder, setup_live_lot, place_bid_on_lot,
    close_lot_to_sold, get_lot,
    validate_success, validate_error,
)


ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_sold_lot_with_runner_up(
    reserve_price_cents=100_000,
    winner_bid=110_000,
    runner_up_bid=100_000,
):
    """Build seller + lot + winner W + runner-up R at runner_up_bid + W at winner_bid; close to SOLD.
    Returns (seller, lot, winner, runner_up)."""
    seller, lot = setup_live_lot(reserve_price_cents=reserve_price_cents, starting_bid_cents=50_000)
    runner_up = create_bidder("RunnerUp", wallet_amount_cents=2_000_000)
    winner = create_bidder("Winner", wallet_amount_cents=2_000_000)
    place_bid_on_lot(runner_up, lot, runner_up_bid)
    place_bid_on_lot(winner, lot, winner_bid)
    lot = close_lot_to_sold(lot["id"])
    return seller, lot, winner, runner_up


class TestManualDefault:
    def test_winner_default_no_runner_up_unsold(self, api):
        """PRD §3.4: "If no runner-up exists, the lot moves immediately to `UNSOLD`:
        the defaulter's `Deposit` (the one whose `bidder_id` is the defaulter and
        `lot_id` is this lot) is moved to `FORFEITED` with
        `terminal_reason = WINNER_DEFAULT_NO_REOFFER`, `refund_amount_cents = 0`,
        and `forfeit_amount_cents` equal to the deposit's `amount_cents`; the `Invoice`
        is moved to `REVERSED` with `refund_amount_cents = 0`."

        Claim: SOLD lot without runner-up → POST /winner/default → UNSOLD; Invoice REVERSED.

        # difficulty: dual_variant_calc/deposit_terminal_amount_variant
        """
        seller, lot = setup_live_lot(reserve_price_cents=100_000, starting_bid_cents=50_000)
        winner = create_bidder("LoneWinner", wallet_amount_cents=2_000_000)
        place_bid_on_lot(winner, lot, 100_000)
        lot = close_lot_to_sold(lot["id"])
        assert lot["status"] == "SOLD"
        # No runner-up — runner_up_bid_id should be null (only one bidder)
        assert lot.get("runner_up_bid_id") in (None,)

        resp = api.default_winner(lot["id"], ADMIN)
        data = validate_success(resp)
        assert data["status"] == "UNSOLD"

        invoice = validate_success(api.get_invoice(lot["id"], ADMIN))
        assert invoice["status"] == "REVERSED"
        assert invoice["refund_amount_cents"] == 0

    def test_winner_default_with_runner_up_reoffered(self, api):
        """PRD §3.4: "If a runner-up exists, the lot moves immediately to `REOFFERED`,
        and `runner_up_acceptance_deadline_at` is set to the current logical clock value
        plus the runner-up acceptance-window duration in seconds."

        Claim: SOLD lot with runner-up → POST /winner/default → REOFFERED.
        """
        seller, lot, winner, runner_up = _setup_sold_lot_with_runner_up()
        assert lot["status"] == "SOLD"
        assert lot["runner_up_bid_id"] is not None

        resp = api.default_winner(lot["id"], ADMIN)
        data = validate_success(resp)
        assert data["status"] == "REOFFERED"

    def test_default_outside_sold_rejected(self, api):
        """PRD §3.4: "Attempts to invoke any of the close-or-settlement actions outside
        the appropriate state — defaulting a lot that is not `SOLD`... are rejected
        with `ERR_LOT_INVALID_STATE`."

        Claim: Default on a LIVE lot → ERR_LOT_INVALID_STATE.
        """
        seller, lot = setup_live_lot()
        resp = api.default_winner(lot["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE.value)


class TestRunnerUpAccept:
    def test_runner_up_accept_moves_to_sold(self, api):
        """PRD §3.4: "Accepting before `runner_up_acceptance_deadline_at` and while the
        bidder is `ACTIVE` moves the lot back to `SOLD`: `winning_bidder_id` is updated
        to the runner-up, `hammer_price_cents` becomes the runner-up bid's
        `amount_cents`, the runner-up bid's `status` becomes `WINNING` and
        `Lot.current_winner_bid_id` updates accordingly..."

        Claim: REOFFERED → runner-up accepts → SOLD with new hammer = runner-up bid.

        # difficulty: dual_variant_calc/deposit_terminal_amount_variant
        """
        seller, lot, winner, runner_up = _setup_sold_lot_with_runner_up(
            reserve_price_cents=100_000, winner_bid=110_000, runner_up_bid=100_000
        )
        # Default the winner — REOFFERED
        api.default_winner(lot["id"], ADMIN)
        # Runner-up accepts
        resp = api.runner_up_accept(lot["id"], make_bidder_headers(runner_up["id"]))
        data = validate_success(resp)
        assert data["status"] == "SOLD"
        assert data["hammer_price_cents"] == 100_000
        assert data["winning_bidder_id"] == runner_up["id"]

    def test_runner_up_accept_creates_new_invoice(self, api):
        """PRD §3.4: "...the original `Invoice` is moved to `REVERSED` with
        `refund_amount_cents = 0`, a fresh `Invoice` is created with `status = ISSUED`,
        and `payment_deadline_at` is set to the current logical clock value plus the
        payment-deadline window."

        Claim: After runner-up accept, there is an ISSUED Invoice for the lot.
        """
        seller, lot, winner, runner_up = _setup_sold_lot_with_runner_up(
            reserve_price_cents=100_000, winner_bid=110_000, runner_up_bid=100_000
        )
        api.default_winner(lot["id"], ADMIN)
        api.runner_up_accept(lot["id"], make_bidder_headers(runner_up["id"]))
        invoice = validate_success(api.get_invoice(lot["id"], ADMIN))
        assert invoice["status"] == "ISSUED"
        assert invoice["buyer_id"] == runner_up["id"]
        assert invoice["hammer_price_cents"] == 100_000

    def test_runner_up_accept_by_non_runner_up(self, api):
        """PRD §2.1: "ownership checks on a bid, an auto-bid proxy, a deposit, a
        runner-up acceptance, or a dispute compare the resource's `bidder_id` (or, for
        runner-up acceptance, the `Bidder.id` referenced by `Lot.runner_up_bid_id`'s
        `bidder_id`...) to `X-User-ID`."
        PRD §2.1: "When the role passes the role-permission check (priority 2) but the
        acting principal is not the resource's owner under the rules above, the request
        is rejected with `ERR_IDENTITY_MISMATCH` and HTTP status 403."

        Claim: Non-runner-up Bidder calling /runner-up/accept → ERR_IDENTITY_MISMATCH.
        """
        seller, lot, winner, runner_up = _setup_sold_lot_with_runner_up()
        api.default_winner(lot["id"], ADMIN)
        outsider = create_bidder("Outsider", wallet_amount_cents=2_000_000)
        resp = api.runner_up_accept(lot["id"], make_bidder_headers(outsider["id"]))
        validate_error(resp, ApiErrorId.ERR_IDENTITY_MISMATCH.value)


class TestRunnerUpDecline:
    def test_runner_up_decline_unsold(self, api):
        """PRD §3.4: "Declining — or letting the runner-up window elapse, evaluated
        whenever the clock advances — moves the lot from `REOFFERED` to `UNSOLD`:
        the defaulter's `Deposit` is moved to `FORFEITED` with `terminal_reason =
        WINNER_DEFAULT_NO_REOFFER` and `refund_amount_cents = 0`, the runner-up's
        `Deposit` is `RELEASED` with `terminal_reason = LOSING_BIDDER`, and the
        (replacement) `Invoice` is moved to `REVERSED` with `refund_amount_cents = 0`."

        Claim: REOFFERED → /runner-up/decline → UNSOLD.

        # difficulty: dual_variant_calc/deposit_terminal_amount_variant
        """
        seller, lot, winner, runner_up = _setup_sold_lot_with_runner_up()
        api.default_winner(lot["id"], ADMIN)
        resp = api.runner_up_decline(lot["id"], make_bidder_headers(runner_up["id"]))
        data = validate_success(resp)
        assert data["status"] == "UNSOLD"


class TestActionsOutsideExpectedState:
    def test_runner_up_accept_outside_reoffered(self, api):
        """PRD §3.4: "Attempts to invoke any of the close-or-settlement actions outside
        the appropriate state — ... accepting or declining a runner-up offer on a lot
        that is not `REOFFERED` — are rejected with `ERR_LOT_INVALID_STATE`."

        Claim: /runner-up/accept on a SOLD lot (no default) → ERR_LOT_INVALID_STATE.
        """
        seller, lot, winner, runner_up = _setup_sold_lot_with_runner_up()
        # Lot still SOLD — no default — accept should reject
        resp = api.runner_up_accept(lot["id"], make_bidder_headers(runner_up["id"]))
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE.value)

    def test_runner_up_decline_outside_reoffered(self, api):
        """PRD §3.4: "Attempts to invoke any of the close-or-settlement actions outside
        the appropriate state — ... accepting or declining a runner-up offer on a lot
        that is not `REOFFERED` — are rejected with `ERR_LOT_INVALID_STATE`."

        Claim: /runner-up/decline on a SOLD lot → ERR_LOT_INVALID_STATE.
        """
        seller, lot, winner, runner_up = _setup_sold_lot_with_runner_up()
        resp = api.runner_up_decline(lot["id"], make_bidder_headers(runner_up["id"]))
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE.value)
