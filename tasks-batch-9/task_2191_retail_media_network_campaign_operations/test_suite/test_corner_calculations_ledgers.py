"""Interval geometry on a single-capacity slot, and the trade fund pool's conservation.

Two independent arithmetic surfaces meet here. The first is the reservation a line item
takes when it becomes eligible, checked on a slot that admits exactly one concurrent
occupant and against a neighbour whose flight ends at the very instant the candidate's
begins — the case the half-open rule is written to permit. The second is the fund pool
ledger, checked after a manual deduction has moved money from the available column to the
deducted one without touching the accrued total.
"""

from test_helpers import (
    BILLING_OPS,
    CATALOG_OPS,
    api_client,
    assert_trade_fund_identity,
    build_active_advertiser,
    build_active_budget_plan,
    build_campaign_ready_world,
    build_catalog_product,
    build_eligible_line_item,
    build_pending_eligibility_line_item,
    build_trade_fund_pool,
    factories,
    reread_line_item,
    reread_plan,
    reread_pool,
    reread_slot,
    validate_success,
)

FLIGHT_START = "2026-08-01T00:00:00Z"
FLIGHT_END = "2026-08-11T00:00:00Z"

# Two windows that touch at 2026-08-04 exactly: the earlier one ends where the later begins.
EARLY_START = "2026-08-02T00:00:00Z"
BOUNDARY = "2026-08-04T00:00:00Z"
LATE_END = "2026-08-06T00:00:00Z"

FIRST = "first_line_item"
SECOND = "second_line_item"
SECOND_PRODUCT = "second_product"


def test_adjacent_flights_both_occupy_a_single_capacity_slot():
    """A flight ending at 08-04 and one starting at 08-04 both reach ELIGIBLE.

    PRD 2.8: "Every time range in this specification is **half-open**: the start instant is
    inclusive and the end instant is exclusive."

    PRD 2.8: "Adjacency is consequently never a collision: a range that ends at exactly the
    instant another begins does not overlap it."

    PRD 3.4: "Rule A is aggregate capacity and applies to every slot regardless of channel:
    the number of those rows whose flight overlaps the candidate's flight must be strictly
    less than `max_concurrent_line_items`."

    PRD 3.4: "It lands the line item in `ELIGIBLE`, raises the slot's `occupancy_count` by
    1, and computes `reserved_cents` as `daily_budget_cents` multiplied by the number of
    whole twenty-four-hour periods in the line item's flight, with that day count floored at
    1 — a flight shorter than a day reserves exactly one day of budget."

    Design: Corner/calculations/adjacent_flight_windows_on_a_single_capacity_slot_do_not_collide
    """
    world = build_campaign_ready_world(
        plan={"committed_total_cents": 2000000, "trade_fund_share_cents": 0},
        slot={
            "page_type": "CATEGORY_BROWSE",
            "max_concurrent_line_items": 1,
            "floor_cpc_cents": 50,
            "relevance_weight": 1.0,
        },
        product={
            "category_code": "FOOTWEAR",
            "title": "red shoes",
            "price_cents": 5000,
            "in_stock_units": 50,
            "margin_pct": 0.4,
        },
        campaign={
            "channel_mix": "ONSITE_ONLY",
            "flight_start_at": FLIGHT_START,
            "flight_end_at": FLIGHT_END,
            "allocated_budget_cents": 1000000,
            "pacing_mode": "EVEN",
            "daily_cap_cents": 200000,
        },
    )
    build_catalog_product(
        world,
        key=SECOND_PRODUCT,
        category_code="FOOTWEAR",
        title="red sandals",
        price_cents=4000,
        in_stock_units=40,
        margin_pct=0.2,
    )
    build_eligible_line_item(
        world,
        key=FIRST,
        bid_cents=200,
        bid_type="CPC",
        flight_start_at=EARLY_START,
        flight_end_at=BOUNDARY,
        daily_budget_cents=100000,
        category_code="FOOTWEAR",
        keyword_match_terms=["red", "shoes"],
    )
    build_pending_eligibility_line_item(
        world,
        key=SECOND,
        product_key=SECOND_PRODUCT,
        bid_cents=180,
        bid_type="CPC",
        flight_start_at=BOUNDARY,
        flight_end_at=LATE_END,
        daily_budget_cents=100000,
        category_code="FOOTWEAR",
        keyword_match_terms=["red"],
    )
    # Only the first line item occupies the slot so far, and the slot admits just one
    # overlapping occupant, so the decision below turns entirely on the adjacency question.
    assert reread_slot(world)["occupancy_count"] == 1

    decided = validate_success(
        api_client.decide_line_item_eligibility(
            world[SECOND]["id"], factories.decision_payload("APPROVE"), CATALOG_OPS
        )
    )

    assert decided["line_item_status"] == "ELIGIBLE"
    assert reread_line_item(world, FIRST)["line_item_status"] == "ELIGIBLE"
    # Two whole twenty-four-hour periods in each flight, at 100,000 cents a day.
    assert reread_line_item(world, FIRST)["reserved_cents"] == 200000
    assert decided["reserved_cents"] == 200000
    # Both rows occupy the slot even though its concurrency limit is one, because they
    # never overlap: capacity counts overlapping occupants, not occupants.
    assert reread_slot(world)["occupancy_count"] == 2


