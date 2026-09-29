"""Chains where each hop is caused only by the hop above it.

Neither cascade below writes any of its own consequences directly. A stock movement flips
one product, and everything else — the assignment, the line item, the campaign — falls
because the row above it fell. A settlement writes one spend figure, and everything else —
the plan, the campaign, the line item — falls because the plan ran dry. Each chain is
therefore pinned hop by hop, and each is paired with a near-identical request that stops
one hop short, which is what shows the hops really are links and not a single write.
"""

from test_helpers import (
    AUCTION_SERVICE,
    CATALOG_OPS,
    adjust_product_stock,
    api_client,
    assert_budget_plan_identity,
    assert_line_item_paused,
    assert_occupancy_count,
    build_awarded_auction,
    build_delivering_world,
    build_engagement_event,
    reread_campaign,
    reread_line_item,
    reread_plan,
    reread_product,
    reread_slot,
    round_half_up,
    validate_paginated,
    validate_success,
)

PLAN_COMMITTED_CENTS = 1000000
CAMPAIGN_ALLOCATED_CENTS = 500000
CAMPAIGN_DAILY_CAP_CENTS = 400000
LINE_ITEM_DAILY_BUDGET_CENTS = 400000
LINE_ITEM_FLIGHT = ("2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z")
ACTIVATE_AT = "2026-08-05T12:00:00Z"
PLAN_WINDOW = ("2026-08-01T00:00:00Z", "2026-11-01T00:00:00Z")

# --- The out-of-stock pausing chain ----------------------------------------

STOCK_UNITS = 10
MIN_STOCK_UNITS_FOR_SERVING = 5
DIP_BELOW_THRESHOLD = -6
DIP_TO_THRESHOLD = -5


def _serving_line_item_world():
    """One serving line item whose only product sits five units above its floor.

    The line item carries exactly one hero assignment, so a single product losing its
    eligibility is enough to empty the line item's eligible-product count, and the campaign
    holds exactly one line item, so that line item pausing is enough to leave the campaign
    with nothing serving.
    """
    return build_delivering_world(
        accrual_cents=0,
        plan={
            "committed_total_cents": PLAN_COMMITTED_CENTS,
            "trade_fund_share_cents": 0,
            "window_start_at": PLAN_WINDOW[0],
            "window_end_at": PLAN_WINDOW[1],
        },
        slot={"max_concurrent_line_items": 2, "floor_cpc_cents": 250000},
        product={
            "category_code": "COFFEE",
            "margin_pct": 0.4,
            "in_stock_units": STOCK_UNITS,
            "min_stock_units_for_serving": MIN_STOCK_UNITS_FOR_SERVING,
        },
        campaign={
            "channel_mix": "ONSITE_ONLY",
            "flight_start_at": "2026-08-01T00:00:00Z",
            "flight_end_at": "2026-09-01T00:00:00Z",
            "allocated_budget_cents": CAMPAIGN_ALLOCATED_CENTS,
            "daily_cap_cents": CAMPAIGN_DAILY_CAP_CENTS,
        },
        line_item={
            "bid_cents": 400000,
            "bid_type": "CPC",
            "daily_budget_cents": LINE_ITEM_DAILY_BUDGET_CENTS,
            "flight_start_at": LINE_ITEM_FLIGHT[0],
            "flight_end_at": LINE_ITEM_FLIGHT[1],
            "category_code": "COFFEE",
            "keyword_match_terms": ["coffee"],
        },
        activate_at=ACTIVATE_AT,
    )


def _only_assignment(world):
    """Re-read the line item's single product assignment."""
    rows, _ = validate_paginated(
        api_client.list_product_assignments(
            CATALOG_OPS, line_item_id=world["line_item"]["id"]
        )
    )
    assert len(rows) == 1
    return rows[0]


