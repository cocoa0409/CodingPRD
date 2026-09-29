"""Acceptance reports the state precondition ahead of the budget shortfall."""

import pytest

from test_helpers import (
    UPC_1,
    AmortizationMethod,
    ApiErrorId,
    DealState,
    fixtures,
    make_retailer_buyer_headers,
    validate_error,
)
from test_helpers import factories as F
from test_helpers.assertions import assert_quote_ladder, assert_version_unchanged, expected_quote

BUDGET_CENTS = 100000
FEE_PER_STORE_CENTS = 50000
STORE_COUNT = 400


@pytest.fixture
def undecided_review_with_oversized_deal(api):
    """A proposed deal whose quote dwarfs the budget, on a review that is still open.

    Both the priority-7 state precondition and the priority-12 fiscal limit are
    violated by the same acceptance request.
    """
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(
        api, retailer["id"], principal_overrides={"slotting_budget_cents": BUDGET_CENTS}
    )
    principal = bundle["principal"]
    item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1)
    review = fixtures.opened_review(api, retailer["id"], new_item_slots=2)
    presentation = fixtures.submitted_presentation(
        api, review["id"], principal["id"], [item["id"]]
    )
    deal = fixtures.proposed_deal(
        api,
        presentation["id"],
        fee_per_store_cents=FEE_PER_STORE_CENTS,
        store_count_in_scope=STORE_COUNT,
        item_count_in_scope=1,
        forecast_annual_units=0,
        amortization_periods=4,
        amortization_method=AmortizationMethod.FORECAST_STRAIGHT,
    )
    return {
        "retailer": retailer,
        "principal": principal,
        "item": item,
        "review": review,
        "presentation": presentation,
        "deal": deal,
    }


def attempt_accept(api, scope):
    principal = fixtures.get_principal(api, scope["principal"]["id"])
    return api.accept_deal(
        scope["deal"]["id"],
        F.accept_payload(principal["version"]),
        make_retailer_buyer_headers(scope["retailer"]["id"]),
    )


class TestAcceptancePrecedenceStateBeforeBudget:
    def test_both_rules_are_genuinely_violated_by_the_same_request(
        self, api, undecided_review_with_oversized_deal
    ):
        """The review is still open and the standing quote is two hundred times the budget.

        PRD: "`quoted_fee_cents` is `net_before_admin_cents` plus `admin_fee_cents`."

        Design: Difficulty/priority_pair_validation_conflict/deal_accept_state_precondition_beats_slotting_budget_shortfall
        """
        deal = fixtures.get_deal(api, undecided_review_with_oversized_deal["deal"]["id"])
        expected = expected_quote(FEE_PER_STORE_CENTS, STORE_COUNT, 1, 0)

        assert deal["gross_fee_cents"] == 20000000
        assert deal["net_before_admin_cents"] == 20000000
        assert deal["admin_fee_cents"] == 300000
        assert deal["quoted_fee_cents"] == expected["quoted_fee_cents"] == 20300000
        assert_quote_ladder(deal, FEE_PER_STORE_CENTS, STORE_COUNT, 1, 0)

        principal = fixtures.get_principal(
            api, undecided_review_with_oversized_deal["principal"]["id"]
        )
        assert principal["slotting_committed_cents"] == 0
        assert (
            principal["slotting_committed_cents"] + deal["quoted_fee_cents"]
            > principal["slotting_budget_cents"]
        )

    def test_the_state_precondition_is_the_only_error_reported(
        self, api, undecided_review_with_oversized_deal
    ):
        """The earlier band wins, so the budget breach is never mentioned.

        PRD: "Validations are evaluated in ascending priority bands, and the **first**
        violated rule determines the response."

        Design: Difficulty/priority_pair_validation_conflict/deal_accept_state_precondition_beats_slotting_budget_shortfall
        """
        response = attempt_accept(api, undecided_review_with_oversized_deal)

        validate_error(response, ApiErrorId.REVIEW_NOT_DECIDED, 409)
        assert ApiErrorId.SLOTTING_BUDGET_EXCEEDED not in response.text

    def test_the_rejected_acceptance_leaves_no_trace(
        self, api, undecided_review_with_oversized_deal
    ):
        """No fee is frozen, nothing is committed, and no version is bumped.

        PRD: "the awarding review's `status` must be `DECIDED`, otherwise
        `ERR_REVIEW_NOT_DECIDED`"

        Design: Difficulty/priority_pair_validation_conflict/deal_accept_state_precondition_beats_slotting_budget_shortfall
        """
        before = fixtures.get_principal(
            api, undecided_review_with_oversized_deal["principal"]["id"]
        )
        attempt_accept(api, undecided_review_with_oversized_deal)

        deal = fixtures.get_deal(api, undecided_review_with_oversized_deal["deal"]["id"])
        assert deal["state"] == DealState.PROPOSED
        # A refused acceptance freezes nothing.
        assert not deal["accepted_fee_cents"]

        after = fixtures.get_principal(
            api, undecided_review_with_oversized_deal["principal"]["id"]
        )
        assert after["slotting_committed_cents"] == 0
        assert_version_unchanged(before, after)

    def test_deciding_the_review_unmasks_the_fiscal_limit(
        self, api, undecided_review_with_oversized_deal
    ):
        """The identical call now reports the budget breach that was live all along.

        PRD: "the principal's `slotting_committed_cents` plus this deal's `quoted_fee_cents`
        must not exceed its `slotting_budget_cents`, otherwise `ERR_SLOTTING_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/deal_accept_state_precondition_beats_slotting_budget_shortfall
        """
        scope = undecided_review_with_oversized_deal
        fixtures.lock_and_decide(
            api, scope["review"]["id"], scope["retailer"]["id"], [scope["item"]["id"]]
        )

        response = attempt_accept(api, scope)
        validate_error(response, ApiErrorId.SLOTTING_BUDGET_EXCEEDED, 409)
        assert ApiErrorId.REVIEW_NOT_DECIDED not in response.text

        deal = fixtures.get_deal(api, scope["deal"]["id"])
        assert deal["state"] == DealState.PROPOSED
        principal = fixtures.get_principal(api, scope["principal"]["id"])
        assert principal["slotting_committed_cents"] == 0
