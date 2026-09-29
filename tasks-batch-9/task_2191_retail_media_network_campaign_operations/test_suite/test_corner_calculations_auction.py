"""Auction arithmetic at the points where the PRD pins the rounding order.

Four figures are computed on one shared two-candidate slot: the composed
`relevance_score`, the per-assignment `relevance_contribution`, the second-price clearing
figure that is rounded up exactly once before it is clamped, and the two settlement
bases. The two candidates differ only in their bid, their match terms and their hero
product's margin, so every divergence in their scores is attributable to those three
inputs and nothing else.

The plan commits 3,000,000 cents and the campaign draws 1,000,000 short of that, which
leaves the remaining ratio at one third — comfortably above the 0.20 self-serve threshold
and below the 0.50 managed one, so both candidates rank as `TIER_2` and the tier
multiplier is exactly 1.00 for each of them.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    AUCTION_SERVICE,
    CATALOG_OPS,
    api_client,
    assert_decimal_places,
    build_awarded_auction,
    build_campaign_ready_world,
    build_catalog_product,
    build_delivering_campaign,
    build_eligible_line_item,
    build_engagement_event,
    build_open_auction,
    build_placement_slot,
    build_ranked_auction,
    reread_campaign,
    reread_line_item,
    reread_plan,
    validate_paginated,
    validate_success,
)

FLIGHT_START = "2026-08-01T00:00:00Z"
FLIGHT_END = "2026-08-11T00:00:00Z"

# The query carries both of the premium line item's terms and both of the thin-margin
# line item's single term, so the overlap ratio is 1.0 on both sides and the only
# surviving difference between them is the margin average.
QUERY = "red shoes sale"
SEGMENT = "RETURNING"

PREMIUM = "premium_line_item"
THIN = "thin_margin_line_item"
CPM_ITEM = "cpm_line_item"
CPM_SLOT = "cpm_slot"
THIN_PRODUCT = "thin_margin_product"

SHOPPER = "sh_1"

CPM_IMPRESSION_MOMENTS = (
    "2026-08-01T12:05:00Z",
    "2026-08-01T12:06:00Z",
    "2026-08-01T12:07:00Z",
)


def _two_candidate_delivering_world():
    """One delivering campaign with two serving line items competing for one slot.

    The slot admits two concurrent line items and floors bids at 50 cents, which both
    candidates clear. The premium line item bids 200 against a 0.40-margin hero product
    and the thin-margin one bids 150 against a 0.20-margin hero product; both flights
    match the campaign flight exactly, so the auction's `requested_at` falls inside each.
    """
    world = build_campaign_ready_world(
        plan={"committed_total_cents": 3000000, "trade_fund_share_cents": 0},
        slot={
            "max_concurrent_line_items": 2,
            "floor_cpc_cents": 50,
            "relevance_weight": 1.0,
        },
        product={
            "category_code": "FOOTWEAR",
            "title": "red running shoes",
            "margin_pct": 0.4,
        },
        campaign={
            "channel_mix": "ONSITE_ONLY",
            "flight_start_at": FLIGHT_START,
            "flight_end_at": FLIGHT_END,
            "allocated_budget_cents": 2000000,
            "daily_cap_cents": 200000,
            "attribution_model": "LAST_TOUCH",
            "attribution_window_days": 14,
        },
    )
    build_catalog_product(
        world,
        key=THIN_PRODUCT,
        category_code="FOOTWEAR",
        title="red canvas shoes",
        margin_pct=0.2,
    )
    build_eligible_line_item(
        world,
        key=PREMIUM,
        product_key="product",
        bid_cents=200,
        bid_type="CPC",
        keyword_match_terms=["red", "shoes"],
        category_code="FOOTWEAR",
        flight_start_at=FLIGHT_START,
        flight_end_at=FLIGHT_END,
        daily_budget_cents=100000,
    )
    build_eligible_line_item(
        world,
        key=THIN,
        product_key=THIN_PRODUCT,
        bid_cents=150,
        bid_type="CPC",
        keyword_match_terms=["red"],
        category_code="FOOTWEAR",
        flight_start_at=FLIGHT_START,
        flight_end_at=FLIGHT_END,
        daily_budget_cents=100000,
    )
    build_delivering_campaign(world, with_line_item=False)
    return world


def _sole_assignment(world, line_item_key):
    """Read back the one hero assignment a line item carries."""
    rows, _meta = validate_paginated(
        api_client.list_product_assignments(
            CATALOG_OPS, line_item_id=world[line_item_key]["id"]
        )
    )
    assert len(rows) == 1
    return rows[0]


def test_relevance_composes_overlap_margin_hero_boost_and_segment_bonus():
    """Two candidates differing only in hero margin score 0.8300 and 0.7800.

    PRD 3.6: "`relevance_score` is the sum of 0.60 times the overlap ratio, 0.25 times
    the margin average, the hero boost and the segment bonus, capped above at 1.0000, and
    rounded half-up to four decimal places."

    PRD 3.6: "The per-assignment `relevance_contribution` is, for each row in that same
    active-and-eligible set, 0.25 multiplied by the product's `margin_pct` divided by the
    count of rows in the set with that count floored at 1, rounded half-up to four decimal
    places; every assignment outside the set carries 0.0000."

    PRD 3.6: "`quality_adjusted_score` is the effective bid multiplied by
    `relevance_score` raised to the power of the slot's `relevance_weight`, multiplied by
    the tier multiplier, rounded half-up to four decimal places."

    PRD 3.6: "Ranking also sets `candidate_count` to the number of bid rows created, sets
    `winner_score` and `second_best_score` from the surviving pool, persists the computed
    `relevance_score` and `quality_adjusted_score` back onto each ranked line item, and
    leaves `winning_line_item_id` null until the award."

    Design: Corner/calculations/relevance_composition_applies_hero_boost_margin_and_segment_bonus
    """
    world = _two_candidate_delivering_world()
    build_open_auction(
        world, request_context_query=QUERY, shopper_segment=SEGMENT
    )

    ranked = validate_success(
        api_client.rank_auction_event(world["auction"]["id"], None, AUCTION_SERVICE)
    )

    assert ranked["status"] == "RANKED"
    assert ranked["candidate_count"] == 2
    assert ranked["winner_score"] == 166.0000
    assert ranked["second_best_score"] == 117.0000

    premium = reread_line_item(world, PREMIUM)
    thin = reread_line_item(world, THIN)

    # 0.60 * 1.0 + 0.25 * 0.40 + 0.10 + 0.03 against 0.60 * 1.0 + 0.25 * 0.20 + 0.10 + 0.03.
    assert premium["relevance_score"] == 0.8300
    assert thin["relevance_score"] == 0.7800
    assert_decimal_places(premium["relevance_score"], 4, "premium relevance_score")
    assert_decimal_places(thin["relevance_score"], 4, "thin relevance_score")

    # The exponent is 1.0 and both candidates rank TIER_2, so the score is bid * relevance.
    assert premium["quality_adjusted_score"] == 166.0000
    assert thin["quality_adjusted_score"] == 117.0000

    # 0.25 * margin_pct over a single-row active-and-eligible set.
    assert _sole_assignment(world, PREMIUM)["relevance_contribution"] == 0.1000
    assert _sole_assignment(world, THIN)["relevance_contribution"] == 0.0500


def test_second_price_clearing_rounds_up_once_before_the_floor_and_bid_clamp():
    """117.0000 over 0.8300 plus one cent ceils to 142, not to 141 or the raw 141.96.

    PRD 3.6: "When a runner-up exists, the raw clearing figure is `second_best_score`
    divided by the winner's multiplier, plus one — the one-cent increment that puts the
    winner just above the runner-up's willingness."

    PRD 3.6: "That raw figure is rounded **up** to the next whole cent, and only then
    clamped: the result is the larger of `floor_cpc_cents` and the smaller of the winner's
    effective bid and the rounded-up figure."

    PRD 3.6: "The rounding-up happens exactly once, before the clamp, never after it, so a
    raw figure below the floor still yields exactly the floor and a raw figure above the
    winner's own effective bid still yields exactly that effective bid."

    Design: Corner/calculations/second_price_clearing_ceils_raw_before_clamping_to_142
    """
    world = _two_candidate_delivering_world()
    build_ranked_auction(
        world, request_context_query=QUERY, shopper_segment=SEGMENT
    )

    awarded = validate_success(
        api_client.award_auction_event(world["auction"]["id"], None, AUCTION_SERVICE)
    )

    assert awarded["status"] == "AWARDED"
    assert awarded["winning_line_item_id"] == world[PREMIUM]["id"]
    assert awarded["no_fill_reason"] == "NONE"

    # 117.0000 / 0.8300 = 140.96385..., plus one cent is 141.96385..., ceiling 142.
    assert awarded["clearing_price_cents"] == 142
    # Truncating instead of ceiling would give 141; the floor of 50 and the winner's own
    # effective bid of 200 both leave the ceiled figure untouched.
    assert awarded["clearing_price_cents"] != 141


def test_cost_per_click_settlement_bills_the_clicks_and_zeroes_the_impression():
    """Three engagements settle at 284 cents because only the two clicks are billable.

    PRD 3.6: "Under `CPC`, only `CLICK` events are billable: `settled_spend_cents` is
    `clearing_price_cents` multiplied by the count of `CLICK` events on the auction, each
    `CLICK` event's `billable_cents` is set to the full `clearing_price_cents`, and every
    `IMPRESSION` and `OFFSITE_VIEW` event's `billable_cents` is set to 0."

    PRD 3.6: "Level one adds `settled_spend_cents` to the winning line item's
    `spend_cents` and to its campaign's `delivered_spend_cents`."

    PRD 3.2: "`available_cents` is `committed_total_cents` plus `top_up_total_cents`, less
    `reserved_cents`, less `consumed_cents`; it may go negative only through
    over-delivery."

    Design: Corner/calculations/cpc_settlement_bills_click_events_only_and_ignores_impressions
    """
    world = _two_candidate_delivering_world()
    build_awarded_auction(
        world, request_context_query=QUERY, shopper_segment=SEGMENT
    )
    for event_type in ("IMPRESSION", "CLICK", "CLICK"):
        build_engagement_event(
            world,
            event_type=event_type,
            line_item_key=PREMIUM,
            shopper_hash=SHOPPER,
        )
    impression, first_click, second_click = world["engagements"][:3]

    settled = validate_success(
        api_client.settle_auction_event(world["auction"]["id"], None, AUCTION_SERVICE)
    )

    assert settled["status"] == "SETTLED"
    assert settled["settled_spend_cents"] == 284

    reread = {
        row["id"]: validate_success(
            api_client.get_engagement_event(row["id"], AUCTION_SERVICE)
        )
        for row in (impression, first_click, second_click)
    }
    assert reread[impression["id"]]["billable_cents"] == 0
    assert reread[first_click["id"]]["billable_cents"] == 142
    assert reread[second_click["id"]]["billable_cents"] == 142

    assert reread_line_item(world, PREMIUM)["spend_cents"] == 284
    # The losing candidate is charged nothing at all.
    assert reread_line_item(world, THIN)["spend_cents"] == 0
    assert reread_campaign(world)["delivered_spend_cents"] == 284

    plan = reread_plan(world)
    assert plan["consumed_cents"] == 284
    assert plan["available_cents"] == 999716


def test_cost_per_mille_settlement_rounds_once_then_waterfalls_the_remainder():
    """A 10.5-cent aggregate rounds to 11 and is handed out as 4, 4 and 3.

    PRD 3.6: "Under `CPM`, the billable set is every `IMPRESSION` and `OFFSITE_VIEW` event
    on the auction: `settled_spend_cents` is `clearing_price_cents` multiplied by the count
    of billable events divided by 1000, rounded half-up to whole cents."

    PRD 3.6: "That total is then distributed across the billable events so the parts sum
    exactly to the whole: each billable event receives a base of `clearing_price_cents`
    divided by 1000 truncated toward zero, and the remainder — the settled total less the
    base multiplied by the billable count — is distributed one additional cent at a time
    to the billable events in ascending order of `occurred_at`, with ties broken by
    ascending `created_at` and never by identifier."

    PRD 3.6: "When no runner-up survived, the raw clearing figure is the slot's
    `floor_cpc_cents` exactly."

    Design: Corner/calculations/cpm_settlement_rounds_once_then_waterfalls_remainder_by_occurred_at
    """
    world = _two_candidate_delivering_world()
    build_placement_slot(
        world,
        key=CPM_SLOT,
        max_concurrent_line_items=1,
        floor_cpc_cents=3500,
        relevance_weight=1.0,
    )
    build_eligible_line_item(
        world,
        key=CPM_ITEM,
        slot_key=CPM_SLOT,
        product_key="product",
        bid_cents=4500,
        bid_type="CPM",
        keyword_match_terms=["red", "shoes"],
        category_code="FOOTWEAR",
        flight_start_at=FLIGHT_START,
        flight_end_at=FLIGHT_END,
        daily_budget_cents=100000,
    )
    world[CPM_ITEM] = validate_success(
        api_client.activate_line_item(world[CPM_ITEM]["id"], None, ACCOUNT_MANAGER)
    )
    assert world[CPM_ITEM]["line_item_status"] == "SERVING"

    build_awarded_auction(
        world,
        key="cpm_auction",
        slot_key=CPM_SLOT,
        request_context_query=QUERY,
        shopper_segment=SEGMENT,
    )
    impressions = []
    for moment in CPM_IMPRESSION_MOMENTS:
        build_engagement_event(
            world,
            event_type="IMPRESSION",
            auction_key="cpm_auction",
            line_item_key=CPM_ITEM,
            product_key="product",
            occurred_at=moment,
            shopper_hash=SHOPPER,
        )
        impressions.append(world["engagement"])

    settled = validate_success(
        api_client.settle_auction_event(
            world["cpm_auction"]["id"], None, AUCTION_SERVICE
        )
    )

    # The two on-site candidates sit on a different slot and are therefore not candidates.
    assert settled["candidate_count"] == 1
    assert settled["clearing_price_cents"] == 3500
    # 3500 * 3 / 1000 is 10.5, which rounds half-up to 11 — not 10, and not 3 * 4 = 12.
    assert settled["settled_spend_cents"] == 11

    billable = [
        validate_success(
            api_client.get_engagement_event(row["id"], AUCTION_SERVICE)
        )["billable_cents"]
        for row in impressions
    ]
    assert billable == [4, 4, 3]
    assert sum(billable) == settled["settled_spend_cents"]

    assert reread_line_item(world, CPM_ITEM)["spend_cents"] == 11
    assert reread_campaign(world)["delivered_spend_cents"] == 11
