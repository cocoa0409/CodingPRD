"""The statement's line set is filtered on authorization state, not on whether an item shipped."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    AuthorizationState,
    PRIMARY_CATEGORY,
    SettlementStateAuthorization,
    UPC_1,
    UPC_2,
    fixtures,
    get_success_data,
)
from test_helpers.assertions import (
    assert_commission_statement,
    assert_statement_walk,
    expected_straight_amortization,
)

FEE_PER_STORE_CENTS = 12500
STORE_COUNT = 400
ITEM_COUNT = 2
PERIODS = 4
ACCEPTED_FEE_CENTS = 10150000
SHARE_CENTS = 5075000
PERIOD_AMOUNT_CENTS = 2537500
I1_LIST_PRICE_CENTS = 2010
I2_LIST_PRICE_CENTS = 2000
CASE_VOLUME = 1000
I1_SHIPPED_CENTS = 2010000
I1_COMMISSION_CENTS = 100500
BASE_COMMISSION_BPS = 500
TIER_THRESHOLD_CENTS = 3000000
TIER_COMMISSION_BPS = 300


@pytest.fixture
def two_awarded_items_before_acceptance(api):
    """Both items are awarded but the deal is still PROPOSED, so both authorizations wait."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(api, retailer["id"])
    principal = bundle["principal"]
    first_item = fixtures.validated_item(
        api, principal["id"], retailer["id"], upc=UPC_1, list_price_cents=I1_LIST_PRICE_CENTS
    )
    second_item = fixtures.validated_item(
        api, principal["id"], retailer["id"], upc=UPC_2, list_price_cents=I2_LIST_PRICE_CENTS
    )
    review = fixtures.opened_review(api, retailer["id"])
    presentation = fixtures.submitted_presentation(
        api, review["id"], principal["id"], [first_item["id"], second_item["id"]]
    )
    deal = fixtures.proposed_deal(
        api,
        presentation["id"],
        fee_per_store_cents=FEE_PER_STORE_CENTS,
        store_count_in_scope=STORE_COUNT,
        item_count_in_scope=ITEM_COUNT,
        forecast_annual_units=0,
        amortization_periods=PERIODS,
    )
    fixtures.lock_and_decide(
        api, review["id"], retailer["id"], [first_item["id"], second_item["id"]]
    )
    return {
        "retailer": retailer,
        "principal": principal,
        "agreement": bundle["agreement"],
        "first_item": first_item,
        "second_item": second_item,
        "review": review,
        "deal": deal,
    }


def read_statement(api, scope):
    response = api.get_commission_statement(
        scope["principal"]["id"],
        ACCOUNT_MANAGER_HEADERS,
        {"retailer_id": scope["retailer"]["id"], "category_code": PRIMARY_CATEGORY},
    )
    return get_success_data(response, 200)


def accept(api, scope):
    return fixtures.accept_as_buyer(
        api, scope["deal"]["id"], scope["retailer"]["id"], scope["principal"]["id"]
    )


def authorization_for_item(api, scope, item_id):
    rows = fixtures.authorizations_for_review(api, scope["review"]["id"])
    return next(row for row in rows if row["item_id"] == item_id)


def ship_the_first_item(api, scope):
    """Post one full period against the first item's authorization only."""
    authorization = authorization_for_item(api, scope, scope["first_item"]["id"])
    return fixtures.post_period(
        api,
        authorization["id"],
        scope["retailer"]["id"],
        period_index=1,
        reported_store_count=STORE_COUNT,
        distributed_store_count=STORE_COUNT,
        reported_case_volume=CASE_VOLUME,
    )


