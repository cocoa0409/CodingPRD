"""Inclusive floors taken exactly, and an empty set closed without dividing."""

from test_helpers import (
    ANALYST,
    ApiErrorId,
    api_client,
    assert_seller,
    assert_seller_scorecard,
    fixtures,
    validate_error,
    validate_success,
)


class TestTangibleNetWorthFloor:
    """The net-worth floor of 250,000,000 cents is inclusive to the cent."""

    @staticmethod
    def _seller_awaiting_decision(
        tangible_net_worth_cents: int, legal_name: str, tin: str
    ) -> dict:
        fixtures.setup_clock("2026-08-01T00:00:00Z")
        staged = fixtures.setup_seller_under_review(
            seller_overrides={
                "legal_name": legal_name,
                "tin": tin,
                "seller_type": "BANK",
            },
            statement_overrides={
                "tangible_net_worth_cents": tangible_net_worth_cents,
                "liquid_assets_cents": 60000000,
            },
        )
        fixtures.complete_qc_review(staged["qc_review"]["id"], 1, 0)
        return staged

    def test_net_worth_exactly_at_the_floor_approves_and_sets_the_leverage_limit(self):
        """250,000,000 exactly clears the gate and buys ten times leverage.

        The applicant sits precisely on the floor, so approval goes through, and
        because the governing review passed outright the limit is ten times the
        frozen net worth — 2,500,000,000 cents, comfortably under the platform
        cap, so the cap does not bind.

        PRD: "`mandatory_exposure_limit_cents` is computed as the smaller of two
        figures: the approved tangible net worth multiplied by a leverage
        multiplier, and an absolute platform cap of 5,000,000,000 cents (fifty
        million dollars)."

        Design: Difficulty/boundary_precision_check/tangible_net_worth_exactly_at_minimum_approves_and_one_cent_below_fails
        """
        staged = self._seller_awaiting_decision(
            250000000, "Boundary Lending AT LIMIT LLC", "823391045"
        )

        approved = validate_success(
            api_client.decide_seller_approval(
                staged["seller_id"], {"decision": "APPROVE"}, ANALYST
            ),
            200,
        )

        assert_seller(approved)
        assert approved["approval_status"] == "APPROVED"
        assert approved["delivery_standing"] == "GOOD_STANDING"
        assert approved["approval_tier"] == "STANDARD"
        assert approved["servicing_retained_eligible"] is True
        assert approved["approved_tangible_net_worth_cents"] == 250000000
        assert approved["mandatory_exposure_limit_cents"] == 2500000000

    def test_net_worth_one_cent_below_the_floor_is_refused(self):
        """249,999,999 is short by a single cent and buys nothing at all.

        The same posture with one cent less of net worth is refused, and the
        refusal leaves the applicant exactly where it was: still under review,
        still not eligible to deliver, still carrying no exposure limit.

        PRD: "The governing statement's `tangible_net_worth_cents` must be at
        least 250,000,000 cents — two and a half million dollars — with a value
        exactly at the floor passing and anything below it failing with
        `ERR_NET_WORTH_BELOW_MINIMUM`."

        Design: Difficulty/boundary_precision_check/tangible_net_worth_exactly_at_minimum_approves_and_one_cent_below_fails
        """
        staged = self._seller_awaiting_decision(
            249999999, "Boundary Lending BELOW LLC", "823391046"
        )

        response = api_client.decide_seller_approval(
            staged["seller_id"], {"decision": "APPROVE"}, ANALYST
        )

        validate_error(response, ApiErrorId.ERR_NET_WORTH_BELOW_MINIMUM, 409)

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["approval_status"] == "UNDER_REVIEW"
        assert seller["delivery_standing"] == "NOT_ELIGIBLE"
        assert seller["mandatory_exposure_limit_cents"] == 0
        assert seller["approved_tangible_net_worth_cents"] == 0


class TestEmptyScorecardClose:
    """A period with nothing purchased closes without dividing by zero."""

    @staticmethod
    def _open_scorecard_over_an_empty_period() -> dict:
        fixtures.setup_clock("2026-06-15T00:00:00Z")
        staged = fixtures.setup_approved_seller()
        scorecard = fixtures.open_scorecard(
            staged["seller_id"], "2026-06-01", "2026-06-30"
        )
        fixtures.setup_clock("2026-07-01T00:00:00Z")
        staged["scorecard"] = scorecard
        return staged

    def test_an_empty_scored_population_records_zero_rates_and_no_grade(self):
        """Nothing was purchased, so both rates read zero and the grade is unrated.

        A naive grader would read a zero rate as an A; the empty population is
        instead reported as ungraded, with every count and balance at zero and no
        division attempted.

        PRD: "When the scored population is empty, both rates are recorded as 0
        and no division is attempted; the `grade` is `UNRATED`."

        Design: Difficulty/boundary_precision_check/zero_purchase_scorecard_close_empty_set_guard
        """
        staged = self._open_scorecard_over_an_empty_period()

        closed = validate_success(
            api_client.close_scorecard(staged["scorecard"]["id"], ANALYST, {}), 200
        )

        assert_seller_scorecard(closed)
        assert closed["purchased_loan_count"] == 0
        assert closed["purchased_upb_cents"] == 0
        assert closed["defective_loan_count"] == 0
        assert closed["defective_upb_cents"] == 0
        assert closed["defect_rate_bps"] == 0
        assert closed["upb_weighted_defect_rate_bps"] == 0
        assert closed["grade"] == "UNRATED"

    def test_the_empty_close_takes_no_action_against_the_seller(self):
        """The small-sample floor stops the ladder before any action is chosen.

        With no purchased loans the count is below the two-loan floor, so the
        ladder answers none, the breach flag stays down, and the seller keeps its
        good standing while adopting the ungraded result.

        PRD: "If `purchased_loan_count` is less than 2, the action is `NONE` — the
        small-sample floor overrides everything below, so even a 10000 basis point
        rate on a single loan takes no action."

        Design: Difficulty/boundary_precision_check/zero_purchase_scorecard_close_empty_set_guard
        """
        staged = self._open_scorecard_over_an_empty_period()

        closed = validate_success(
            api_client.close_scorecard(staged["scorecard"]["id"], ANALYST, {}), 200
        )

        assert closed["breach"] is False
        assert closed["standing_action_applied"] == "NONE"
        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] == "2026-07-01T00:00:00.000Z"

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["delivery_standing"] == "GOOD_STANDING"
        assert seller["current_scorecard_grade"] == "UNRATED"
        assert seller["current_defect_rate_bps"] == 0
