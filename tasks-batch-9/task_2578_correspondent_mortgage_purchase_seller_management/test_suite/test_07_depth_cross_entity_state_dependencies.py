"""The same request refused and then accepted, because another entity moved."""

from test_helpers import (
    REVIEWER,
    REVIEWER_THIRD,
    TRADER,
    ApiErrorId,
    api_client,
    assert_commitment,
    assert_escrow_transfer,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLockGatedBySellerStanding:
    """A lock request's fate is decided on the seller row, not on the payload."""

    @staticmethod
    def _approved_but_suspended_seller() -> dict:
        staged = fixtures.setup_lock_ready_seller()
        fixtures.apply_standing_action(staged["seller_id"], "SUSPEND")
        return staged

    @staticmethod
    def _lock_request(staged: dict):
        return api_client.create_commitment(
            factories.commitment_payload(
                staged["seller_id"],
                staged["product_id"],
                notional_amount_cents=40000000,
            ),
            TRADER,
        )

    def test_a_suspended_seller_cannot_be_locked_even_though_it_is_approved(self):
        """Approval alone is not enough; the standing dimension bars the lock.

        The seller cleared every approval gate and is still approved, but a manual
        suspension sits on its delivery standing, so the lock desk is refused and
        no commitment comes into existence.

        PRD: "Its `delivery_standing` must be `GOOD_STANDING` or `WATCH`; a seller
        sitting at `NOT_ELIGIBLE`, `SUSPENDED` or `TERMINATED` is refused with
        `ERR_SELLER_DELIVERY_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/commitment_lock_gated_by_seller_delivery_standing_then_allowed_after_reinstate
        """
        staged = self._approved_but_suspended_seller()

        validate_error(
            self._lock_request(staged), ApiErrorId.ERR_SELLER_DELIVERY_SUSPENDED, 409
        )

        commitments, meta = validate_paginated(
            api_client.list_commitments(TRADER, {"seller_id": staged["seller_id"]})
        )
        assert commitments == []
        assert meta["total_count"] == 0

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["approval_status"] == "APPROVED"
        assert seller["delivery_standing"] == "SUSPENDED"
        assert seller["open_mandatory_exposure_cents"] == 0

    def test_reinstating_the_seller_lets_the_identical_lock_through_and_prices_it(self):
        """Nothing about the payload changes, yet the second attempt is priced.

        Once the seller is back in good standing the identical body is accepted,
        and the lock prices at 100.880: the 101.250 base takes 25 basis points for
        the mandatory obligation, 12 back for the 30-day term and 50 back for the
        matching grid row.

        PRD: "The three contributions are added together as basis points,
        converted to a price percentage by dividing by 100, and added to the
        product's `base_price_pct`."

        Design: Difficulty/cross_entity_state_dependency/commitment_lock_gated_by_seller_delivery_standing_then_allowed_after_reinstate
        """
        staged = self._approved_but_suspended_seller()
        validate_error(
            self._lock_request(staged), ApiErrorId.ERR_SELLER_DELIVERY_SUSPENDED, 409
        )

        reinstated = fixtures.apply_standing_action(staged["seller_id"], "REINSTATE")
        assert reinstated["delivery_standing"] == "GOOD_STANDING"
        assert reinstated["suspension_reason"] is None

        commitment = validate_success(self._lock_request(staged), 201)

        assert_commitment(commitment)
        assert commitment["status"] == "LOCKED"
        assert commitment["commitment_price_pct"] == 100.880
        assert commitment["lock_term_days"] == 30
        assert commitment["llpa_bps_applied"] == -50
        assert commitment["available_amount_cents"] == 40000000
        assert commitment["tolerance_cents"] == 800000

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["open_mandatory_exposure_cents"] == 40000000


class TestEscrowCompletionGatedByLoanState:
    """A transfer that is perfectly completable is blocked by its parent loan."""

    @staticmethod
    def _pending_transfer_under_a_demand() -> dict:
        staged = fixtures.setup_loan_in_review(
            commitment_overrides={"notional_amount_cents": 40000000},
            loan_overrides={
                "seller_loan_number": "HP-8001",
                "note_amount_cents": 40000000,
                "servicing_election": "RELEASED",
                "escrow_balance_cents": 320000,
                "closing_date": "2026-07-20",
            },
        )
        defect = fixtures.record_defect(
            staged["loan_id"], "CR-DTI-OVERSTATED", "CREDIT", "HIGH"
        )
        fixtures.waive_defect(defect["id"], -25)
        fixtures.clear_loan_for_purchase(staged["loan_id"])

        fixtures.setup_clock("2026-08-05T00:00:00Z")
        advice = fixtures.issue_purchase_advice(staged["loan_id"])
        staged["advice"] = fixtures.settle_purchase_advice(advice["id"], "WIRE-8001")
        staged["transfer"] = fixtures.read_pending_escrow_transfer(staged["loan_id"])

        fixtures.setup_clock("2026-08-10T00:00:00Z")
        staged["demand"] = fixtures.issue_repurchase_demand(
            staged["loan_id"], "DEFECT", "RD-8001", defect["id"]
        )
        staged["defect_id"] = defect["id"]
        return staged

    def test_escrow_cannot_be_moved_while_the_file_is_being_pulled_back(self):
        """The transfer itself is faultless: pending, funded and not yet due.

        The advice wired 41,184,056 after the waived defect took 100,000 off the
        price, leaving a pending 320,000 transfer due 2026-08-20 which the
        2026-08-10 clock is comfortably inside. The refusal comes from the loan,
        which sits under a repurchase demand.

        PRD: "The loan must be in `PURCHASED` status: a loan whose
        `purchase_status` is `REPURCHASE_DEMANDED` or `REPURCHASED` is refused
        with `ERR_LOAN_UNDER_REPURCHASE`, because escrow may not be moved to the
        investor while the file is being pulled back to the seller."

        Design: Difficulty/cross_entity_state_dependency/escrow_completion_gated_by_loan_repurchase_state_then_allowed_after_rescind
        """
        staged = self._pending_transfer_under_a_demand()

        assert staged["advice"]["net_wire_cents"] == 41184056
        assert staged["advice"]["defect_price_adjustment_cents"] == -100000

        response = api_client.complete_escrow_transfer(
            staged["transfer"]["id"], {"goodbye_letter_reference": "GB-8001"}, REVIEWER
        )

        validate_error(response, ApiErrorId.ERR_LOAN_UNDER_REPURCHASE, 409)

        transfer = fixtures.read_escrow_transfers(staged["loan_id"])[0]
        assert transfer["status"] == "PENDING"
        assert transfer["completed_at"] is None
        assert transfer["transfer_due_at"] == "2026-08-20T00:00:00.000Z"

    def test_rescinding_the_demand_lets_the_same_completion_through(self):
        """Withdrawing the accusation returns the loan and unblocks the transfer.

        Rescission puts the loan back into purchased without unwinding any money,
        so the funded total still reads 41,184,056 and the identical completion
        call now books the transfer at the 2026-08-10 clock.

        PRD: "Rescission moves the demand `ISSUED → RESCINDED` or `APPEALED →
        RESCINDED`, a terminal status, cascades the loan `REPURCHASE_DEMANDED →
        PURCHASED`, and removes the loan from the defective population this demand
        had contributed to the seller's scorecard."

        Design: Difficulty/cross_entity_state_dependency/escrow_completion_gated_by_loan_repurchase_state_then_allowed_after_rescind
        """
        staged = self._pending_transfer_under_a_demand()
        validate_error(
            api_client.complete_escrow_transfer(
                staged["transfer"]["id"],
                {"goodbye_letter_reference": "GB-8001"},
                REVIEWER,
            ),
            ApiErrorId.ERR_LOAN_UNDER_REPURCHASE,
            409,
        )

        rescinded = validate_success(
            api_client.decide_repurchase_demand(
                staged["demand"]["id"], {"decision": "RESCIND"}, REVIEWER_THIRD
            ),
            200,
        )
        assert rescinded["status"] == "RESCINDED"
        assert fixtures.read_loan(staged["loan_id"])["purchase_status"] == "PURCHASED"
        assert fixtures.read_seller(staged["seller_id"])["net_funded_cents"] == 41184056

        completed = validate_success(
            api_client.complete_escrow_transfer(
                staged["transfer"]["id"],
                {"goodbye_letter_reference": "GB-8001"},
                REVIEWER,
            ),
            200,
        )

        assert_escrow_transfer(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] == "2026-08-10T00:00:00.000Z"
        assert completed["goodbye_letter_reference"] == "GB-8001"
