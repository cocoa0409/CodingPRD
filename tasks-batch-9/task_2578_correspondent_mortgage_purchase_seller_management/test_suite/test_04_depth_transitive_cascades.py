"""One call, four levels: settlement fans out, and repurchase unwinds it."""

from test_helpers import (
    REVIEWER_ALT,
    api_client,
    assert_commitment,
    assert_commitment_amounts_conserved,
    assert_escrow_transfer,
    assert_loan,
    assert_purchase_advice,
    assert_repurchase_demand,
    fixtures,
    validate_success,
)


def _advised_loan_ready_to_settle() -> dict:
    """A cleared 40,000,000 released loan carrying one issued advice."""
    staged = fixtures.setup_cleared_loan(
        commitment_overrides={"notional_amount_cents": 40000000},
        loan_overrides={
            "seller_loan_number": "HP-5001",
            "note_amount_cents": 40000000,
            "servicing_election": "RELEASED",
            "escrow_balance_cents": 320000,
            "closing_date": "2026-07-20",
        },
    )
    fixtures.setup_clock("2026-08-05T00:00:00Z")
    advice = fixtures.issue_purchase_advice(staged["loan_id"])
    staged["advice"] = advice
    staged["advice_id"] = advice["id"]
    return staged


def _settled_loan() -> dict:
    """The same loan once the advice has been settled and the wire has moved."""
    staged = _advised_loan_ready_to_settle()
    staged["advice"] = fixtures.settle_purchase_advice(staged["advice_id"], "WIRE-5001")
    staged["transfer"] = fixtures.read_pending_escrow_transfer(staged["loan_id"])
    return staged


class TestSettlementCascade:
    """Settling one advice moves the advice, the loan, the line and the seller."""

    def test_settlement_carries_the_advice_the_loan_and_the_line_forward(self):
        """Three levels of state move on a single settle call.

        The advice settles at the 2026-08-05 clock for its full 41,284,056 wire,
        the loan reaches purchased, and the parent commitment converts its whole
        40,000,000 allocation into fulfilment, which takes it terminal with a
        zero residual and no fee.

        PRD: "The parent commitment fills: `fulfilled_amount_cents` rises by the
        loan's `note_amount_cents` and `allocated_amount_cents` falls by the same
        amount, so `available_amount_cents` is unchanged by this hop — the
        allocation simply converts into fulfilment."

        Design: Difficulty/transitive_cascade/advice_settlement_cascades_advice_loan_commitment_seller_escrow
        """
        staged = _advised_loan_ready_to_settle()

        settled = validate_success(
            api_client.settle_purchase_advice(
                staged["advice_id"], {"funding_reference": "WIRE-5001"}, REVIEWER_ALT
            ),
            200,
        )

        assert_purchase_advice(settled)
        assert settled["status"] == "SETTLED"
        assert settled["settled_at"] == "2026-08-05T00:00:00.000Z"
        assert settled["net_wire_cents"] == 41284056

        loan = fixtures.read_loan(staged["loan_id"])
        assert_loan(loan)
        assert loan["purchase_status"] == "PURCHASED"
        assert loan["purchased_at"] == "2026-08-05T00:00:00.000Z"

        commitment = fixtures.read_commitment(staged["commitment_id"])
        assert_commitment(commitment)
        assert commitment["status"] == "FULFILLED"
        assert commitment["fulfilled_amount_cents"] == 40000000
        assert commitment["allocated_amount_cents"] == 0
        assert commitment["available_amount_cents"] == 0
        assert commitment["cancelled_amount_cents"] == 0
        assert commitment["pair_off_fee_cents"] == 0
        assert_commitment_amounts_conserved(commitment)

    def test_settlement_also_books_the_seller_totals_and_the_escrow_transfer(self):
        """The fourth level and a brand new resource appear from the same call.

        The seller's funded total picks up the wire exactly, its mandatory
        exposure drops to zero because the line went terminal, no fee is booked,
        and because servicing was released a pending escrow transfer for the
        frozen 320,000 balance appears due fifteen days after purchase.

        PRD: "When the loan's `servicing_election` is `RELEASED`, an
        **EscrowTransfer** is created in `PENDING` status with
        `transfer_amount_cents` frozen at the loan's `escrow_balance_cents` and
        `transfer_due_at` set to `purchased_at` advanced by 15 days."

        Design: Difficulty/transitive_cascade/advice_settlement_cascades_advice_loan_commitment_seller_escrow
        """
        staged = _advised_loan_ready_to_settle()

        validate_success(
            api_client.settle_purchase_advice(
                staged["advice_id"], {"funding_reference": "WIRE-5001"}, REVIEWER_ALT
            ),
            200,
        )

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["net_funded_cents"] == 41284056
        assert seller["open_mandatory_exposure_cents"] == 0
        assert seller["fee_receivable_cents"] == 0

        transfers = fixtures.read_escrow_transfers(staged["loan_id"])
        assert len(transfers) == 1
        transfer = transfers[0]
        assert_escrow_transfer(transfer)
        assert transfer["status"] == "PENDING"
        assert transfer["transfer_amount_cents"] == 320000
        assert transfer["transfer_due_at"] == "2026-08-20T00:00:00.000Z"