class TestCommissionStatementLineSet:
    def test_pending_setup_authorizations_produce_no_lines_at_all(
        self, api, two_awarded_items_before_acceptance
    ):
        """Both items exist and are awarded, but neither authorization is live yet.

        PRD: "One line appears for each item of that principal that holds at least one
        authorization at the requested chain whose `authorization_state` is `AUTHORIZED`, `AT_RISK`
        or `DISCONTINUED` and whose awarding review's category matches the requested category."

        Design: Corner/calculations/commission_statement_lines_only_for_items_with_live_authorizations
        """
        scope = two_awarded_items_before_acceptance
        for item in (scope["first_item"], scope["second_item"]):
            authorization = authorization_for_item(api, scope, item["id"])
            assert authorization["authorization_state"] == AuthorizationState.PENDING_SETUP

        statement = read_statement(api, scope)

        assert statement["lines"] == []
        assert statement["total_shipped_cents"] == 0
        assert statement["total_commission_cents"] == 0

    def test_the_empty_statement_still_resolves_the_rate_card(
        self, api, two_awarded_items_before_acceptance
    ):
        """An empty line set is not a missing agreement: the rate terms are still echoed.

        PRD: "The response echoes `principal_id`, `retailer_id`, `category_code`, the resolved
        `agreement_id` and the three rate terms `base_commission_bps`, `tier_threshold_cents` and
        `tier_commission_bps`, then carries a `lines` array and the two totals
        `total_shipped_cents` and `total_commission_cents`."

        Design: Corner/calculations/commission_statement_lines_only_for_items_with_live_authorizations
        """
        scope = two_awarded_items_before_acceptance

        statement = read_statement(api, scope)

        assert_commission_statement(statement)
        assert statement["agreement_id"] == scope["agreement"]["id"]
        assert statement["base_commission_bps"] == BASE_COMMISSION_BPS
        assert statement["tier_threshold_cents"] == TIER_THRESHOLD_CENTS
        assert statement["tier_commission_bps"] == TIER_COMMISSION_BPS

    def test_acceptance_brings_both_authorizations_to_life_with_equal_shares(
        self, api, two_awarded_items_before_acceptance
    ):
        """10,150,000 splits evenly across two authorizations with no remainder.

        PRD: "The second hop allocates the money: `slotting_share_cents` distributes
        `accepted_fee_cents` across those authorizations by taking the base share as
        `accepted_fee_cents` divided by the number of linked authorizations, floored to whole
        cents, computing the remainder as `accepted_fee_cents` less the base share multiplied by
        that count, and giving one extra cent to each of the first *remainder* authorizations in an
        order defined by `created_at` ascending and then item `upc` ascending."

        Design: Corner/calculations/commission_statement_lines_only_for_items_with_live_authorizations
        """
        scope = two_awarded_items_before_acceptance

        accepted = accept(api, scope)

        assert accepted["gross_fee_cents"] == 10000000
        assert accepted["admin_fee_cents"] == 150000
        assert accepted["accepted_fee_cents"] == ACCEPTED_FEE_CENTS
        for item in (scope["first_item"], scope["second_item"]):
            authorization = authorization_for_item(api, scope, item["id"])
            assert authorization["authorization_state"] == AuthorizationState.AUTHORIZED
            assert authorization["settlement_state"] == (
                SettlementStateAuthorization.SLOTTING_AMORTIZING
            )
            assert authorization["slotting_share_cents"] == SHARE_CENTS

    def test_the_straight_line_period_amount_ignores_the_case_volume(
        self, api, two_awarded_items_before_acceptance
    ):
        """A quarter of 10,150,000 is 2,537,500 whatever the period shipped.

        PRD: "Under `FORECAST_STRAIGHT`, the base amount is `accepted_fee_cents` divided by
        `amortization_periods`, floored to whole cents."

        PRD: "The period's `reported_case_volume` is recorded on the ledger entry but has no effect
        at all on the amount."

        Design: Corner/calculations/commission_statement_lines_only_for_items_with_live_authorizations
        """
        scope = two_awarded_items_before_acceptance
        accept(api, scope)

        entry = ship_the_first_item(api, scope)

        assert entry["amortized_amount_cents"] == PERIOD_AMOUNT_CENTS
        assert (
            expected_straight_amortization(ACCEPTED_FEE_CENTS, PERIODS) == PERIOD_AMOUNT_CENTS
        )
        assert entry["reported_case_volume"] == CASE_VOLUME

    def test_the_item_that_never_shipped_still_gets_a_line(
        self, api, two_awarded_items_before_acceptance
    ):
        """Only one of the two authorizations has a posting, but both are live and both appear.

        PRD: "The shipped figure for a line is the sum of `reported_case_volume` over that item's
        live `POSTING` ledger entries, multiplied by the item's `list_price_cents`."

        Design: Corner/calculations/commission_statement_lines_only_for_items_with_live_authorizations
        """
        scope = two_awarded_items_before_acceptance
        accept(api, scope)
        ship_the_first_item(api, scope)

        statement = read_statement(api, scope)

        assert [line["item_id"] for line in statement["lines"]] == [
            scope["first_item"]["id"],
            scope["second_item"]["id"],
        ]
        assert [line["upc"] for line in statement["lines"]] == [UPC_1, UPC_2]
        assert statement["lines"][1]["line_shipped_cents"] == 0
        assert statement["lines"][1]["line_commission_cents"] == 0

    def test_the_shipped_line_is_wholly_inside_the_first_tier(
        self, api, two_awarded_items_before_acceptance
    ):
        """2,010,000 of shipped value is under the 3,000,000 threshold, so 500 bps applies to all.

        PRD: "For each line, the tier-1 portion is the smaller of that line's
        `line_shipped_cents` and the part of `tier_threshold_cents` not yet consumed by earlier
        lines, and it is never negative: once the cumulative total has already reached the
        threshold, the tier-1 portion is zero."

        Design: Corner/calculations/commission_statement_lines_only_for_items_with_live_authorizations
        """
        scope = two_awarded_items_before_acceptance
        accept(api, scope)
        ship_the_first_item(api, scope)

        statement = read_statement(api, scope)

        shipped_line = statement["lines"][0]
        assert shipped_line["line_shipped_cents"] == CASE_VOLUME * I1_LIST_PRICE_CENTS
        assert shipped_line["line_shipped_cents"] == I1_SHIPPED_CENTS
        assert shipped_line["tier1_part_cents"] == I1_SHIPPED_CENTS
        assert shipped_line["tier2_part_cents"] == 0
        assert shipped_line["line_commission_cents"] == I1_COMMISSION_CENTS

    def test_the_totals_sum_the_rounded_lines(self, api, two_awarded_items_before_acceptance):
        """One earning line and one empty line give the same totals as the earning line alone.

        PRD: "`total_commission_cents` is the sum of the already-rounded line values, and
        `total_shipped_cents` is the sum of the line shipped amounts."

        Design: Corner/calculations/commission_statement_lines_only_for_items_with_live_authorizations
        """
        scope = two_awarded_items_before_acceptance
        accept(api, scope)
        ship_the_first_item(api, scope)

        statement = read_statement(api, scope)

        assert statement["total_shipped_cents"] == I1_SHIPPED_CENTS
        assert statement["total_commission_cents"] == I1_COMMISSION_CENTS
        assert_statement_walk(
            statement, TIER_THRESHOLD_CENTS, BASE_COMMISSION_BPS, TIER_COMMISSION_BPS
        )
