"""State machines that revisit earlier states instead of moving forward only."""

from test_helpers import (
    ANALYST,
    REVIEWER,
    api_client,
    assert_defect,
    assert_seller,
    assert_suspense_condition,
    fixtures,
    validate_success,
)


class TestLoanRevisitsReviewTwice:
    """A file suspended twice for two different causes returns to review twice."""

    @staticmethod
    def _loan_in_review() -> dict:
        return fixtures.setup_loan_in_review(
            with_adjustment=False,
            commitment_overrides={"notional_amount_cents": 40000000},
            loan_overrides={
                "seller_loan_number": "HP-4001",
                "note_amount_cents": 40000000,
                "servicing_election": "RELEASED",
                "escrow_balance_cents": 320000,
                "closing_date": "2026-07-20",
            },
        )

    def test_cure_then_clearance_drive_the_review_cycle_counter_to_two(self):
        """A cured defect and then a cleared condition each restart the review.

        The medium defect carries a ten-day cure window closing 2026-08-11 and the
        condition a seven-day window closing 2026-08-08, so both resolutions land
        on time at the 2026-08-01 clock. Each resolution empties both open-item
        families while the file sits suspended, so the counter advances twice and
        the file ends in review rather than cleared.

        PRD: "That counter is the meter on the cure cycle `IN_REVIEW → SUSPENDED →
        IN_REVIEW`, which a file may traverse any number of times."

        Design: Difficulty/non_linear_state_machine/loan_suspense_cycle_revisits_in_review_twice
        """
        staged = self._loan_in_review()
        loan_id = staged["loan_id"]
        seller_id = staged["seller_id"]

        defect = fixtures.record_defect(
            loan_id, "DOC-FLOOD-CERT-MISSING", "DOCUMENTATION", "MEDIUM"
        )
        assert_defect(defect)
        assert defect["classification"] == "CURABLE"
        assert defect["cure_deadline_at"] == "2026-08-11T00:00:00.000Z"
        assert fixtures.read_loan(loan_id)["purchase_status"] == "SUSPENDED"

        cured = fixtures.cure_defect(
            defect["id"], seller_id, "DOC-FLOOD-CERT-2026-08-01"
        )
        assert cured["status"] == "CURED"
        after_first_cycle = fixtures.read_loan(loan_id)
        assert after_first_cycle["purchase_status"] == "IN_REVIEW"
        assert after_first_cycle["review_cycle_count"] == 1

        condition = fixtures.add_suspense_condition(
            loan_id, "SC-MISSING-NOTE-ENDORSEMENT"
        )
        assert_suspense_condition(condition)
        assert condition["due_at"] == "2026-08-08T00:00:00.000Z"
        assert fixtures.read_loan(loan_id)["purchase_status"] == "SUSPENDED"

        cleared = fixtures.clear_suspense_condition(condition["id"], "END-2026-08-01")
        assert cleared["status"] == "CLEARED"

        loan = fixtures.read_loan(loan_id)
        assert loan["review_cycle_count"] == 2
        assert loan["open_defect_count"] == 0
        assert loan["open_suspense_count"] == 0
        assert loan["purchase_status"] == "IN_REVIEW"

    def test_clearing_after_the_second_cycle_leaves_the_counter_alone(self):
        """Clearing for purchase is a separate explicit step, not a cycle.

        Once both open-item families are empty the file is merely back in review;
        the purchase reviewer still has to clear it, and that clearance is not a
        cure cycle, so the counter stays at two.

        PRD: "If open items remain in either family, the loan stays `SUSPENDED`
        and `review_cycle_count` is untouched."

        Design: Difficulty/non_linear_state_machine/loan_suspense_cycle_revisits_in_review_twice
        """
        staged = self._loan_in_review()
        loan_id = staged["loan_id"]
        seller_id = staged["seller_id"]

        defect = fixtures.record_defect(
            loan_id, "DOC-FLOOD-CERT-MISSING", "DOCUMENTATION", "MEDIUM"
        )
        fixtures.cure_defect(defect["id"], seller_id, "DOC-FLOOD-CERT-2026-08-01")
        condition = fixtures.add_suspense_condition(
            loan_id, "SC-MISSING-NOTE-ENDORSEMENT"
        )
        fixtures.clear_suspense_condition(condition["id"], "END-2026-08-01")

        cleared_loan = validate_success(
            api_client.clear_loan(loan_id, REVIEWER), 200
        )

        assert cleared_loan["purchase_status"] == "CLEARED_FOR_PURCHASE"
        assert cleared_loan["review_cycle_count"] == 2


