"""Single figures assembled from several interacting inputs at once.

Neither figure below can be reproduced by handling its inputs one at a time. The auction
score nests a three-way minimum inside a bid clamp, raises relevance to a per-slot
exponent and then scales the product by a threshold-derived tier multiplier, so a wrong
order of operations reverses the ranking rather than merely shifting it. The cost-per-mille
charge is summed across the whole auction before it is rounded and only then broken back
into per-event parts, so rounding each event first loses cents that the sum keeps.
"""

from test_helpers import (
    AUCTION_SERVICE,
    CATALOG_OPS,
    api_client,
    assert_relevance_score_in_range,
    build_active_budget_plan,
    build_active_managed_advertiser,
    build_awarded_auction,
    build_catalog_product,
    build_delivering_campaign,
    build_draft_campaign,
    build_eligible_line_item,
    build_engagement_event,
    build_placement_slot,
    parse_utc,
    reread_campaign,
    reread_line_item,
    reread_plan,
    round_half_up,
    round_half_up_int,
    set_clock,
    validate_paginated,
    validate_success,
)

# --- The ranking score -----------------------------------------------------

PLAN_COMMITTED_CENTS = 40000000
CAMPAIGN_ALLOCATED_CENTS = 5000000
CAMPAIGN_FLIGHT = ("2026-08-01T00:00:00Z", "2026-08-11T00:00:00Z")
CAMPAIGN_DAILY_CAP_CENTS = 400000
AUCTION_AT = "2026-08-05T10:00:00Z"

SLOT_FLOOR_CENTS = 300
SLOT_RELEVANCE_WEIGHT = 2.0

# The high bidder is starved of daily budget and the low bidder is not, which is what
# makes the nested minimum decide the auction instead of the raw bids.
HI_BID_CENTS = 3000
HI_DAILY_BUDGET_CENTS = 700
HI_MARGIN_PCT = 0.2
LO_BID_CENTS = 1200
LO_DAILY_BUDGET_CENTS = 100000
LO_MARGIN_PCT = 0.4

REQUEST_QUERY = "organic coffee beans"
SHOPPER_SEGMENT = "LOYALTY"
SEGMENT_BONUS = 0.06
HERO_BOOST = 0.10
TIER_1_MULTIPLIER = 1.10


def _ranking_world():
    """One delivering campaign holding two line items on one slot, mid-flight.

    The slot admits three concurrent line items and names no exclusivity category, so
    both line items occupy it and both are candidates. The advertiser is managed, so the
    self-serve daily cap contributes no third term to the headroom minimum. No auction
    has settled, so today's spend is 0 for both line items and for the campaign.
    """
    world = build_active_managed_advertiser()
    build_active_budget_plan(
        world,
        committed_total_cents=PLAN_COMMITTED_CENTS,
        trade_fund_share_cents=0,
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-10-01T00:00:00Z",
    )
    build_placement_slot(
        world,
        max_concurrent_line_items=3,
        floor_cpc_cents=SLOT_FLOOR_CENTS,
        relevance_weight=SLOT_RELEVANCE_WEIGHT,
        buffer_minutes=0,
    )
    build_catalog_product(
        world, key="low_margin_product", category_code="GROCERY", margin_pct=HI_MARGIN_PCT
    )
    build_catalog_product(
        world,
        key="high_margin_product",
        category_code="GROCERY",
        margin_pct=LO_MARGIN_PCT,
    )
    build_draft_campaign(
        world,
        channel_mix="ONSITE_ONLY",
        flight_start_at=CAMPAIGN_FLIGHT[0],
        flight_end_at=CAMPAIGN_FLIGHT[1],
        allocated_budget_cents=CAMPAIGN_ALLOCATED_CENTS,
        daily_cap_cents=CAMPAIGN_DAILY_CAP_CENTS,
    )
    build_eligible_line_item(
        world,
        key="line_item_hi",
        product_key="low_margin_product",
        bid_cents=HI_BID_CENTS,
        bid_type="CPC",
        daily_budget_cents=HI_DAILY_BUDGET_CENTS,
        flight_start_at=CAMPAIGN_FLIGHT[0],
        flight_end_at=CAMPAIGN_FLIGHT[1],
        category_code="GROCERY",
        keyword_match_terms=["coffee"],
    )
    build_eligible_line_item(
        world,
        key="line_item_lo",
        product_key="high_margin_product",
        bid_cents=LO_BID_CENTS,
        bid_type="CPC",
        daily_budget_cents=LO_DAILY_BUDGET_CENTS,
        flight_start_at=CAMPAIGN_FLIGHT[0],
        flight_end_at=CAMPAIGN_FLIGHT[1],
        category_code="GROCERY",
        keyword_match_terms=["coffee", "tea"],
    )
    build_delivering_campaign(world, with_line_item=False)
    set_clock(world, AUCTION_AT)
    return world