def test_a_stock_dip_flips_the_product_and_the_assignment_beneath_it():
    """The movement writes stock; the product's status and the assignment follow from it.

    PRD 3.5: "The adjustment updates `in_stock_units` and stamps `last_stock_change_at`
    with the current logical time, and it is refused outright against a `DELISTED`
    product. When the resulting `in_stock_units` falls strictly below
    `min_stock_units_for_serving` and the product was `ELIGIBLE`, the product moves to
    `OUT_OF_STOCK` and the depth-three pausing chain fires. Level one: every assignment
    referencing this product that is `ACTIVE` moves to `PAUSED_OOS`, with its
    `relevance_contribution` zeroed."

    PRD 3.5: "`eligible_product_count` on a line item is the number of its assignments
    that are `ACTIVE` **and** whose product is `ELIGIBLE`. Assignments in `PAUSED_OOS`,
    `PAUSED_RESTRICTED` or `REMOVED` count zero, as do `ACTIVE` assignments whose product
    has slipped out of eligibility."

    Design: Difficulty/transitive_cascade/tc_catalog_out_of_stock_three_hop_pause_chain
    """
    world = _serving_line_item_world()
    assert world["line_item"]["line_item_status"] == "SERVING"
    assert reread_product(world)["eligibility_status"] == "ELIGIBLE"
    assert _only_assignment(world)["assignment_status"] == "ACTIVE"

    adjust_product_stock(world, DIP_BELOW_THRESHOLD)

    product = reread_product(world)
    assert product["in_stock_units"] == STOCK_UNITS + DIP_BELOW_THRESHOLD == 4
    assert product["in_stock_units"] < MIN_STOCK_UNITS_FOR_SERVING
    assert product["eligibility_status"] == "OUT_OF_STOCK"
    assert product["last_stock_change_at"] is not None

    assignment = _only_assignment(world)
    assert assignment["assignment_status"] == "PAUSED_OOS"
    assert assignment["relevance_contribution"] == 0.0
    assert reread_line_item(world)["eligible_product_count"] == 0


def test_the_line_item_and_its_campaign_follow_the_emptied_assignment_down():
    """Hops two and three: an empty count pauses the line item, which pauses the campaign.

    PRD 3.5: "Level two: each of those assignments triggers a recomputation of
    `eligible_product_count` on its line item, and any line item whose recomputed count
    reaches 0 while it is `SERVING` moves to `OOS_PAUSED` with `pause_reason`
    `OUT_OF_STOCK` and `last_pause_at` stamped. Level three: each line item entering
    `OOS_PAUSED` raises `oos_paused_line_item_count` on its campaign by 1, and a campaign
    whose every non-ended line item is now in `OOS_PAUSED` or `MANUAL_PAUSED` and whose
    `delivery_status` is `DELIVERING` moves to `PAUSED`."

    Design: Difficulty/transitive_cascade/tc_catalog_out_of_stock_three_hop_pause_chain
    """
    world = _serving_line_item_world()
    assert reread_campaign(world)["oos_paused_line_item_count"] == 0

    adjust_product_stock(world, DIP_BELOW_THRESHOLD)

    line_item = reread_line_item(world)
    assert_line_item_paused(line_item, "OOS_PAUSED", "OUT_OF_STOCK")
    assert line_item["last_pause_at"] is not None
    assert line_item["eligible_product_count"] == 0

    campaign = reread_campaign(world)
    assert campaign["oos_paused_line_item_count"] == 1
    assert campaign["delivery_status"] == "PAUSED"

    # Only the delivery dimension reacted: the billing dimension is untouched by a
    # catalog blocker.
    assert campaign["billing_status"] == "ACCRUING"


