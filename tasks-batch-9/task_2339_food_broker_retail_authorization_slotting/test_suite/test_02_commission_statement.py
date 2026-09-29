"""The commission statement's running tier walk and its per-line rounding placement."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    PRIMARY_CATEGORY,
    UPC_1,
    UPC_2,
    UPC_3,
    get_success_data,
)
from test_helpers import fixtures
from test_helpers.assertions import (
    assert_commission_statement,
    assert_lines_ordered_by_upc,
    assert_statement_walk,
    expected_line_commission,
)

BASE_BPS = 500
TIER_BPS = 300
TIER_THRESHOLD_CENTS = 5000000


@pytest.fixture
def statement_scope(api):
    """Three authorized items at one chain, each carrying one period of volume."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(
        api,
        retailer["id"],
        agreement_overrides={
            "base_commission_bps": BASE_BPS,
            "tier_threshold_cents": TIER_THRESHOLD_CENTS,
            "tier_commission_bps": TIER_BPS,
        },
    )
    principal = bundle["principal"]

    items = [
        fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1, list_price_cents=2010),
        fixtures.validated_item(
            api,
            principal["id"],
            retailer["id"],
            upc=UPC_2,
            list_price_cents=2010,
            description="Mini Pizzas 8ct",
        ),
        fixtures.validated_item(
            api,
            principal["id"],
            retailer["id"],
            upc=UPC_3,
            list_price_cents=2000,
            description="Mini Rolls 10ct",
        ),
    ]
    review = fixtures.opened_review(api, retailer["id"], new_item_slots=3)
    fixtures.submitted_presentation(
        api, review["id"], principal["id"], [item["id"] for item in items]
    )
    review = fixtures.lock_and_decide(
        api,
        review["id"],
        retailer["id"],
        [item["id"] for item in items],
        default_store_count=400,
    )

    volumes = {UPC_1: 995, UPC_2: 995, UPC_3: 1000}
    by_item = {item["id"]: item for item in items}
    for authorization in fixtures.authorizations_for_review(api, review["id"]):
        upc = by_item[authorization["item_id"]]["upc"]
        fixtures.post_period(
            api,
            authorization["id"],
            retailer["id"],
            period_index=1,
            reported_store_count=400,
            distributed_store_count=380,
            reported_case_volume=volumes[upc],
        )

    return {"retailer": retailer, "principal": principal, "items": items}


def read_statement(api, principal_id, retailer_id):
    response = api.get_commission_statement(
        principal_id,
        ACCOUNT_MANAGER_HEADERS,
        {"retailer_id": retailer_id, "category_code": PRIMARY_CATEGORY},
    )
    return get_success_data(response, 200)


class TestCommissionStatementTierWalk:
    def test_lines_are_ordered_by_upc_and_shipped_from_live_postings(self, api, statement_scope):
        """Each line's shipped figure is live posted volume times the item list price.

        PRD: "The shipped figure for a line is the sum of `reported_case_volume` over that
        item's live `POSTING` ledger entries, multiplied by the item's `list_price_cents`."

        Design: Difficulty/combinatorial_formula/commission_lines_rounded_per_line_then_summed
        """
        statement = read_statement(
            api, statement_scope["principal"]["id"], statement_scope["retailer"]["id"]
        )

        assert_commission_statement(statement)
        lines = statement["lines"]
        assert len(lines) == 3
        assert_lines_ordered_by_upc(lines)
        assert [line["upc"] for line in lines] == [UPC_1, UPC_2, UPC_3]
        assert lines[0]["line_shipped_cents"] == 995 * 2010 == 1999950
        assert lines[1]["line_shipped_cents"] == 995 * 2010 == 1999950
        assert lines[2]["line_shipped_cents"] == 1000 * 2000 == 2000000

    def test_tier_one_room_is_consumed_cumulatively_across_lines(self, api, statement_scope):
        """The third line straddles the breakpoint the first two lines partly consumed.

        PRD: "For each line, the tier-1 portion is the smaller of that line's
        `line_shipped_cents` and the part of `tier_threshold_cents` not yet consumed by
        earlier lines, and it is never negative: once the cumulative total has already
        reached the threshold, the tier-1 portion is zero."

        Design: Difficulty/combinatorial_formula/commission_lines_rounded_per_line_then_summed
        """
        statement = read_statement(
            api, statement_scope["principal"]["id"], statement_scope["retailer"]["id"]
        )
        lines = statement["lines"]

        assert lines[0]["tier1_part_cents"] == 1999950
        assert lines[0]["tier2_part_cents"] == 0
        assert lines[1]["tier1_part_cents"] == 1999950
        assert lines[1]["tier2_part_cents"] == 0
        # 5,000,000 less the 3,999,900 the first two lines consumed.
        assert lines[2]["tier1_part_cents"] == 1000100
        assert lines[2]["tier2_part_cents"] == 999900
        assert_statement_walk(statement, TIER_THRESHOLD_CENTS, BASE_BPS, TIER_BPS)

    def test_each_line_is_rounded_half_up_before_the_totals_are_summed(self, api, statement_scope):
        """A raw 99,997.5 cent line becomes 99,998, and the total sums rounded lines.

        PRD: "Rounding each line first and summing afterwards is mandatory: summing the raw
        line values and rounding the total once, or applying the tier to the aggregate
        shipped total instead of walking the lines in `upc` order, produces a different —
        and wrong — answer."

        Design: Difficulty/combinatorial_formula/commission_lines_rounded_per_line_then_summed
        """
        statement = read_statement(
            api, statement_scope["principal"]["id"], statement_scope["retailer"]["id"]
        )
        lines = statement["lines"]

        assert lines[0]["line_commission_cents"] == 99998
        assert lines[1]["line_commission_cents"] == 99998
        assert lines[2]["line_commission_cents"] == 80002
        assert statement["total_shipped_cents"] == 5999900
        assert statement["total_commission_cents"] == 279998
        # Summing the raw 99,997.5 values and rounding once would have produced 279,997.
        assert statement["total_commission_cents"] != 279997

    def test_the_rate_terms_of_the_resolved_agreement_are_echoed(self, api, statement_scope):
        """The statement names the agreement it resolved and the three rate terms.

        PRD: "The response echoes `principal_id`, `retailer_id`, `category_code`, the
        resolved `agreement_id` and the three rate terms `base_commission_bps`,
        `tier_threshold_cents` and `tier_commission_bps`, then carries a `lines` array and
        the two totals `total_shipped_cents` and `total_commission_cents`."

        Design: Difficulty/combinatorial_formula/commission_lines_rounded_per_line_then_summed
        """
        statement = read_statement(
            api, statement_scope["principal"]["id"], statement_scope["retailer"]["id"]
        )

        assert statement["principal_id"] == statement_scope["principal"]["id"]
        assert statement["retailer_id"] == statement_scope["retailer"]["id"]
        assert statement["category_code"] == PRIMARY_CATEGORY
        assert statement["base_commission_bps"] == BASE_BPS
        assert statement["tier_threshold_cents"] == TIER_THRESHOLD_CENTS
        assert statement["tier_commission_bps"] == TIER_BPS
        # The echoed terms are exactly the terms the tier walk used.
        expected_third = expected_line_commission(
            2000000,
            statement["tier_threshold_cents"],
            statement["base_commission_bps"],
            statement["tier_commission_bps"],
            cumulative_shipped_cents=3999900,
        )
        assert statement["lines"][2]["line_commission_cents"] == expected_third["line_commission_cents"]