class TestDemandSatisfactionUnwind:
    """Satisfying a demand reverses the same chain settlement had built."""

    @staticmethod
    def _loan_under_epd_demand() -> dict:
        staged = _settled_loan()
        fixtures.setup_clock("2026-09-15T00:00:00Z")
        fixtures.record_payment_event(staged["loan_id"], "FIRST_PAYMENT_MISSED")
        demand = fixtures.issue_repurchase_demand(staged["loan_id"], "EPD", "RD-6001")
        staged["demand"] = demand
        staged["demand_id"] = demand["id"]
        return staged

    def test_satisfaction_prices_the_repurchase_off_the_wire_and_retires_the_loan(self):
        """The demand's money is the wire plus the flat fee, nothing recomputed.

        Recovery is pinned at the 41,284,056 that was wired, the administrative
        fee is the flat 50,000, and the total repurchase price is 41,334,056. The
        seller remits inside the appeal window that closes 2026-10-15, so the
        demand is satisfied and the loan is retired as repurchased.

        PRD: "The `admin_fee_cents` is a flat 50,000 cents, and the
        `repurchase_price_cents` is the sum of the two."

        Design: Difficulty/transitive_cascade/demand_satisfaction_unwinds_advice_escrow_and_net_funded
        """
        staged = self._loan_under_epd_demand()

        assert_repurchase_demand(staged["demand"])
        assert staged["demand"]["funding_recovery_cents"] == 41284056
        assert staged["demand"]["admin_fee_cents"] == 50000
        assert staged["demand"]["repurchase_price_cents"] == 41334056
        assert staged["demand"]["appeal_deadline_at"] == "2026-10-15T00:00:00.000Z"

        satisfied = validate_success(
            api_client.settle_repurchase_demand(
                staged["demand_id"],
                {"remittance_reference": "REMIT-6001"},
                staged["seller_headers"],
            ),
            200,
        )

        assert satisfied["status"] == "SATISFIED"
        assert satisfied["satisfied_at"] == "2026-09-15T00:00:00.000Z"

        loan = fixtures.read_loan(staged["loan_id"])
        assert loan["purchase_status"] == "REPURCHASED"
        assert loan["first_payment_status"] == "MISSED"

    def test_satisfaction_reverses_the_advice_and_escrow_and_zeroes_the_funding(self):
        """The unwind is exact: funded goes back to zero, the fee stays behind.

        The settled advice and the pending escrow transfer both go to reversed,
        the transfer records why, the seller's funded total returns to precisely
        zero rather than merely close to it, the 50,000 fee lands on the
        receivable, and the fulfilled commitment is left exactly as it was.

        PRD: "The seller's `net_funded_cents` falls by the demand's
        `funding_recovery_cents`, restoring the conserved cash identity of §2.7 to
        its pre-purchase value, and `fee_receivable_cents` rises by the demand's
        `admin_fee_cents`."

        Design: Difficulty/transitive_cascade/demand_satisfaction_unwinds_advice_escrow_and_net_funded
        """
        staged = self._loan_under_epd_demand()

        validate_success(
            api_client.settle_repurchase_demand(
                staged["demand_id"],
                {"remittance_reference": "REMIT-6001"},
                staged["seller_headers"],
            ),
            200,
        )

        advices = fixtures.read_loan_advices(staged["loan_id"])
        assert [entry["status"] for entry in advices] == ["REVERSED"]

        transfers = fixtures.read_escrow_transfers(staged["loan_id"])
        assert len(transfers) == 1
        assert transfers[0]["id"] == staged["transfer"]["id"]
        assert transfers[0]["status"] == "REVERSED"
        assert transfers[0]["reversal_reason"] == "REPURCHASE_SATISFIED"

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["net_funded_cents"] == 0
        assert seller["fee_receivable_cents"] == 50000

        commitment = fixtures.read_commitment(staged["commitment_id"])
        assert commitment["status"] == "FULFILLED"
        assert commitment["fulfilled_amount_cents"] == 40000000
