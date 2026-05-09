"""Disputes, arbitration, refund cascade, and commission reversal (PRD §3.5)."""
import pytest

from test_helpers import (
    api_client, ApiErrorId,
    file_dispute_payload, resolve_dispute_payload,
    TEST_USERS, make_seller_headers, make_bidder_headers, make_arbitrator_headers,
    create_seller, create_bidder, setup_sold_lot, setup_paid_lot,
    setup_paid_and_delivered_lot, setup_dispute_under_review,
    place_bid_on_lot, file_dispute_for_lot,
    advance_clock, get_lot,
    validate_success, validate_error,
    assert_dispute, assert_invoice,
    commission_reversal_cents,
)


ADMIN = TEST_USERS["platform_admin_headers"]


class TestDisputeFiling:
    def test_file_dispute_on_paid_delivered_lot(self, api):
        """PRD §3.5: "After a lot is `SOLD`, paid, and physically delivered (the
        logistics system having reported a `delivered_at`), the buyer may file a
        dispute. ... On filing, a `Dispute` is created with `status = FILED`...
        and the `Lot` transitions from `SOLD` to `DISPUTED`."

        Claim: Filing on PAID-and-delivered SOLD lot → Dispute FILED, Lot DISPUTED.
        """
        seller, lot, bidder, invoice = setup_paid_and_delivered_lot(
            reserve_price_cents=100_000, starting_bid_cents=100_000, bid_amount_cents=100_000,
        )
        dispute = file_dispute_for_lot(lot, bidder, claimed_refund_amount_cents=50_000)
        assert dispute["status"] == "FILED"
        lot_after = get_lot(lot["id"])
        assert lot_after["status"] == "DISPUTED"

    def test_dispute_blocked_when_invoice_not_paid(self, api):
        """PRD §3.5: "Filing requires `Invoice.status` to be `PAID`..."
        PRD §2.6: priority-4 state-check produces ERR_LOT_INVALID_STATE on the
        SOLD→DISPUTED transition.

        Claim: Dispute on SOLD-but-not-PAID lot → ERR_LOT_INVALID_STATE.

        # difficulty: cross_entity_state_dependency/dispute_filing_depends_on_invoice_status
        """
        seller, lot, bidder, invoice = setup_sold_lot(
            reserve_price_cents=100_000, starting_bid_cents=100_000, bid_amount_cents=100_000,
        )
        # Don't pay; do deliver to isolate the Invoice precondition
        from test_helpers import deliver_lot
        deliver_lot(lot)
        resp = api.file_dispute(
            lot["id"],
            file_dispute_payload(claimed_refund_amount_cents=10_000),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE.value)

    def test_dispute_filer_must_be_winner(self, api):
        """PRD §3.5: "...and the filer's `X-User-ID` to equal `Lot.winning_bidder_id`
        (a non-winner filing produces `ERR_IDENTITY_MISMATCH`)."

        Claim: Non-winner Bidder filing dispute → ERR_IDENTITY_MISMATCH.
        """
        seller, lot, winner, invoice = setup_paid_and_delivered_lot(
            reserve_price_cents=100_000, starting_bid_cents=100_000, bid_amount_cents=100_000,
        )
        outsider = create_bidder("Outsider", wallet_amount_cents=2_000_000)
        resp = api.file_dispute(
            lot["id"],
            file_dispute_payload(claimed_refund_amount_cents=10_000),
            make_bidder_headers(outsider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_IDENTITY_MISMATCH.value)


class TestStartReview:
    def test_arbitrator_starts_review(self, api):
        """PRD §3.5: "An `ArbitratorOps` operator picks up a `FILED` dispute by starting
        review, which moves it to `UNDER_REVIEW`: `arbitrator_user_id` snapshots the
        operator's `X-User-ID` and `review_started_at` is recorded."

        Claim: start-review → status=UNDER_REVIEW.
        """
        seller, lot, bidder, invoice = setup_paid_and_delivered_lot(
            reserve_price_cents=100_000, starting_bid_cents=100_000, bid_amount_cents=100_000,
        )
        dispute = file_dispute_for_lot(lot, bidder, claimed_refund_amount_cents=50_000)
        resp = api.start_dispute_review(lot["id"], dispute["id"], make_arbitrator_headers())
        data = validate_success(resp)
        assert data["status"] == "UNDER_REVIEW"

    def test_start_review_on_already_under_review(self, api):
        """PRD §3.5: "Starting review on any other dispute status — already
        `UNDER_REVIEW`, already terminal — is rejected with
        `ERR_DISPUTE_INVALID_STATE`."

        Claim: Re-start on UNDER_REVIEW → ERR_DISPUTE_INVALID_STATE.
        """
        seller, lot, bidder, invoice = setup_paid_and_delivered_lot()
        dispute = file_dispute_for_lot(lot, bidder)
        api.start_dispute_review(lot["id"], dispute["id"], make_arbitrator_headers())
        resp = api.start_dispute_review(lot["id"], dispute["id"], make_arbitrator_headers())
        validate_error(resp, ApiErrorId.ERR_DISPUTE_INVALID_STATE.value)


class TestResolveRefund:
    def test_resolve_refund_cascade(self, api):
        """PRD §3.5: "**`REFUND`** moves the `Dispute` to `RESOLVED_REFUND` and the
        `Lot` from `DISPUTED` to `REFUNDED` via the refund cascade described in §2.8:
        the original `Invoice` becomes `REVERSED` with `Invoice.refund_amount_cents`
        set to the dispute's `resolution_refund_amount_cents`..."

        Claim: REFUND outcome → Dispute RESOLVED_REFUND, Lot REFUNDED, Invoice REVERSED
        with refund_amount_cents matching.

        # difficulty: non_linear_state_machine/dispute_branching_resolution_shape
        """
        seller, lot, bidder, invoice, dispute = setup_dispute_under_review(
            hammer_amount_cents=100_000, reserve_price_cents=100_000,
            claimed_refund_amount_cents=50_000,
        )
        resp = api.resolve_dispute(
            lot["id"], dispute["id"],
            resolve_dispute_payload("REFUND", resolution_refund_amount_cents=50_000),
            make_arbitrator_headers(),
        )
        data = validate_success(resp)
        assert data["status"] == "RESOLVED_REFUND"
        lot_after = get_lot(lot["id"])
        assert lot_after["status"] == "REFUNDED"
        invoice_after = validate_success(api.get_invoice(lot["id"], ADMIN))
        assert invoice_after["status"] == "REVERSED"
        assert invoice_after["refund_amount_cents"] == 50_000

    def test_commission_reversal_nested_rounding(self, api):
        """PRD §3.5: "the `commission_reversal_amount_cents` is computed by the
        **commission-reversal rule**, which divides `resolution_refund_amount_cents` by
        `Invoice.buyer_total_cents` to produce a `Decimal` ratio rounded half-up to
        four decimal places, multiplies the original `seller_commission_cents` by that
        quantised ratio, and rounds the product half-up to integer cents (the rounding
        order is fixed — applying any other order produces a different cents value)..."

        Claim: hammer=100000 (premium=15000, commission=10000, buyer_total=115000),
        refund=50000 → ratio = round(50000/115000, 4dp half_up) = 0.4348;
        commission_reversal = round(10000 * 0.4348, half_up) = 4348.

        # difficulty: combinatorial_formula/commission_reversal_nested_rounding_order
        """
        seller, lot, bidder, invoice, dispute = setup_dispute_under_review(
            hammer_amount_cents=100_000, reserve_price_cents=100_000,
            claimed_refund_amount_cents=50_000,
        )
        # Pre-condition: invoice has expected money fields
        assert invoice["hammer_price_cents"] == 100_000
        assert invoice["buyer_premium_cents"] == 15_000
        assert invoice["seller_commission_cents"] == 10_000
        assert invoice["buyer_total_cents"] == 115_000

        api.resolve_dispute(
            lot["id"], dispute["id"],
            resolve_dispute_payload("REFUND", resolution_refund_amount_cents=50_000),
            make_arbitrator_headers(),
        )
        invoice_after = validate_success(api.get_invoice(lot["id"], ADMIN))
        assert invoice_after["status"] == "REVERSED"
        assert invoice_after["refund_amount_cents"] == 50_000
        assert invoice_after["commission_reversal_amount_cents"] == 4348, (
            f"Expected commission_reversal_amount_cents == 4348 per the pinned rounding order; "
            f"got {invoice_after['commission_reversal_amount_cents']}"
        )

    def test_refund_cascade_seller_proceeds(self, api):
        """PRD §3.5: "the seller's `gross_proceeds_cents` and `net_proceeds_cents` are
        recomputed so that `net_proceeds_cents` is reduced by the freshly computed
        reversal amount..."

        Claim: After refund cascade, net_proceeds reduced by commission_reversal_amount_cents.
        With hammer=100000, payout=90000 → commission_reversal=4348:
        Seller.net_proceeds_cents = 90000 - 4348 = 85652.

        # difficulty: transitive_cascade/refund_cascade
        """
        seller, lot, bidder, invoice, dispute = setup_dispute_under_review(
            hammer_amount_cents=100_000, reserve_price_cents=100_000,
            claimed_refund_amount_cents=50_000,
        )
        # Before resolution: gross = net = 90000
        seller_before = validate_success(api.get_seller(seller["id"], ADMIN))
        assert seller_before["gross_proceeds_cents"] == 90_000
        assert seller_before["net_proceeds_cents"] == 90_000

        api.resolve_dispute(
            lot["id"], dispute["id"],
            resolve_dispute_payload("REFUND", resolution_refund_amount_cents=50_000),
            make_arbitrator_headers(),
        )

        seller_after = validate_success(api.get_seller(seller["id"], ADMIN))
        assert seller_after["net_proceeds_cents"] == 85_652, (
            f"Expected net_proceeds_cents == 85652 (90000 - 4348); got {seller_after['net_proceeds_cents']}"
        )


class TestResolveRelist:
    def test_resolve_relist_creates_new_draft_lot(self, api):
        """PRD §3.5: "**`RELIST`** moves the `Dispute` to `RESOLVED_RELIST` and the `Lot`
        from `DISPUTED` to `RELISTED` (a terminal status). The original `Invoice`
        becomes `REVERSED` with `refund_amount_cents` set to the full `buyer_total_cents`,
        and `commission_reversal_amount_cents` set to the original
        `seller_commission_cents` in full (the ratio is exactly 1.0000, so no rounding
        is needed). The platform creates a fresh `Lot` in `DRAFT` that copies `title`,
        `category`, `condition`, `physical_item_serial`, `reserve_price_cents`, and
        `starting_bid_cents` from the original; the new lot's `relisted_from_lot_id`
        is set to the original lot's `id`..."

        Claim: RELIST outcome → Lot RELISTED; Invoice REVERSED with full refund;
        new DRAFT lot exists with relisted_from_lot_id == original lot.id.

        # difficulty: non_linear_state_machine/dispute_branching_resolution_shape
        """
        seller, lot, bidder, invoice, dispute = setup_dispute_under_review(
            hammer_amount_cents=100_000, reserve_price_cents=100_000,
            claimed_refund_amount_cents=50_000,
        )
        api.resolve_dispute(
            lot["id"], dispute["id"],
            resolve_dispute_payload("RELIST"),
            make_arbitrator_headers(),
        )
        lot_after = get_lot(lot["id"])
        assert lot_after["status"] == "RELISTED"
        invoice_after = validate_success(api.get_invoice(lot["id"], ADMIN))
        assert invoice_after["status"] == "REVERSED"
        assert invoice_after["refund_amount_cents"] == 115_000  # full buyer_total
        assert invoice_after["commission_reversal_amount_cents"] == 10_000  # full commission
        # New DRAFT lot exists with relisted_from_lot_id
        listing = api.list_lots(ADMIN, params={"status": "DRAFT", "limit": 100})
        body = listing.json()
        relisted = [l for l in body["data"] if l.get("relisted_from_lot_id") == lot["id"]]
        assert len(relisted) >= 1, "Expected a new DRAFT lot referring to the original via relisted_from_lot_id"

    # NOTE: test_relist_cycle_seller_proceeds_zero was removed. PRD §3.5 RELIST
    # text describes the invoice reversal (full refund_amount_cents and full
    # commission_reversal_amount_cents) but is silent on the seller's
    # gross_proceeds_cents and net_proceeds_cents under RELIST — only the
    # REFUND cascade has the explicit "net_proceeds_cents is reduced by the
    # freshly computed reversal amount" text. A faithful PRD-only reader could
    # reasonably leave seller proceeds at 90000/80000, drop both to 0, or any
    # other combination — unique derivability fails.


class TestResolveDenied:
    def test_resolve_denied_reverts_to_sold(self, api):
        """PRD §3.5: "**`DENIED`** moves the `Dispute` to `RESOLVED_DENIED` and the
        `Lot` back from `DISPUTED` to `SOLD`; the `Invoice` remains `PAID` and no
        refund is issued. The filer's `dispute_loss_count` is incremented by one and
        their `risk_score` is recomputed."

        Claim: DENIED → Lot SOLD (reverted); Invoice PAID; bidder.dispute_loss_count +1.

        # difficulty: non_linear_state_machine/lot_branching_with_revert_shape
        # difficulty: non_linear_state_machine/dispute_branching_resolution_shape
        """
        seller, lot, bidder, invoice, dispute = setup_dispute_under_review(
            hammer_amount_cents=100_000, reserve_price_cents=100_000,
            claimed_refund_amount_cents=50_000,
        )
        bidder_before = validate_success(api.get_bidder(bidder["id"], ADMIN))
        api.resolve_dispute(
            lot["id"], dispute["id"],
            resolve_dispute_payload("DENIED"),
            make_arbitrator_headers(),
        )
        lot_after = get_lot(lot["id"])
        assert lot_after["status"] == "SOLD"
        invoice_after = validate_success(api.get_invoice(lot["id"], ADMIN))
        assert invoice_after["status"] == "PAID"
        bidder_after = validate_success(api.get_bidder(bidder["id"], ADMIN))
        assert bidder_after["dispute_loss_count"] == bidder_before["dispute_loss_count"] + 1


class TestResolveAmountValidation:
    def test_refund_requires_positive_amount(self, api):
        """PRD §3.5: "when `outcome` is `REFUND`, `resolution_refund_amount_cents` is
        required, must be strictly greater than 0, and must be at most
        `Invoice.buyer_total_cents`..."

        Claim: REFUND with amount=0 → ERR_INVALID_REFUND_AMOUNT.
        """
        seller, lot, bidder, invoice, dispute = setup_dispute_under_review()
        resp = api.resolve_dispute(
            lot["id"], dispute["id"],
            {"outcome": "REFUND", "resolution_refund_amount_cents": 0},
            make_arbitrator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REFUND_AMOUNT.value)

    def test_refund_amount_above_buyer_total(self, api):
        """PRD §3.5: "...must be at most `Invoice.buyer_total_cents`..."

        Claim: REFUND with amount > buyer_total_cents → ERR_INVALID_REFUND_AMOUNT.
        """
        seller, lot, bidder, invoice, dispute = setup_dispute_under_review(
            hammer_amount_cents=100_000, reserve_price_cents=100_000,
            claimed_refund_amount_cents=50_000,
        )
        # buyer_total = 115_000 → over-refund
        resp = api.resolve_dispute(
            lot["id"], dispute["id"],
            {"outcome": "REFUND", "resolution_refund_amount_cents": 200_000},
            make_arbitrator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REFUND_AMOUNT.value)

    def test_denied_with_nonzero_amount(self, api):
        """PRD §3.5: "when `outcome` is `RELIST` or `DENIED`, the field must be 0 or
        omitted (any non-zero supplied value produces `ERR_INVALID_REFUND_AMOUNT`,
        HTTP 422)."

        Claim: DENIED with non-zero refund → ERR_INVALID_REFUND_AMOUNT.
        """
        seller, lot, bidder, invoice, dispute = setup_dispute_under_review()
        resp = api.resolve_dispute(
            lot["id"], dispute["id"],
            {"outcome": "DENIED", "resolution_refund_amount_cents": 100},
            make_arbitrator_headers(),
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_INVALID_REFUND_AMOUNT"

    def test_relist_with_nonzero_amount(self, api):
        """PRD §3.5: "when `outcome` is `RELIST` or `DENIED`, the field must be 0 or
        omitted (any non-zero supplied value produces `ERR_INVALID_REFUND_AMOUNT`,
        HTTP 422)."

        Claim: RELIST with non-zero refund → ERR_INVALID_REFUND_AMOUNT.
        """
        seller, lot, bidder, invoice, dispute = setup_dispute_under_review()
        resp = api.resolve_dispute(
            lot["id"], dispute["id"],
            {"outcome": "RELIST", "resolution_refund_amount_cents": 50},
            make_arbitrator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REFUND_AMOUNT.value)


class TestResolveStateGate:
    def test_resolve_on_filed_status(self, api):
        """PRD §3.5: "Resolution requires `UNDER_REVIEW`..." (resolution on FILED is
        outside the allowed source state).

        Claim: resolve on FILED → ERR_DISPUTE_INVALID_STATE.
        """
        seller, lot, bidder, invoice = setup_paid_and_delivered_lot()
        dispute = file_dispute_for_lot(lot, bidder, claimed_refund_amount_cents=10_000)
        # do NOT start review
        resp = api.resolve_dispute(
            lot["id"], dispute["id"],
            resolve_dispute_payload("REFUND", resolution_refund_amount_cents=5000),
            make_arbitrator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_INVALID_STATE.value)
