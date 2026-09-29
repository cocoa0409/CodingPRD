"""Movements that must leave the conserved notional identity standing."""

from test_helpers import (
    REVIEWER,
    api_client,
    assert_commitment,
    assert_commitment_amounts_conserved,
    assert_defect,
    assert_purchase_advice,
    fixtures,
    validate_success,
)


class TestRejectionRestoresTheLine:
    """Rejecting a delivery undoes the allocation and nothing besides."""

    @staticmethod
    def _suspended_loan_on_a_partly_used_line() -> dict:
        staged = fixtures.setup_loan_in_review(
            loan_overrides={
                "seller_loan_number": "HP-9001",
                "servicing_election": "RELEASED",
                "escrow_balance_cents": 320000,
                "closing_date": "2026-07-20",
            }
        )
        staged["defect"] = fixtures.record_defect(
            staged["loan_id"],
            "CP-TRID-TOLERANCE-CURE-MISSING",
            "COMPLIANCE",
            "HIGH",
        )
        return staged

    def test_a_high_compliance_defect_is_non_curable_and_forces_rejection(self):
        """The compliance category makes a high finding unfixable.

        A high-severity finding would normally be curable on a five-day rope, but
        the compliance category takes it out of the curable family altogether, so
        it carries no deadline, stays open, and gives the reviewer the grounds to
        throw the file back.

        PRD: "A defect is `NON_CURABLE` when its `severity` is `CRITICAL`, and
        also when its `category` is `COMPLIANCE` and its `severity` is `HIGH`; in
        every other combination it is `CURABLE`."

        Design: Difficulty/compensating_invariant/loan_rejection_restores_commitment_notional_identity
        """
        staged = self._suspended_loan_on_a_partly_used_line()

        assert_defect(staged["defect"])
        assert staged["defect"]["classification"] == "NON_CURABLE"
        assert staged["defect"]["cure_deadline_at"] is None
        assert staged["defect"]["status"] == "OPEN"

        rejected = validate_success(
            api_client.reject_loan(
                staged["loan_id"],
                REVIEWER,
                {"note": "non-curable TRID tolerance violation"},
            ),
            200,
        )

        assert rejected["purchase_status"] == "REJECTED"
        assert rejected["non_curable_defect_count"] == 1
        assert rejected["open_defect_count"] == 1

    def test_rejection_hands_the_capacity_back_and_leaves_the_line_locked(self):
        """The 40,000,000 allocation returns to available and the line stays open.

        Rejection is neither a fill nor a pair-off: the line keeps its locked
        status and books no fee, the residual returns to the full 100,000,000, the
        conserved identity holds again, and the seller's mandatory exposure is
        untouched because the commitment never went terminal.

        PRD: "Rejection moves the loan `IN_REVIEW → REJECTED` or `SUSPENDED →
        REJECTED`, a terminal status, and **compensates the delivery**: the parent
        commitment's `allocated_amount_cents` falls by the loan's
        `note_amount_cents` and its `available_amount_cents` rises by the same
        amount, restoring the conserved notional identity of §2.7 exactly as it
        stood before delivery."

        Design: Difficulty/compensating_invariant/loan_rejection_restores_commitment_notional_identity
        """
        staged = self._suspended_loan_on_a_partly_used_line()

        before = fixtures.read_commitment(staged["commitment_id"])
        assert before["allocated_amount_cents"] == 40000000
        assert before["available_amount_cents"] == 60000000

        fixtures.reject_loan(staged["loan_id"])

        commitment = fixtures.read_commitment(staged["commitment_id"])
        assert_commitment(commitment)
        assert commitment["status"] == "LOCKED"
        assert commitment["allocated_amount_cents"] == 0
        assert commitment["available_amount_cents"] == 100000000
        assert commitment["fulfilled_amount_cents"] == 0
        assert commitment["paired_off_amount_cents"] == 0
        assert commitment["cancelled_amount_cents"] == 0
        assert commitment["pair_off_fee_cents"] == 0
        assert_commitment_amounts_conserved(commitment)

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["open_mandatory_exposure_cents"] == 100000000
        assert seller["net_funded_cents"] == 0
        assert seller["fee_receivable_cents"] == 0