def test_a_dip_that_stops_at_the_threshold_starts_no_chain_at_all():
    """One unit of stock decides whether any of the three hops happen.

    PRD 3.5: "The product's `eligibility_status` at creation is derived rather than
    supplied: `ELIGIBLE` when `in_stock_units` is at least `min_stock_units_for_serving`,
    and `OUT_OF_STOCK` otherwise."

    PRD 3.5: "When the resulting `in_stock_units` falls strictly below
    `min_stock_units_for_serving` and the product was `ELIGIBLE`, the product moves to
    `OUT_OF_STOCK` and the depth-three pausing chain fires."

    Design: Difficulty/transitive_cascade/tc_catalog_out_of_stock_three_hop_pause_chain
    """
    world = _serving_line_item_world()

    adjust_product_stock(world, DIP_TO_THRESHOLD)

    # The stock lands exactly on the threshold, which is not strictly below it.
    product = reread_product(world)
    assert product["in_stock_units"] == MIN_STOCK_UNITS_FOR_SERVING == 5
    assert product["eligibility_status"] == "ELIGIBLE"

    # No hop fired, so nothing below the product moved.
    assert _only_assignment(world)["assignment_status"] == "ACTIVE"
    line_item = reread_line_item(world)
    assert line_item["line_item_status"] == "SERVING"
    assert line_item["pause_reason"] == "NONE"
    assert line_item["eligible_product_count"] == 1
    campaign = reread_campaign(world)
    assert campaign["delivery_status"] == "DELIVERING"
    assert campaign["oos_paused_line_item_count"] == 0


def test_the_out_of_stock_chain_surrenders_no_occupancy_and_no_reservation():
    """A paused line item still occupies its slot and its campaign still reserves.

    PRD 3.5: "The slot's `occupancy_count` is unchanged throughout, because `OOS_PAUSED`
    remains an occupying status."

    PRD 2.10: "**pausing a line item does not change its slot's `occupancy_count`, and
    does not change its plan's `reserved_cents`**, because a paused line item still
    occupies its slot and its campaign is still in a reserving delivery status."

    PRD 3.2: "`reserved_cents` is the sum of `allocated_budget_cents` over the plan's
    campaigns whose `delivery_status` is `SCHEDULED`, `DELIVERING` or `PAUSED`; campaigns
    in `DRAFT`, `PENDING_REVIEW`, `COMPLETED`, `REJECTED` or `ARCHIVED` reserve nothing."

    Design: Difficulty/transitive_cascade/tc_catalog_out_of_stock_three_hop_pause_chain
    """
    world = _serving_line_item_world()
    assert_occupancy_count(reread_slot(world), 1)
    plan_before = reread_plan(world)
    assert plan_before["reserved_cents"] == CAMPAIGN_ALLOCATED_CENTS
    assert plan_before["available_cents"] == 500000

    adjust_product_stock(world, DIP_BELOW_THRESHOLD)

    assert_occupancy_count(reread_slot(world), 1)
    plan_after = reread_plan(world)
    assert plan_after["plan_status"] == "ACTIVE"
    assert plan_after["reserved_cents"] == plan_before["reserved_cents"]
    assert plan_after["consumed_cents"] == 0
    assert plan_after["available_cents"] == 500000
    assert_budget_plan_identity(plan_after)


# ---------------------------------------------------------------------------
# The budget-exhaustion chain
# ---------------------------------------------------------------------------

SLOT_FLOOR_CENTS = 250000
LINE_ITEM_BID_CENTS = 400000
PRODUCT_MARGIN_PCT = 0.4
EXHAUSTING_FLIGHT = ("2026-08-01T00:00:00Z", "2026-08-06T00:00:00Z")
IMPRESSION_AT = "2026-08-05T12:10:00Z"
CLICK_TIMES = ("2026-08-05T12:20:00Z", "2026-08-05T12:30:00Z")
TIER_2_MULTIPLIER = 1.00