def test_manual_deduction_moves_available_cents_into_deducted_cents():
    """A 50,000-cent deduction leaves 500,000 accrued split 250,000 / 200,000 / 50,000.

    PRD 2.9: "The **trade fund identity** governs a fund pool: its `accrued_cents` always
    equals its `available_cents` plus its `reserved_cents` plus its `deducted_cents`."

    PRD 3.2: "A manual deduction, posted with `deduction_amount_cents`, a mandatory
    `deduction_reference` and the mandatory `expected_trade_fund_account_version`, moves the
    amount from `available_cents` to `deducted_cents` and requires `available_cents` to be
    at least the requested amount; the pool identity is preserved throughout, and a manual
    deduction can never drive `available_cents` below zero."

    PRD 3.2: "`reserved_cents` is the sum of `trade_fund_share_cents` over budget plans of
    the same advertiser and period whose `plan_status` is `APPROVED` or `ACTIVE`;
    `deducted_cents` is the sum of `trade_fund_deduction_cents` over invoices referencing
    this pool whose `invoice_status` is `ISSUED`, `DISPUTED`, `ADJUSTED` or `SETTLED`, plus
    the sum of every manual deduction posted to it; and `available_cents` is `accrued_cents`
    less `reserved_cents` less `deducted_cents`."

    PRD 3.2: "`cash_share_cents` is `committed_total_cents` less `trade_fund_share_cents`."

    Design: Corner/calculations/trade_fund_pool_conserves_accrued_reserved_and_deducted_cents
    """
    world = build_active_advertiser()
    build_trade_fund_pool(world, accrual_cents=500000)
    build_active_budget_plan(
        world,
        committed_total_cents=2000000,
        trade_fund_share_cents=200000,
    )
    # The approval reserved the plan's share against the pool, so the pool's version has
    # moved on since it was created and has to be re-read before the deduction carries it.
    pool = reread_pool(world)
    assert pool["reserved_cents"] == 200000

    deducted = validate_success(
        api_client.post_trade_fund_deduction(
            pool["id"],
            factories.deduction_payload(50000, pool["version"]),
            BILLING_OPS,
        )
    )

    # The accrued total is untouched: a deduction shifts money between columns.
    assert deducted["accrued_cents"] == 500000
    assert deducted["reserved_cents"] == 200000
    assert deducted["deducted_cents"] == 50000
    assert deducted["available_cents"] == 250000
    assert deducted["account_status"] == "OPEN"
    assert_trade_fund_identity(deducted)

    assert reread_plan(world)["cash_share_cents"] == 1800000
    assert_trade_fund_identity(reread_pool(world))