class TestSellerStandingCyclesUnderPinnedApproval:
    """Delivery standing walks a cycle while the approval decision stands still."""

    @staticmethod
    def _approved_seller_with_one_lock() -> dict:
        return fixtures.setup_locked_commitment(
            with_adjustment=False,
            commitment_overrides={"notional_amount_cents": 40000000},
        )

    def test_watch_then_manual_suspension_leaves_approval_and_locks_intact(self):
        """Watching and then suspending never touches the approval dimension.

        Both manual actions rewrite `delivery_standing` alone: the seller stays
        approved on the standard tier, the suspension records the manual reason,
        and the untouched lock survives because a manual suspension cancels
        nothing.

        PRD: "`PLACE_ON_WATCH` moves `GOOD_STANDING → WATCH`; a seller on watch
        may still lock and deliver, because only `SUSPENDED`, `TERMINATED` and
        `NOT_ELIGIBLE` block delivery."

        Design: Difficulty/non_linear_state_machine/seller_delivery_standing_cycles_while_approval_status_pinned
        """
        staged = self._approved_seller_with_one_lock()
        seller_id = staged["seller_id"]

        watched = validate_success(
            api_client.apply_standing_action(
                seller_id, {"action": "PLACE_ON_WATCH"}, ANALYST
            ),
            200,
        )
        assert_seller(watched)
        assert watched["delivery_standing"] == "WATCH"
        assert watched["approval_status"] == "APPROVED"
        assert watched["approval_tier"] == "STANDARD"
        assert watched["open_mandatory_exposure_cents"] == 40000000

        suspended = validate_success(
            api_client.apply_standing_action(seller_id, {"action": "SUSPEND"}, ANALYST),
            200,
        )
        assert suspended["delivery_standing"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "MANUAL_COUNTERPARTY_ACTION"
        assert suspended["approval_status"] == "APPROVED"
        assert suspended["approval_tier"] == "STANDARD"
        assert suspended["open_mandatory_exposure_cents"] == 40000000

        commitment = fixtures.read_commitment(staged["commitment_id"])
        assert commitment["status"] == "LOCKED"
        assert commitment["cancelled_amount_cents"] == 0
        assert commitment["pair_off_fee_cents"] == 0

    def test_reinstatement_returns_the_seller_to_good_standing_and_clears_the_reason(
        self,
    ):
        """The cycle closes back on good standing with the reason wiped out.

        Walking watch, suspension and reinstatement returns `delivery_standing`
        to the value it held right after approval, clears the recorded reason, and
        never disturbs the approval decision or the seller's mandatory exposure.

        PRD: "`REINSTATE` moves either `WATCH → GOOD_STANDING` or `SUSPENDED →
        GOOD_STANDING` and clears `suspension_reason` back to null."

        Design: Difficulty/non_linear_state_machine/seller_delivery_standing_cycles_while_approval_status_pinned
        """
        staged = self._approved_seller_with_one_lock()
        seller_id = staged["seller_id"]

        fixtures.apply_standing_action(seller_id, "PLACE_ON_WATCH")
        fixtures.apply_standing_action(seller_id, "SUSPEND")

        reinstated = validate_success(
            api_client.apply_standing_action(
                seller_id, {"action": "REINSTATE"}, ANALYST
            ),
            200,
        )

        assert reinstated["delivery_standing"] == "GOOD_STANDING"
        assert reinstated["suspension_reason"] is None
        assert reinstated["approval_status"] == "APPROVED"
        assert reinstated["approval_tier"] == "STANDARD"
        assert reinstated["open_mandatory_exposure_cents"] == 40000000
        assert fixtures.read_commitment(staged["commitment_id"])["status"] == "LOCKED"