def _awarded_world(clicks=2):
    """One awarded auction on a plan that the coming settlement will drain exactly.

    The plan commits a million cents and the campaign reserves half of it, so the plan has
    exactly the settlement figure left to give. The campaign's flight closes a day after
    the auction, which puts the daily pacing allowance above the campaign's daily cap and
    leaves the cap as the binding campaign term of the headroom minimum, so the single
    candidate bids its whole bid. Two clicks at the clearing price is exactly the plan's
    remaining headroom; one click is exactly half of it.
    """
    world = build_delivering_world(
        accrual_cents=0,
        plan={
            "committed_total_cents": PLAN_COMMITTED_CENTS,
            "trade_fund_share_cents": 0,
            "window_start_at": PLAN_WINDOW[0],
            "window_end_at": PLAN_WINDOW[1],
        },
        slot={"max_concurrent_line_items": 2, "floor_cpc_cents": SLOT_FLOOR_CENTS},
        product={
            "category_code": "COFFEE",
            "margin_pct": PRODUCT_MARGIN_PCT,
            "in_stock_units": 100,
            "min_stock_units_for_serving": 3,
        },
        campaign={
            "channel_mix": "ONSITE_ONLY",
            "flight_start_at": EXHAUSTING_FLIGHT[0],
            "flight_end_at": EXHAUSTING_FLIGHT[1],
            "allocated_budget_cents": CAMPAIGN_ALLOCATED_CENTS,
            "daily_cap_cents": CAMPAIGN_DAILY_CAP_CENTS,
        },
        line_item={
            "bid_cents": LINE_ITEM_BID_CENTS,
            "bid_type": "CPC",
            "daily_budget_cents": LINE_ITEM_DAILY_BUDGET_CENTS,
            "flight_start_at": LINE_ITEM_FLIGHT[0],
            "flight_end_at": LINE_ITEM_FLIGHT[1],
            "category_code": "COFFEE",
            "keyword_match_terms": ["coffee"],
        },
        activate_at=ACTIVATE_AT,
    )
    build_awarded_auction(
        world, request_context_query="coffee", shopper_segment="LOYALTY"
    )
    build_engagement_event(world, event_type="IMPRESSION", occurred_at=IMPRESSION_AT)
    for moment in CLICK_TIMES[:clicks]:
        build_engagement_event(world, event_type="CLICK", occurred_at=moment)
    return world


def _settle(world):
    """Settle the awarded auction, which is the only call the cascade needs."""
    world["auction"] = validate_success(
        api_client.settle_auction_event(world["auction"]["id"], None, AUCTION_SERVICE)
    )
    return world["auction"]


def test_the_settlement_drains_the_plan_and_the_plan_pauses_everything_below_it():
    """One spend write, then a plan flip, then a campaign flip, then a line item flip.

    PRD 3.6: "Level one adds `settled_spend_cents` to the winning line item's
    `spend_cents` and to its campaign's `delivered_spend_cents`. Level two recomputes the
    plan's `consumed_cents` and `available_cents`, moving the amount out of the reservation
    and into consumption; a plan whose recomputed `available_cents` is 0 or less while
    `plan_status` is `ACTIVE` moves to `EXHAUSTED` with `exhausted_at` stamped. Level three
    is that exhaustion's own two-step consequence: every `DELIVERING` campaign on the plan
    moves to `PAUSED`, and every `SERVING` line item of those campaigns moves to
    `MANUAL_PAUSED` with `pause_reason` `BUDGET_EXHAUSTED`."

    PRD 3.6: "Under `CPC`, only `CLICK` events are billable: `settled_spend_cents` is
    `clearing_price_cents` multiplied by the count of `CLICK` events on the auction."

    Design: Difficulty/transitive_cascade/tc_auction_settlement_budget_exhaustion_chain
    """
    world = _awarded_world(clicks=2)
    plan_before = reread_plan(world)
    assert plan_before["plan_status"] == "ACTIVE"
    assert plan_before["available_cents"] == 500000

    settled = _settle(world)
    assert settled["status"] == "SETTLED"
    assert settled["clearing_price_cents"] == SLOT_FLOOR_CENTS
    assert settled["settled_spend_cents"] == SLOT_FLOOR_CENTS * len(CLICK_TIMES)
    assert settled["settled_spend_cents"] == 500000

    # Level one.
    assert reread_line_item(world)["spend_cents"] == 500000
    campaign = reread_campaign(world)
    assert campaign["delivered_spend_cents"] == 500000

    # Level two: the settlement figure is exactly what the plan had left.
    plan = reread_plan(world)
    assert plan["consumed_cents"] == 500000
    assert plan["available_cents"] == 0
    assert plan["plan_status"] == "EXHAUSTED"
    assert plan["exhausted_at"] is not None

    # Level three: the plan's exhaustion, and nothing else, paused the campaign and its
    # line item.
    assert campaign["delivery_status"] == "PAUSED"
    assert_line_item_paused(
        reread_line_item(world), "MANUAL_PAUSED", "BUDGET_EXHAUSTED"
    )


