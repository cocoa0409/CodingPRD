"""Two combinatorial money formulas whose evaluation order is pinned.

An order's six money figures are rounded component by component, in the order the
price card declares, and only then summed — so the group discount and the pit
party bundle discount each carry their own half-cent up before the total exists.

A settlement's co-op credit rate is selected from the very pre-credit rental total
that the credit then reduces, with inclusive band floors, so an implementation
that keys the rate on the post-credit figure lands on a different band.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from test_helpers import (
    ApiClient,
    assert_event_settlement,
    assert_profitability_margin,
    assert_seat_pool_conserved,
    assert_settlement_waterfall,
    assert_ticket_order,
    make_ticket_order_payload,
    validate_success,
)
from test_helpers import fixtures as helpers

# The rounding order lands on a half cent twice: 99,750 x 0.125 = 12,468.75 and
# 51,450 x 0.15 = 7,717.5.
_ROUNDING_ORDER_QTY = 21

# The Dallas market of the boundary scenario. Its booking terms are chosen so the
# pre-credit rental total lands exactly on the inclusive 5,000,000-cent floor of
# the 0.06 co-op band.
_DAL_BOOKING = {
    "venue_name": "Dallas Coliseum",
    "market_code": "DAL",
    "city": "Dallas",
    "state_code": "TX",
    "tour_date": "2026-12-05",
    "rental_base_cents": 4_700_000,
    "revenue_share_pct": 0.10,
    "per_ticket_facility_fee_cents": 500,
    "load_in_start_utc": "2026-12-04T14:00:00Z",
    "tear_down_end_utc": "2026-12-06T06:00:00Z",
    "doors_open_utc": "2026-12-05T22:00:00Z",
    "show_start_utc": "2026-12-05T23:00:00Z",
    "pit_party_capacity": 0,
    "segment_title": "Freestyle Final",
    "duration_minutes": 40,
    "include_second_tier": False,
    "tier_code": "DALGA",
    "price_cents": 4_750,
    "allotment": 1_000,
    "on_sale_end_utc": "2026-12-05T18:00:00Z",
    "barrier_linear_feet": 1_200,
    "catch_fence_height_ft": 6,
    "medical_als_staff_count": 1,
    "medical_bls_staff_count": 2,
    "ambulance_count": 1,
    "emergency_access_lanes": 1,
    "amount_cents": 500_000,
    "qty": 600,
    "purchaser_name": "DAL Block",
    "purchaser_email": "dal-block@example.com",
}


def _place_rounding_order(
    api: ApiClient, state: Dict[str, Any], headers: Dict[str, str]
) -> Dict[str, Any]:
    """Place the 21-seat group order that also brings 21 pit party heads."""
    version = helpers.fetch_tier_version(api, state["tier_id"])
    return validate_success(
        api.create_ticket_order(
            make_ticket_order_payload(
                state["stop_id"],
                state["tier_id"],
                version,
                purchaser_name="Rounding Group",
                purchaser_email="rounding@example.com",
                qty=_ROUNDING_ORDER_QTY,
                is_group=True,
                pit_party_addon_qty=_ROUNDING_ORDER_QTY,
            ),
            headers=headers,
        ),
        expected_status=201,
    )


class TestTicketOrderPerLineRounding:
    """The order money breakdown, rounded line by line before it is summed."""

    def test_each_percentage_line_is_rounded_to_whole_cents_on_its_own_line(
        self,
        api: ApiClient,
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §3.7: "Six figures are written, and the rounding order is pinned — each percentage component is rounded to whole cents on its own line, in the order below, and only then are the lines summed."

        PRD §2.5: "Where a percentage is applied to a monetary amount, the product is rounded to whole cents using the round-half-up rule, and the rounding is applied to each named component separately, on its own line, in the order the calculation declares."

        Design: Difficulty/combinatorial_formula/ticket_order_rounds_each_discount_line_before_summing
        """
        state = helpers.stop_on_sale(api)

        order = _place_rounding_order(api, state, ticketing_headers)

        assert_ticket_order(order)
        # 21 seats at the 4,750-cent PITSIDE face.
        assert order["line_subtotal_cents"] == 99_750
        # 99,750 x 0.125 is 12,468.75, which rounds half up on its own line.
        assert order["group_discount_cents"] == 12_469
        # 21 pit party heads at 2,450 cents each.
        assert order["addon_subtotal_cents"] == 51_450
        # 51,450 x 0.15 is 7,717.5, which also rounds half up on its own line.
        assert order["addon_discount_cents"] == 7_718
        # The facility fee is never discounted: 21 seats at 350 cents.
        assert order["facility_fee_cents"] == 7_350

    def test_the_order_total_sums_the_already_rounded_lines_and_reserves_the_seats(
        self,
        api: ApiClient,
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §3.7: "`total_cents` is `line_subtotal_cents` minus `group_discount_cents`, plus `addon_subtotal_cents` minus `addon_discount_cents`, plus `facility_fee_cents`."

        PRD §3.7: "Rounding the two discounts together after adding them produces a different total and is wrong."

        Design: Difficulty/combinatorial_formula/ticket_order_rounds_each_discount_line_before_summing
        """
        state = helpers.stop_on_sale(api)

        order = _place_rounding_order(api, state, ticketing_headers)

        # Summing the raw discounts first gives 20,186.25, rounds to 20,186 and
        # leaves a total of 138,364 — one cent above the pinned per-line answer.
        assert order["total_cents"] == 138_363
        assert order["total_cents"] != 138_364
        assert order["status"] == "PENDING"

        tier = helpers.fetch_tier(api, state["tier_id"])
        assert tier["reserved_seat_count"] == _ROUNDING_ORDER_QTY
        assert tier["sold_seat_count"] == 0
        assert_seat_pool_conserved(tier)


class TestCoopCreditRateAtTheInclusiveBoundary:
    """The co-op credit rate keyed on the pre-credit total it then reduces."""

    def test_the_coop_rate_is_keyed_on_the_pre_credit_total_at_its_inclusive_floor(
        self,
        api: ApiClient,
        finance_preparer_headers: Dict[str, str],
    ) -> None:
        """PRD §3.9: "The co-op credit rate `coop_credit_pct` is selected from that pre-credit figure with inclusive boundaries: 0.06 when `rental_due_pre_credit_cents` is 5,000,000 cents or more, otherwise 0.04 when it is 2,500,000 cents or more, otherwise 0.02."

        PRD §3.9: "The rate is **not** re-selected after the credit is applied."

        Design: Difficulty/combinatorial_formula/coop_credit_rate_keyed_on_pre_credit_total_at_the_inclusive_boundary
        """
        state = helpers.stop_sales_closed(api, **_DAL_BOOKING)

        settlement = validate_success(
            api.create_settlement(
                state["stop_id"], headers=finance_preparer_headers
            ),
            expected_status=201,
        )

        assert_event_settlement(settlement)
        # 600 seats at 4,750 cents with no group rate, and 600 facility fees of
        # 500 cents each.
        assert settlement["ticket_revenue_cents"] == 2_850_000
        assert settlement["facility_fee_cents"] == 300_000
        # The share component is 2,850,000 x 0.10 = 285,000, so the 4,700,000-cent
        # rental base wins; adding the 300,000-cent facility total lands the
        # pre-credit figure exactly on the inclusive floor of the top band.
        assert settlement["rental_due_pre_credit_cents"] == 5_000_000
        assert settlement["coop_credit_pct"] == pytest.approx(0.06, abs=0.01)
        assert settlement["coop_credit_cents"] == 300_000
        # Keying the rate on the post-credit figure would pick 0.04, credit only
        # 200,000 cents and leave 4,800,000 due to the building.
        assert settlement["venue_due_cents"] == 4_700_000

    def test_the_venue_due_drives_the_costs_the_net_and_the_waterfall_shortfall(
        self,
        api: ApiClient,
        finance_preparer_headers: Dict[str, str],
    ) -> None:
        """PRD §3.9: "`net_to_promoter_cents` is `collected_cash_cents` minus `venue_due_cents`, minus `safety_cost_cents`, minus `marketing_spend_cents`, minus `purse_cents`, and it may legitimately be negative."

        PRD §3.9: "`payout_venue_cents` is the smaller of the remainder and `venue_due_cents`, and the remainder falls by that amount."

        Design: Difficulty/combinatorial_formula/coop_credit_rate_keyed_on_pre_credit_total_at_the_inclusive_boundary
        """
        state = helpers.stop_sales_closed(api, **_DAL_BOOKING)

        settlement = validate_success(
            api.create_settlement(
                state["stop_id"], headers=finance_preparer_headers
            ),
            expected_status=201,
        )

        # One ALS medic, two BLS medics, one ambulance and 1,200 feet of barrier.
        assert settlement["safety_cost_cents"] == 641_000
        assert settlement["marketing_spend_cents"] == 500_000
        # Nothing is staged at this stop, so no competitor earns the purse.
        assert settlement["purse_cents"] == 0

        assert settlement["collected_cash_cents"] == 3_150_000
        assert settlement["net_to_promoter_cents"] == -2_691_000
        assert settlement["profitability_margin_pct"] == pytest.approx(
            -85.43, abs=0.01
        )
        assert_profitability_margin(settlement)

        # The building's 4,700,000-cent claim swallows every cent of collected
        # cash, so the three later buckets go unfunded.
        assert settlement["payout_venue_cents"] == 3_150_000
        assert settlement["payout_safety_cents"] == 0
        assert settlement["payout_marketing_cents"] == 0
        assert settlement["payout_purse_cents"] == 0
        assert settlement["promoter_remainder_cents"] == 0
        assert settlement["shortfall_cents"] == 2_691_000
        assert_settlement_waterfall(settlement)