class TestToleranceWriteOff:
    """A shortfall inside tolerance is written off, not billed."""

    @staticmethod
    def _almost_full_fill_on_a_jumbo_line() -> dict:
        staged = fixtures.setup_lock_ready_seller(
            with_adjustment=False,
            product_overrides={
                "product_code": "JUMBO30F",
                "base_price_pct": 100.500,
                "min_fico": 720,
                "max_ltv_pct": 80.0,
                "max_loan_amount_cents": 250000000,
                "allowed_commitment_types": ["MANDATORY"],
                "allowed_occupancies": ["PRIMARY"],
                "srp_pct": 0.750,
            },
        )
        commitment = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            notional_amount_cents=100000000,
            reference_fico=760,
            reference_ltv_pct=78.0,
        )
        staged["commitment"] = commitment
        staged["commitment_id"] = commitment["id"]

        loan = fixtures.deliver_loan(
            commitment["id"],
            staged["seller_id"],
            seller_loan_number="HP-9101",
            note_amount_cents=98000000,
            note_rate_pct=6.000,
            fico=760,
            ltv_pct=78.0,
            servicing_election="RETAINED",
            escrow_balance_cents=0,
            closing_date="2026-07-28",
        )
        staged["loan"] = loan
        staged["loan_id"] = loan["id"]
        fixtures.open_loan_review(loan["id"])
        fixtures.clear_loan_for_purchase(loan["id"])
        fixtures.setup_clock("2026-08-05T00:00:00Z")
        advice = fixtures.issue_purchase_advice(loan["id"])
        staged["advice"] = advice
        staged["advice_id"] = advice["id"]
        return staged

    def test_a_shortfall_exactly_on_tolerance_is_written_off_without_a_fee(self):
        """98,000,000 against 100,000,000 lands precisely on the 2,000,000 rope.

        The line prices at 100.630 with no grid row matching, and its tolerance is
        two percent of notional. The fill leaves a shortfall equal to that
        tolerance, so the purchase retires the line rather than leaving it
        partially fulfilled, moving the residual into cancelled and charging
        nothing for it.

        PRD: "If the post-fill `fulfilled_amount_cents` reaches or exceeds
        `notional_amount_cents` minus `tolerance_cents`, the commitment moves
        `LOCKED → FULFILLED` or `PARTIALLY_FULFILLED → FULFILLED` and the
        **tolerance write-off** fires: `cancelled_amount_cents` rises by whatever
        `available_amount_cents` remains, driving `available_amount_cents` to zero
        so the conserved notional identity holds, while `pair_off_fee_cents` stays
        at zero — a shortfall inside tolerance is never billable."

        Design: Difficulty/compensating_invariant/tolerance_write_off_conserves_notional_without_pair_off_fee
        """
        staged = self._almost_full_fill_on_a_jumbo_line()
        assert staged["commitment"]["commitment_price_pct"] == 100.630
        assert staged["commitment"]["tolerance_cents"] == 2000000
        assert staged["commitment"]["llpa_bps_applied"] == 0

        fixtures.settle_purchase_advice(staged["advice_id"], "WIRE-9101")

        commitment = fixtures.read_commitment(staged["commitment_id"])
        assert commitment["status"] == "FULFILLED"
        assert commitment["fulfilled_amount_cents"] == 98000000
        assert commitment["cancelled_amount_cents"] == 2000000
        assert commitment["available_amount_cents"] == 0
        assert commitment["allocated_amount_cents"] == 0
        assert commitment["pair_off_fee_cents"] == 0
        assert commitment["pair_off_method"] is None
        assert_commitment_amounts_conserved(commitment)

    def test_the_retained_election_prices_the_advice_without_escrow_or_premium(self):
        """Keeping the servicing removes two whole components from the wire.

        Eight days of interest at 6.000 percent on a 98,617,400 principal, no
        escrow because the balance never moved and no premium because servicing
        was not released, wires 98,744,567 after the flat fee — which is what the
        seller's funded total ends up holding.

        PRD: "`escrow_funding_cents` is the loan's `escrow_balance_cents` when
        `servicing_election` is `RELEASED`, and 0 when it is `RETAINED` — a seller
        keeping the servicing keeps the escrow."

        Design: Difficulty/compensating_invariant/tolerance_write_off_conserves_notional_without_pair_off_fee
        """
        staged = self._almost_full_fill_on_a_jumbo_line()

        advice = staged["advice"]
        assert_purchase_advice(advice)
        assert advice["accrued_days"] == 8
        assert advice["principal_purchase_cents"] == 98617400
        assert advice["accrued_interest_cents"] == 130667
        assert advice["escrow_funding_cents"] == 0
        assert advice["service_release_premium_cents"] == 0
        assert advice["net_wire_cents"] == 98744567

        fixtures.settle_purchase_advice(staged["advice_id"], "WIRE-9101")

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["open_mandatory_exposure_cents"] == 0
        assert seller["net_funded_cents"] == 98744567
        assert seller["fee_receivable_cents"] == 0
        assert fixtures.read_escrow_transfers(staged["loan_id"]) == []
