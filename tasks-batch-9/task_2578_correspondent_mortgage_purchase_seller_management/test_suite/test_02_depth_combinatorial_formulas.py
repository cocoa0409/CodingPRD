"""Purchase-advice arithmetic: nested rounding and pinned evaluation order."""

from test_helpers import (
    REVIEWER,
    api_client,
    assert_purchase_advice,
    fixtures,
    validate_success,
)


class TestAdvicePerComponentRounding:
    """Each money component rounds on its own before the components are summed."""

    @staticmethod
    def _cleared_loan_with_two_waived_defects() -> dict:
        staged = fixtures.setup_loan_in_review(
            commitment_overrides={"notional_amount_cents": 40000000},
            loan_overrides={
                "seller_loan_number": "HP-2001",
                "note_amount_cents": 30000500,
                "note_rate_pct": 6.500,
                "servicing_election": "RELEASED",
                "escrow_balance_cents": 320000,
                "closing_date": "2026-07-20",
            },
        )
        credit_defect = fixtures.record_defect(
            staged["loan_id"], "CR-DTI-OVERSTATED", "CREDIT", "HIGH"
        )
        document_defect = fixtures.record_defect(
            staged["loan_id"], "DOC-FLOOD-CERT-MISSING", "DOCUMENTATION", "MEDIUM"
        )
        fixtures.waive_defect(credit_defect["id"], -25)
        fixtures.waive_defect(document_defect["id"], -13)
        fixtures.clear_loan_for_purchase(staged["loan_id"])
        fixtures.setup_clock("2026-08-05T00:00:00Z")
        return staged

    def test_each_money_component_is_rounded_on_its_own(self):
        """A note of 30,000,500 cents exposes every component's own rounding.

        Sixteen accrued days at 6.500 percent, escrow of 320,000 released, a
        1.250 percent service release premium and two waived defects each land on
        their own rounded whole-cent figure before anything is added up.

        PRD: "Summing exact values first and rounding once at the end is the
        wrong order and can differ by a cent."

        Design: Difficulty/combinatorial_formula/purchase_advice_per_component_rounding_vs_sum_then_round
        """
        staged = self._cleared_loan_with_two_waived_defects()

        advice = validate_success(
            api_client.create_purchase_advice(
                staged["loan_id"],
                {"expected_loan_version": fixtures.loan_version(staged["loan_id"])},
                REVIEWER,
            ),
            201,
        )

        assert_purchase_advice(advice)
        assert advice["accrued_days"] == 16
        assert advice["volume_incentive_bps"] == 0
        assert advice["final_purchase_price_pct"] == 100.880
        assert advice["principal_purchase_cents"] == 30264504
        assert advice["accrued_interest_cents"] == 86668
        assert advice["escrow_funding_cents"] == 320000
        assert advice["service_release_premium_cents"] == 375006
        assert advice["wire_fee_cents"] == 3500

    def test_net_wire_takes_the_per_component_total_not_the_sum_then_round_total(self):
        """The pinned order yields 30,928,676 cents, one cent under the wrong order.

        The two waived defects contribute -25 and -13 basis points, each hit
        rounded on its own before the sum, for a combined price concession of
        -114,002 cents. Adding the independently rounded components produces
        30,928,676; summing the exact rationals first and rounding once would
        produce 30,928,677.

        PRD: "A `WAIVED` defect's hit is the `price_adjustment_bps` negotiated at
        waiver; an `EXPIRED` defect's hit is the fixed penalty of -50 basis points
        regardless of severity."

        Design: Difficulty/combinatorial_formula/purchase_advice_per_component_rounding_vs_sum_then_round
        """
        staged = self._cleared_loan_with_two_waived_defects()

        advice = validate_success(
            api_client.create_purchase_advice(
                staged["loan_id"],
                {"expected_loan_version": fixtures.loan_version(staged["loan_id"])},
                REVIEWER,
            ),
            201,
        )

        assert advice["defect_price_adjustment_cents"] == -114002
        assert advice["net_wire_cents"] == 30928676
        assert advice["net_wire_cents"] != 30928677
        assert advice["status"] == "ISSUED"

        loan = fixtures.read_loan(staged["loan_id"])
        assert loan["advice_count"] == 1