def test_the_single_candidate_was_awarded_at_its_whole_bid_and_the_bare_floor():
    """The charge that drains the plan is the floor times the clicks, and nothing else.

    PRD 3.6: "`quality_adjusted_score` is the effective bid multiplied by
    `relevance_score` raised to the power of the slot's `relevance_weight`, multiplied by
    the tier multiplier, rounded half-up to four decimal places."

    PRD 3.4: "Otherwise, when the advertiser is `MANAGED` **or** the remaining ratio is at
    least 0.20, the tier is `TIER_2`."

    PRD 3.6: "`winner_score` is the rank-one row's `quality_adjusted_score` and
    `second_best_score` is the rank-two row's, or null when no rank-two row exists."

    Design: Difficulty/transitive_cascade/tc_auction_settlement_budget_exhaustion_chain
    """
    world = _awarded_world(clicks=2)
    auction = world["auction"]

    # A self-serve advertiser with half its commitment still free lands in the middle
    # tier, whose multiplier leaves the score alone.
    plan = reread_plan(world)
    remaining_ratio = plan["available_cents"] / (
        plan["committed_total_cents"] + plan["top_up_total_cents"]
    )
    assert remaining_ratio == 0.5
    assert reread_line_item(world)["priority_tier"] == "TIER_2"

    relevance = round_half_up(0.60 * 1.0 + 0.25 * PRODUCT_MARGIN_PCT + 0.10 + 0.06, 4)
    assert relevance == 0.86
    expected_score = round_half_up(
        LINE_ITEM_BID_CENTS * relevance * TIER_2_MULTIPLIER, 4
    )
    assert expected_score == 344000.0
    assert auction["candidate_count"] == 1
    assert auction["winner_score"] == expected_score
    assert auction["second_best_score"] is None
    assert auction["winning_line_item_id"] == world["line_item"]["id"]
    assert auction["clearing_price_cents"] == SLOT_FLOOR_CENTS
    assert auction["no_fill_reason"] == "NONE"


def test_a_settlement_that_leaves_the_plan_funded_pauses_nothing():
    """Half the charge leaves the plan solvent, and then no hop below it fires.

    PRD 3.6: "a plan whose recomputed `available_cents` is 0 or less while `plan_status`
    is `ACTIVE` moves to `EXHAUSTED` with `exhausted_at` stamped."

    PRD 3.2: "`available_cents` is `committed_total_cents` plus `top_up_total_cents`, less
    `reserved_cents`, less `consumed_cents`; it may go negative only through
    over-delivery."

    Design: Difficulty/transitive_cascade/tc_auction_settlement_budget_exhaustion_chain
    """
    world = _awarded_world(clicks=1)

    settled = _settle(world)
    assert settled["settled_spend_cents"] == SLOT_FLOOR_CENTS == 250000

    plan = reread_plan(world)
    assert plan["consumed_cents"] == 250000
    assert plan["reserved_cents"] == CAMPAIGN_ALLOCATED_CENTS
    assert plan["available_cents"] == 250000
    assert plan["plan_status"] == "ACTIVE"
    assert plan["exhausted_at"] is None
    assert_budget_plan_identity(plan)

    # The plan did not flip, so neither did the campaign or the line item.
    campaign = reread_campaign(world)
    assert campaign["delivery_status"] == "DELIVERING"
    assert campaign["delivered_spend_cents"] == 250000
    line_item = reread_line_item(world)
    assert line_item["line_item_status"] == "SERVING"
    assert line_item["pause_reason"] == "NONE"
    assert line_item["spend_cents"] == 250000