def _bids_by_line_item(world, auction_key="auction"):
    """Re-read the auction's bid rows and index them by line item."""
    rows, _ = validate_paginated(
        api_client.list_auction_bids(
            AUCTION_SERVICE, auction_event_id=world[auction_key]["id"]
        )
    )
    return {row["line_item_id"]: row for row in rows}


def _expected_relevance(overlap_ratio, margin_pct):
    """Compose one candidate's relevance from the four documented terms."""
    return round_half_up(
        0.60 * overlap_ratio + 0.25 * margin_pct + HERO_BOOST + SEGMENT_BONUS, 4
    )


HI_RELEVANCE = _expected_relevance(1.0, HI_MARGIN_PCT)
LO_RELEVANCE = _expected_relevance(0.5, LO_MARGIN_PCT)


def test_the_headroom_clamp_and_the_relevance_exponent_decide_the_winner():
    """The starved high bidder still wins, because relevance is exponentiated.

    PRD 3.6: "The headroom is the smallest of the applicable caps. The effective bid is
    the smaller of the line item's `bid_cents` and that headroom, so a constrained line
    item bids down rather than being excluded outright."

    PRD 3.6: "The line-item cap is `daily_budget_cents` less the sum of `billable_cents`
    over the line item's engagement events whose `occurred_at` falls in the day window.
    The campaign cap is the campaign's daily pacing allowance from 3.3 less the sum of
    `settled_spend_cents` over settled auctions won by any line item of that campaign
    inside the day window. The advertiser cap is `self_serve_daily_spend_cap_cents` less
    the same day's spend across all of the advertiser's campaigns, and it applies **only**
    when the advertiser's `service_model` is `SELF_SERVE`; a `MANAGED` advertiser
    contributes no third cap."

    PRD 3.6: "`quality_adjusted_score` is the effective bid multiplied by
    `relevance_score` raised to the power of the slot's `relevance_weight`, multiplied by
    the tier multiplier, rounded half-up to four decimal places."

    Design: Difficulty/combinatorial_formula/cf_headroom_min_exponent_tier_bid_ranking
    """
    world = _ranking_world()
    build_awarded_auction(
        world, request_context_query=REQUEST_QUERY, shopper_segment=SHOPPER_SEGMENT
    )
    hi_id = world["line_item_hi"]["id"]
    lo_id = world["line_item_lo"]["id"]
    bids = _bids_by_line_item(world)

    assert HI_RELEVANCE == 0.81
    assert LO_RELEVANCE == 0.56
    assert bids[hi_id]["relevance_score"] == HI_RELEVANCE
    assert bids[lo_id]["relevance_score"] == LO_RELEVANCE
    assert_relevance_score_in_range(bids[hi_id]["relevance_score"])
    assert bids[hi_id]["raw_bid_cents"] == HI_BID_CENTS

    # The high bidder's effective bid is its daily budget; the low bidder's is its bid.
    hi_effective = min(HI_BID_CENTS, HI_DAILY_BUDGET_CENTS, CAMPAIGN_DAILY_CAP_CENTS)
    lo_effective = min(LO_BID_CENTS, LO_DAILY_BUDGET_CENTS, CAMPAIGN_DAILY_CAP_CENTS)
    assert hi_effective == 700
    assert lo_effective == 1200

    hi_score = round_half_up(
        hi_effective * HI_RELEVANCE**SLOT_RELEVANCE_WEIGHT * TIER_1_MULTIPLIER, 4
    )
    lo_score = round_half_up(
        lo_effective * LO_RELEVANCE**SLOT_RELEVANCE_WEIGHT * TIER_1_MULTIPLIER, 4
    )
    assert hi_score == 505.197
    assert lo_score == 413.952
    assert bids[hi_id]["quality_adjusted_score"] == hi_score
    assert bids[lo_id]["quality_adjusted_score"] == lo_score

    # Multiplying by relevance linearly would have reversed the ranking, and skipping the
    # headroom clamp would have scored the raw bid instead of the effective one.
    assert bids[hi_id]["quality_adjusted_score"] != round_half_up(
        hi_effective * HI_RELEVANCE * TIER_1_MULTIPLIER, 4
    )
    assert bids[lo_id]["quality_adjusted_score"] != round_half_up(
        lo_effective * LO_RELEVANCE * TIER_1_MULTIPLIER, 4
    )
    assert bids[hi_id]["quality_adjusted_score"] != round_half_up(
        HI_BID_CENTS * HI_RELEVANCE**SLOT_RELEVANCE_WEIGHT * TIER_1_MULTIPLIER, 4
    )

    assert bids[hi_id]["rank"] == 1
    assert bids[hi_id]["outcome"] == "WON"
    assert bids[hi_id]["filter_reason"] == "NONE"
    assert bids[lo_id]["rank"] == 2
    assert bids[lo_id]["outcome"] == "LOST"
    assert bids[lo_id]["filter_reason"] == "NONE"

    auction = world["auction"]
    assert auction["candidate_count"] == 2
    assert auction["winner_score"] == hi_score
    assert auction["second_best_score"] == lo_score
    assert auction["winning_line_item_id"] == hi_id
    assert auction["no_fill_reason"] == "NONE"