class TestVolumeIncentiveEvaluationOrder:
    """Month-to-date volume is measured over loans already purchased only."""

    @staticmethod
    def _prior_purchase_then_a_cleared_loan() -> dict:
        staged = fixtures.setup_locked_commitment(
            commitment_overrides={
                "commitment_type": "BEST_EFFORTS",
                "notional_amount_cents": 70000000,
            }
        )
        seller_id = staged["seller_id"]
        prior_line = staged["commitment"]
        test_line = fixtures.setup_commitment(
            seller_id, staged["product_id"], notional_amount_cents=40000000
        )

        prior_loan = fixtures.deliver_loan(
            prior_line["id"],
            seller_id,
            seller_loan_number="HP-3001",
            note_amount_cents=70000000,
            note_rate_pct=6.250,
            escrow_balance_cents=0,
            closing_date="2026-07-25",
        )
        test_loan = fixtures.deliver_loan(
            test_line["id"],
            seller_id,
            seller_loan_number="HP-3002",
            note_amount_cents=40000000,
            servicing_election="RELEASED",
            escrow_balance_cents=320000,
            closing_date="2026-07-20",
        )

        for loan in (prior_loan, test_loan):
            fixtures.open_loan_review(loan["id"])
            fixtures.clear_loan_for_purchase(loan["id"])

        fixtures.setup_clock("2026-08-03T00:00:00Z")
        prior_advice = fixtures.issue_purchase_advice(prior_loan["id"])
        fixtures.settle_purchase_advice(prior_advice["id"], "WIRE-3001")

        fixtures.setup_clock("2026-08-05T00:00:00Z")
        staged["prior_loan_id"] = prior_loan["id"]
        staged["test_loan_id"] = test_loan["id"]
        return staged

    def test_month_to_date_volume_excludes_the_loan_being_priced(self):
        """70,000,000 of prior volume stays under the first tier, so no rebate.

        Were the 40,000,000 loan under advice counted into its own month-to-date
        measurement the total would read 110,000,000 and earn 5 basis points; the
        advice instead records zero and wires 41,284,056 rather than 41,304,056.

        PRD: "This evaluation order is pinned deliberately: the incentive raises
        the price, the price raises the proceeds, and the proceeds would raise the
        volume that selects the incentive, so the tier must be measured only over
        volume already purchased."

        Design: Difficulty/combinatorial_formula/volume_incentive_excludes_loan_under_advice_ordering
        """
        staged = self._prior_purchase_then_a_cleared_loan()

        prior_loan = fixtures.read_loan(staged["prior_loan_id"])
        assert prior_loan["purchase_status"] == "PURCHASED"
        assert prior_loan["note_amount_cents"] == 70000000

        advice = validate_success(
            api_client.create_purchase_advice(
                staged["test_loan_id"],
                {
                    "expected_loan_version": fixtures.loan_version(
                        staged["test_loan_id"]
                    )
                },
                REVIEWER,
            ),
            201,
        )

        assert advice["volume_incentive_bps"] == 0
        assert advice["final_purchase_price_pct"] == 100.880
        assert advice["net_wire_cents"] == 41284056
        assert advice["net_wire_cents"] != 41304056

    def test_components_of_the_unrebated_advice_are_priced_off_the_locked_price(self):
        """With no rebate the advice prices straight off the locked 100.880.

        Principal is 40,352,000, sixteen accrued days at 6.500 percent give
        115,556 of interest, the released escrow adds 320,000 and the 1.250
        percent premium adds 500,000.

        PRD: "The resulting `volume_incentive_bps` is 0 below 100,000,000 cents
        of month-to-date balance, 5 at or above 100,000,000 cents, and 10 at or
        above 250,000,000 cents."

        Design: Difficulty/combinatorial_formula/volume_incentive_excludes_loan_under_advice_ordering
        """
        staged = self._prior_purchase_then_a_cleared_loan()

        advice = validate_success(
            api_client.create_purchase_advice(
                staged["test_loan_id"],
                {
                    "expected_loan_version": fixtures.loan_version(
                        staged["test_loan_id"]
                    )
                },
                REVIEWER,
            ),
            201,
        )

        assert_purchase_advice(advice)
        assert advice["principal_purchase_cents"] == 40352000
        assert advice["accrued_days"] == 16
        assert advice["accrued_interest_cents"] == 115556
        assert advice["service_release_premium_cents"] == 500000
        assert advice["escrow_funding_cents"] == 320000
        assert advice["defect_price_adjustment_cents"] == 0