def test_the_clearing_price_lifts_the_runner_up_score_through_the_winners_multiplier():
    """Second price divides by the winner's own multiplier, rounds up once, then clamps.

    PRD 3.6: "Let the winner's multiplier be the winner's `relevance_score` raised to the
    power of the slot's `relevance_weight`, multiplied by the winner's tier multiplier.
    When no runner-up survived, the raw clearing figure is the slot's `floor_cpc_cents`
    exactly. When a runner-up exists, the raw clearing figure is `second_best_score`
    divided by the winner's multiplier, plus one."

    PRD 3.6: "That raw figure is rounded **up** to the next whole cent, and only then
    clamped: the result is the larger of `floor_cpc_cents` and the smaller of the winner's
    effective bid and the rounded-up figure. The rounding-up happens exactly once, before
    the clamp, never after it."

    Design: Difficulty/combinatorial_formula/cf_headroom_min_exponent_tier_bid_ranking
    """
    world = _ranking_world()
    build_awarded_auction(
        world, request_context_query=REQUEST_QUERY, shopper_segment=SHOPPER_SEGMENT
    )
    auction = world["auction"]

    winner_multiplier = HI_RELEVANCE**SLOT_RELEVANCE_WEIGHT * TIER_1_MULTIPLIER
    raw = auction["second_best_score"] / winner_multiplier + 1
    assert 574 < raw < 575
    rounded_up = -(-round(raw, 10) // 1)
    hi_effective = min(HI_BID_CENTS, HI_DAILY_BUDGET_CENTS)
    expected = max(SLOT_FLOOR_CENTS, min(hi_effective, int(rounded_up)))
    assert expected == 575
    assert auction["clearing_price_cents"] == expected
    assert auction["status"] == "AWARDED"

    # The clamp is loose at both ends here: the figure clears the floor and stays under
    # the winner's effective bid, so what is observed is the rounded-up quotient itself.
    assert SLOT_FLOOR_CENTS < auction["clearing_price_cents"] < hi_effective
    assert auction["settled_spend_cents"] == 0


def test_both_line_items_reach_the_top_tier_from_the_plans_remaining_ratio():
    """The tier multiplier is threshold-derived, and the threshold is met by both rows.

    PRD 3.5: "Let the denominator be the funding plan's `committed_total_cents` plus its
    `top_up_total_cents`, and let the remaining ratio be 0.0 when that denominator is 0
    and otherwise the plan's `available_cents` divided by that denominator, compared
    without rounding. When the advertiser's `service_model` is `MANAGED` **and** the
    remaining ratio is at least 0.50, the tier is `TIER_1`."

    PRD 3.6: "The tier multiplier is 1.10 for `TIER_1`, 1.00 for `TIER_2` and 0.90 for
    `TIER_3`, using the `priority_tier` recomputed at ranking time."

    PRD 3.6: "The per-assignment `relevance_contribution` is, for each row in that same
    active-and-eligible set, 0.25 multiplied by the product's `margin_pct` divided by the
    count of rows in the set with that count floored at 1, rounded half-up to four decimal
    places."

    Design: Difficulty/combinatorial_formula/cf_headroom_min_exponent_tier_bid_ranking
    """
    world = _ranking_world()
    build_awarded_auction(
        world, request_context_query=REQUEST_QUERY, shopper_segment=SHOPPER_SEGMENT
    )

    plan = reread_plan(world)
    assert plan["available_cents"] == PLAN_COMMITTED_CENTS - CAMPAIGN_ALLOCATED_CENTS
    assert plan["available_cents"] == 35000000
    remaining_ratio = plan["available_cents"] / (
        plan["committed_total_cents"] + plan["top_up_total_cents"]
    )
    assert remaining_ratio == 0.875
    assert remaining_ratio >= 0.50

    assert reread_line_item(world, "line_item_hi")["priority_tier"] == "TIER_1"
    assert reread_line_item(world, "line_item_lo")["priority_tier"] == "TIER_1"

    # Each line item carries exactly one assignment, so that assignment carries the whole
    # margin term of its line item's relevance.
    for key, margin_pct in (
        ("line_item_hi", HI_MARGIN_PCT),
        ("line_item_lo", LO_MARGIN_PCT),
    ):
        rows, _ = validate_paginated(
            api_client.list_product_assignments(
                CATALOG_OPS, line_item_id=world[key]["id"]
            )
        )
        assert len(rows) == 1
        assert rows[0]["relevance_contribution"] == round_half_up(0.25 * margin_pct, 4)
    assert round_half_up(0.25 * HI_MARGIN_PCT, 4) == 0.05
    assert round_half_up(0.25 * LO_MARGIN_PCT, 4) == 0.1


# ---------------------------------------------------------------------------
# The cost-per-mille settlement charge
# ---------------------------------------------------------------------------

CPM_SLOT_FLOOR_CENTS = 1250
CPM_BID_CENTS = 3000
CPM_DAILY_BUDGET_CENTS = 200000
CPM_MARGIN_PCT = 0.4
IMPRESSION_TIMES = (
    "2026-08-05T10:01:00Z",
    "2026-08-05T10:02:00Z",
    "2026-08-05T10:03:00Z",
    "2026-08-05T10:04:00Z",
    "2026-08-05T10:05:00Z",
    "2026-08-05T10:06:00Z",
)
CLICK_TIME = "2026-08-05T10:07:00Z"


def _cpm_settled_world():
    """One cost-per-mille line item, one awarded auction, six impressions and a click.

    The line item is the only candidate on the slot, so no runner-up survives and the
    clearing price lands exactly on the slot floor of 1250 cents — a figure whose share of
    a thousand impressions, 1.25 cents, is deliberately not a whole number of cents. The
    impressions are recorded a minute apart so their `occurred_at` order is unambiguous,
    and the interleaved click is recorded last.
    """
    world = build_active_managed_advertiser()
    build_active_budget_plan(
        world,
        committed_total_cents=PLAN_COMMITTED_CENTS,
        trade_fund_share_cents=0,
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-10-01T00:00:00Z",
    )
    build_placement_slot(
        world,
        page_type="HOMEPAGE",
        max_concurrent_line_items=2,
        floor_cpc_cents=CPM_SLOT_FLOOR_CENTS,
        relevance_weight=1.0,
        buffer_minutes=0,
    )
    build_catalog_product(world, category_code="GROCERY", margin_pct=CPM_MARGIN_PCT)
    build_draft_campaign(
        world,
        channel_mix="ONSITE_ONLY",
        flight_start_at=CAMPAIGN_FLIGHT[0],
        flight_end_at=CAMPAIGN_FLIGHT[1],
        allocated_budget_cents=CAMPAIGN_ALLOCATED_CENTS,
        daily_cap_cents=CAMPAIGN_DAILY_CAP_CENTS,
    )
    build_eligible_line_item(
        world,
        bid_cents=CPM_BID_CENTS,
        bid_type="CPM",
        daily_budget_cents=CPM_DAILY_BUDGET_CENTS,
        flight_start_at=CAMPAIGN_FLIGHT[0],
        flight_end_at=CAMPAIGN_FLIGHT[1],
        category_code="GROCERY",
        keyword_match_terms=["coffee"],
    )
    build_delivering_campaign(world, with_line_item=False)
    set_clock(world, AUCTION_AT)
    build_awarded_auction(
        world, request_context_query="coffee", shopper_segment=SHOPPER_SEGMENT
    )
    for moment in IMPRESSION_TIMES:
        build_engagement_event(world, event_type="IMPRESSION", occurred_at=moment)
    build_engagement_event(world, event_type="CLICK", occurred_at=CLICK_TIME)
    return world


def _settle(world):
    """Settle the awarded auction and return the settled row."""
    world["auction"] = validate_success(
        api_client.settle_auction_event(world["auction"]["id"], None, AUCTION_SERVICE)
    )
    return world["auction"]


def _reread_engagements(world):
    """Re-read the seven recorded engagements in the order they were created."""
    return [
        validate_success(api_client.get_engagement_event(event["id"], AUCTION_SERVICE))
        for event in world["engagements"]
    ]


def test_the_cpm_charge_is_summed_over_the_auction_before_it_is_rounded():
    """Six shares of 1.25 cents round to eight cents together and to six apart.

    PRD 3.6: "Under `CPM`, the billable set is every `IMPRESSION` and `OFFSITE_VIEW` event
    on the auction: `settled_spend_cents` is `clearing_price_cents` multiplied by the count
    of billable events divided by 1000, rounded half-up to whole cents."

    PRD 3.6: "When no runner-up survived, the raw clearing figure is the slot's
    `floor_cpc_cents` exactly."

    Design: Difficulty/combinatorial_formula/cf_cpm_sum_then_round_remainder_waterfall
    """
    world = _cpm_settled_world()
    awarded = world["auction"]

    # A single candidate leaves no runner-up, so the clearing figure is the bare floor.
    assert awarded["candidate_count"] == 1
    assert awarded["second_best_score"] is None
    assert awarded["clearing_price_cents"] == CPM_SLOT_FLOOR_CENTS
    expected_relevance = _expected_relevance(1.0, CPM_MARGIN_PCT)
    assert expected_relevance == 0.86
    assert awarded["winner_score"] == round_half_up(
        CPM_BID_CENTS * expected_relevance * TIER_1_MULTIPLIER, 4
    )

    settled = _settle(world)
    billable_count = len(IMPRESSION_TIMES)
    expected_total = round_half_up_int(
        settled["clearing_price_cents"] * billable_count / 1000
    )
    assert expected_total == 8
    assert settled["status"] == "SETTLED"
    assert settled["settled_spend_cents"] == expected_total

    # Rounding each event's own 1.25-cent share first, or distributing only the truncated
    # base, would both have charged six cents; truncating the 7.5-cent sum would charge
    # seven.
    per_event = round_half_up_int(settled["clearing_price_cents"] / 1000)
    assert settled["settled_spend_cents"] != per_event * billable_count == 6
    assert settled["settled_spend_cents"] != 7


def test_the_rounded_total_is_distributed_one_cent_at_a_time_in_time_order():
    """The two residual cents land on the two earliest impressions and nowhere else.

    PRD 3.6: "That total is then distributed across the billable events so the parts sum
    exactly to the whole: each billable event receives a base of `clearing_price_cents`
    divided by 1000 truncated toward zero, and the remainder — the settled total less the
    base multiplied by the billable count — is distributed one additional cent at a time to
    the billable events in ascending order of `occurred_at`, with ties broken by ascending
    `created_at` and never by identifier. Non-billable events under `CPM` receive
    `billable_cents` 0."

    Design: Difficulty/combinatorial_formula/cf_cpm_sum_then_round_remainder_waterfall
    """
    world = _cpm_settled_world()
    settled = _settle(world)
    events = _reread_engagements(world)
    assert len(events) == len(IMPRESSION_TIMES) + 1

    base = settled["clearing_price_cents"] // 1000
    remainder = settled["settled_spend_cents"] - base * len(IMPRESSION_TIMES)
    assert base == 1
    assert remainder == 2

    impressions = [event for event in events if event["event_type"] == "IMPRESSION"]
    impressions.sort(key=lambda event: (event["occurred_at"], event["created_at"]))
    assert [parse_utc(event["occurred_at"]) for event in impressions] == [
        parse_utc(moment) for moment in IMPRESSION_TIMES
    ]
    assert [event["billable_cents"] for event in impressions] == [2, 2, 1, 1, 1, 1]

    clicks = [event for event in events if event["event_type"] == "CLICK"]
    assert len(clicks) == 1
    assert clicks[0]["billable_cents"] == 0

    # The parts sum exactly to the whole, which is what the residue distribution is for.
    assert sum(event["billable_cents"] for event in events) == 8
    assert sum(event["billable_cents"] for event in events) == (
        settled["settled_spend_cents"]
    )


def test_the_settled_cpm_charge_reaches_the_line_item_and_its_campaign():
    """Level one of the cascade adds the whole settled figure, residue included.

    PRD 3.6: "Level one adds `settled_spend_cents` to the winning line item's
    `spend_cents` and to its campaign's `delivered_spend_cents`."

    PRD 3.6: "`billable_cents` is 0 at the moment the event is recorded and is populated
    when the auction settles; recording an engagement therefore moves neither
    `spend_cents` nor `delivered_spend_cents` on its own."

    Design: Difficulty/combinatorial_formula/cf_cpm_sum_then_round_remainder_waterfall
    """
    world = _cpm_settled_world()

    # Seven engagements are on record and none of them has moved any money yet.
    assert all(event["billable_cents"] == 0 for event in _reread_engagements(world))
    assert reread_line_item(world)["spend_cents"] == 0
    assert reread_campaign(world)["delivered_spend_cents"] == 0

    settled = _settle(world)
    assert settled["settled_spend_cents"] == 8
    assert reread_line_item(world)["spend_cents"] == 8
    assert reread_campaign(world)["delivered_spend_cents"] == 8

    # The plan is far from exhausted, so the campaign is still delivering.
    plan = reread_plan(world)
    assert plan["plan_status"] == "ACTIVE"
    assert reread_campaign(world)["delivery_status"] == "DELIVERING"
    assert plan["consumed_cents"] == 8
