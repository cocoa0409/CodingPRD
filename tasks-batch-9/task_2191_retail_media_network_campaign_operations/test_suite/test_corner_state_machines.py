"""Delivery lifecycle transitions for campaigns, line items and auctions.

Every resource in the network carries its own lifecycle, and the PRD is explicit about
which move is accepted from which state, what each accepted move does to the numbers
around it, and which refusal identifier answers a move that was never declared. The
tests here walk one accepted transition at a time and then push the same resource
through a move its current state does not declare, checking both that the refusal names
the documented identifier and that nothing moved on the way out.

The worlds are deliberately built with round figures — a two-million-cent plan carrying
a one-million-cent campaign whose single line item spends a hundred thousand a day over
a ten-day flight — so the reservation released by a completion or an archive is the same
figure the reservation taken at approval, and a drift of one cent is visible.
"""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER,
    AUCTION_SERVICE,
    BILLING_OPS,
    CATALOG_OPS,
    ERR_AUCTION_INVALID_STATE,
    ERR_CAMPAIGN_NOT_DELIVERING,
    ERR_LINE_ITEM_INVALID_STATE,
    NETWORK_ADMIN,
    api_client,
    assert_budget_plan_identity,
    assert_campaign_dimensions,
    assert_line_item_paused,
    assert_no_drift,
    assert_occupancy_count,
    assert_version_unchanged,
    adjust_product_stock,
    build_campaign_ready_world,
    build_catalog_product,
    build_delivering_world,
    build_eligible_line_item,
    build_scheduled_campaign,
    build_second_campaign_on_same_plan,
    build_second_line_item_on_same_slot,
    build_settled_auction,
    pause_campaign,
    parse_utc,
    reread_advertiser,
    reread_campaign,
    reread_line_item,
    reread_plan,
    reread_product,
    reread_slot,
    validate_error,
    validate_success,
)

# The plan is all cash, so `cash_share_cents` equals the commitment and the trade fund
# pool never enters the arithmetic below.
PLAN_COMMITTED_CENTS = 2000000
CAMPAIGN_ALLOCATED_CENTS = 1000000

# A hundred thousand cents a day across exactly ten whole twenty-four-hour periods, so
# the line item's own reservation is a million cents on the nose.
LINE_ITEM_DAILY_BUDGET_CENTS = 100000
LINE_ITEM_FLIGHT_START = "2026-08-05T00:00:00Z"
LINE_ITEM_FLIGHT_END = "2026-08-15T00:00:00Z"
LINE_ITEM_RESERVED_CENTS = 1000000

# `build_delivering_world` activates at the campaign's flight start, which is where the
# logical clock therefore stands for every test in this module.
DELIVERY_CLOCK = "2026-08-05T00:00:00Z"
CAMPAIGN_FLIGHT_END = "2026-08-20T00:00:00Z"

SLOT_FLOOR_CPC_CENTS = 40
SETTLED_SPEND_CENTS = 40

SECOND_CAMPAIGN_ALLOCATED_CENTS = 500000


def _plan_overrides() -> dict:
    return {"committed_total_cents": PLAN_COMMITTED_CENTS, "trade_fund_share_cents": 0}


def _line_item_overrides() -> dict:
    return {
        "flight_start_at": LINE_ITEM_FLIGHT_START,
        "flight_end_at": LINE_ITEM_FLIGHT_END,
        "daily_budget_cents": LINE_ITEM_DAILY_BUDGET_CENTS,
    }


def _delivering_world(**kwargs) -> dict:
    """One campaign DELIVERING with one line item SERVING on round figures."""
    return build_delivering_world(
        plan=_plan_overrides(),
        campaign={"allocated_budget_cents": CAMPAIGN_ALLOCATED_CENTS},
        line_item=_line_item_overrides(),
        **kwargs,
    )


def test_activating_an_eligible_line_item_starts_it_serving_without_taking_new_occupancy():
    """A second eligible line item activated under a delivering campaign starts serving.

    PRD 3.4: "Activation moves an `ELIGIBLE` line item to `SERVING` and is available to
    `NetworkAdmin`, `AccountManager` and the owning `AdvertiserUser`; the system performs
    the same transition for every eligible line item when the owning campaign reaches
    `DELIVERING`."
    PRD 3.4: "Activation sets `pause_reason` to `NONE` and recomputes `priority_tier`."
    PRD 3.4: "Catalog eligibility approval ... raises the slot's `occupancy_count` by 1,
    and computes `reserved_cents` as `daily_budget_cents` multiplied by the number of
    whole twenty-four-hour periods in the line item's flight, with that day count floored
    at 1."

    Occupancy was already taken at eligibility approval, so activation must not take it a
    second time: the slot reads two occupants both before and after the call.

    Design: Corner/state_machines/line_item_activate_moves_eligible_to_serving_and_holds_slot_occupancy
    """
    world = _delivering_world()
    build_second_line_item_on_same_slot(
        world, key="second_line_item", activate=False, **_line_item_overrides()
    )

    slot_before = reread_slot(world)
    assert_occupancy_count(slot_before, 2)
    assert world["second_line_item"]["line_item_status"] == "ELIGIBLE"

    line_item = validate_success(
        api_client.activate_line_item(
            world["second_line_item"]["id"], None, ACCOUNT_MANAGER
        )
    )
    assert line_item["line_item_status"] == "SERVING"
    assert line_item["pause_reason"] == "NONE"
    assert line_item["reserved_cents"] == LINE_ITEM_RESERVED_CENTS
    assert line_item["eligible_product_count"] == 1
    # Self-serve advertiser whose plan headroom ratio is 1000000 / 2000000 = 0.50, which
    # clears the 0.20 threshold of the middle tier but not the managed-only top tier.
    assert line_item["priority_tier"] == "TIER_2"

    slot_after = reread_slot(world)
    assert_occupancy_count(slot_after, 2)
    assert_no_drift(
        slot_before["occupancy_count"], slot_after["occupancy_count"], "occupancy_count"
    )

    campaign = reread_campaign(world)
    assert_campaign_dimensions(campaign, "DELIVERING", "ACCRUING")

    plan = reread_plan(world)
    assert plan["plan_status"] == "ACTIVE"
    assert plan["reserved_cents"] == CAMPAIGN_ALLOCATED_CENTS
    assert plan["available_cents"] == PLAN_COMMITTED_CENTS - CAMPAIGN_ALLOCATED_CENTS
    assert_budget_plan_identity(plan)


def test_completing_a_delivering_campaign_moves_both_status_dimensions_at_once():
    """Completion ends the line items, releases the reservation and advances billing.

    PRD 3.3: "Completion is available to `NetworkAdmin`, `AccountManager` and
    `BillingOps` from `DELIVERING` ... an operator may complete early, but the sweep only
    acts at or after `flight_end_at`."
    PRD 3.3: "Completion moves every own line item in `ELIGIBLE`, `SERVING`, `OOS_PAUSED`
    or `MANUAL_PAUSED` to `ENDED`, and each line item entering `ENDED` surrenders its slot
    occupancy, so `occupancy_count` falls by one on each affected slot. `COMPLETED` is not
    a reserving status, so the plan's `reserved_cents` is recomputed downward and its
    `available_cents` upward. The billing dimension fires its own `ACCRUING` to
    `PENDING_INVOICE` transition in the same request."

    Design: Corner/state_machines/campaign_complete_advances_delivery_and_billing_dimensions_independently
    """
    world = _delivering_world()
    plan_before = reread_plan(world)
    assert plan_before["reserved_cents"] == CAMPAIGN_ALLOCATED_CENTS
    assert plan_before["available_cents"] == PLAN_COMMITTED_CENTS - CAMPAIGN_ALLOCATED_CENTS
    assert reread_line_item(world)["line_item_status"] == "SERVING"

    # Completed early: the clock still sits at the flight start, which an operator is
    # allowed to do even though the sweep would not.
    campaign = validate_success(
        api_client.complete_campaign(world["campaign"]["id"], None, BILLING_OPS)
    )
    assert_campaign_dimensions(campaign, "COMPLETED", "PENDING_INVOICE")
    assert campaign["delivered_spend_cents"] == 0

    line_item = reread_line_item(world)
    assert line_item["line_item_status"] == "ENDED"
    assert_occupancy_count(reread_slot(world), 0)

    plan = reread_plan(world)
    assert plan["reserved_cents"] == 0
    assert plan["consumed_cents"] == 0
    assert plan["available_cents"] == PLAN_COMMITTED_CENTS
    assert plan["plan_status"] == "ACTIVE"
    assert_budget_plan_identity(plan)


def test_archiving_a_scheduled_campaign_releases_the_untouched_reservation_exactly():
    """Archive from SCHEDULED restores the plan headroom it held before scheduling.

    PRD 3.3: "From `SCHEDULED` it requires `delivered_spend_cents` to be exactly 0; it
    moves every own line item in `ELIGIBLE`, `PENDING_ELIGIBILITY` or `DRAFT` to `ENDED`,
    each surrendering its slot occupancy, and releases the reservation outright — the
    plan's `reserved_cents` falls by exactly `allocated_budget_cents` and its
    `available_cents` rises by exactly the same amount, restoring the plan's headroom to
    the value it held before the campaign was scheduled."
    PRD 3.3: "Archiving a `SCHEDULED` campaign leaves the billing dimension at
    `UNBILLED`, which is where it already was."
    PRD 2.9: "when that campaign is archived straight out of the scheduled state, the
    allocation is released and the plan's headroom returns to exactly the value it held
    before the reservation."

    Design: Corner/state_machines/scheduled_campaign_archive_reverses_reservation_and_conserves_plan_identity
    """
    world = build_campaign_ready_world(
        plan=_plan_overrides(),
        campaign={"allocated_budget_cents": CAMPAIGN_ALLOCATED_CENTS},
    )
    build_scheduled_campaign(world, **_line_item_overrides())
    assert world["campaign"]["delivery_status"] == "SCHEDULED"

    plan_before = reread_plan(world)
    assert plan_before["reserved_cents"] == CAMPAIGN_ALLOCATED_CENTS
    assert plan_before["available_cents"] == PLAN_COMMITTED_CENTS - CAMPAIGN_ALLOCATED_CENTS
    advertiser_before = reread_advertiser(world)
    # Exposure counts the whole commitment of an active plan, not the part a campaign has
    # reserved out of it, so releasing the reservation must leave it alone.
    assert advertiser_before["credit_exposure_cents"] == PLAN_COMMITTED_CENTS

    campaign = validate_success(
        api_client.archive_campaign(
            world["campaign"]["id"],
            {"archive_reason": "Brief withdrawn before launch"},
            NETWORK_ADMIN,
        )
    )
    assert campaign["delivery_status"] == "ARCHIVED"
    assert campaign["billing_status"] == "UNBILLED"
    assert campaign["delivered_spend_cents"] == 0

    line_item = reread_line_item(world)
    assert line_item["line_item_status"] == "ENDED"
    assert_occupancy_count(reread_slot(world), 0)

    plan = reread_plan(world)
    assert plan["reserved_cents"] == 0
    assert plan["consumed_cents"] == 0
    assert plan["available_cents"] == PLAN_COMMITTED_CENTS
    assert plan["plan_status"] == "ACTIVE"
    assert_budget_plan_identity(plan)
    assert_no_drift(
        PLAN_COMMITTED_CENTS, plan["available_cents"], "plan available_cents"
    )

    advertiser = reread_advertiser(world)
    assert advertiser["credit_exposure_cents"] == PLAN_COMMITTED_CENTS


def test_settling_an_already_settled_auction_is_refused_and_moves_no_money():
    """`SETTLED` is terminal, so a second settlement is refused as an invalid state.

    PRD 3.6: "`SETTLED` is the auction's terminal state."
    PRD 2.12 (35): "On auction ranking, award and settlement: the requested auction
    transition is declared for the current auction `status` — ranking requires `OPEN`,
    awarding requires `RANKED`, settling requires either `AWARDED` or `NO_FILL` —
    otherwise `ERR_AUCTION_INVALID_STATE`, 409."
    PRD 3.6: "Under `CPC`, only `CLICK` events are billable: `settled_spend_cents` is
    `clearing_price_cents` multiplied by the count of `CLICK` events on the auction."

    Design: Corner/state_machines/settled_auction_cannot_be_settled_again_returns_409
    """
    world = _delivering_world()
    build_settled_auction(world, impressions=1, clicks=1)
    auction = world["auction"]
    assert auction["status"] == "SETTLED"
    # A single candidate, so there is no runner-up and the clearing figure is the floor.
    assert auction["clearing_price_cents"] == SLOT_FLOOR_CPC_CENTS
    assert auction["settled_spend_cents"] == SETTLED_SPEND_CENTS

    line_item_before = reread_line_item(world)
    campaign_before = reread_campaign(world)
    assert campaign_before["delivered_spend_cents"] == SETTLED_SPEND_CENTS

    validate_error(
        api_client.settle_auction_event(auction["id"], None, AUCTION_SERVICE),
        ERR_AUCTION_INVALID_STATE,
        expected_status=409,
    )

    after = validate_success(api_client.get_auction_event(auction["id"], AUCTION_SERVICE))
    assert after["status"] == "SETTLED"
    assert after["settled_spend_cents"] == SETTLED_SPEND_CENTS
    assert after["clearing_price_cents"] == SLOT_FLOOR_CPC_CENTS

    line_item_after = reread_line_item(world)
    assert_version_unchanged(line_item_before, line_item_after)
    campaign_after = reread_campaign(world)
    assert campaign_after["delivered_spend_cents"] == SETTLED_SPEND_CENTS
    assert_no_drift(
        campaign_before["delivered_spend_cents"],
        campaign_after["delivered_spend_cents"],
        "campaign delivered_spend_cents",
    )


def test_resuming_a_line_item_that_was_never_paused_is_refused_as_an_invalid_state():
    """Resume is declared only out of the paused states, never out of `ELIGIBLE`.

    PRD 3.4: "Pausing a `SERVING` line item ... lands the line item in `MANUAL_PAUSED` ...
    Resuming is available to `NetworkAdmin`, `AccountManager`, `CatalogOps` and the owning
    `AdvertiserUser`, and requires the campaign to be `DELIVERING`,
    `eligible_product_count` of at least 1, the plan's `available_cents` to be at least
    `daily_budget_cents`, and the current logical time to be strictly before
    `flight_end_at`; it returns the line item to `SERVING` with `pause_reason` reset to
    `NONE`. The serving-paused-serving cycle may repeat."
    PRD 2.12 (32): "On line item eligibility submission, eligibility decision, activation,
    pause, resume and end: the requested line item transition is one declared for the
    current `line_item_status` — otherwise `ERR_LINE_ITEM_INVALID_STATE`, 409."

    Resume is the inverse of a pause, so `ELIGIBLE` is not a state it is declared from.
    The owning campaign is `DELIVERING` throughout and the plan has ample headroom, so
    the earlier guard of check 31 is satisfied and the refusal can only be about the line
    item's own state.

    Design: Corner/state_machines/resume_on_eligible_line_item_returns_409_invalid_state
    """
    world = _delivering_world()
    build_second_line_item_on_same_slot(
        world, key="second_line_item", activate=False, **_line_item_overrides()
    )
    assert world["second_line_item"]["line_item_status"] == "ELIGIBLE"
    assert reread_campaign(world)["delivery_status"] == "DELIVERING"

    validate_error(
        api_client.resume_line_item(
            world["second_line_item"]["id"], None, ACCOUNT_MANAGER
        ),
        ERR_LINE_ITEM_INVALID_STATE,
        expected_status=409,
    )

    unchanged = reread_line_item(world, "second_line_item")
    assert unchanged["line_item_status"] == "ELIGIBLE"
    assert unchanged["pause_reason"] == "NONE"
    assert_occupancy_count(reread_slot(world), 2)


def test_activating_a_line_item_that_is_already_serving_is_refused():
    """Activation is declared from `ELIGIBLE` only, so a serving line item refuses it.

    PRD 3.4: "Activation moves an `ELIGIBLE` line item to `SERVING`."
    PRD 2.12 (32): "On line item activation, pause, resume and ending: the requested
    transition is declared for the current `line_item_status` — otherwise
    `ERR_LINE_ITEM_INVALID_STATE`, 409."

    A repeated activation must not reserve or occupy anything twice, so the line item's
    reservation and the slot's occupancy are read back afterwards.

    Design: Corner/state_machines/second_activate_on_serving_line_item_returns_409
    """
    world = _delivering_world()
    before = reread_line_item(world)
    assert before["line_item_status"] == "SERVING"
    assert before["reserved_cents"] == LINE_ITEM_RESERVED_CENTS
    assert_occupancy_count(reread_slot(world), 1)

    validate_error(
        api_client.activate_line_item(before["id"], None, ACCOUNT_MANAGER),
        ERR_LINE_ITEM_INVALID_STATE,
        expected_status=409,
    )

    after = reread_line_item(world)
    assert after["line_item_status"] == "SERVING"
    assert after["reserved_cents"] == LINE_ITEM_RESERVED_CENTS
    assert_version_unchanged(before, after)
    assert_occupancy_count(reread_slot(world), 1)


def test_activating_a_line_item_whose_campaign_is_only_scheduled_is_refused():
    """A line item cannot start serving ahead of its own campaign.

    PRD 3.4: "It requires the campaign to be `DELIVERING`, the advertiser to be `ACTIVE`,
    the plan to be `ACTIVE` with `available_cents` at least `daily_budget_cents`, the
    current logical time to be at or after `flight_start_at` and strictly before
    `flight_end_at`, and `eligible_product_count` of at least 1."
    PRD 2.12 (31): "On line item activation and line item resume: the owning campaign's
    `delivery_status` is `DELIVERING` — otherwise `ERR_CAMPAIGN_NOT_DELIVERING`, 409."

    Design: Corner/state_machines/activating_line_item_of_scheduled_campaign_returns_409_not_delivering
    """
    world = _delivering_world()
    build_second_campaign_on_same_plan(
        world,
        key="campaign_b",
        allocated_budget_cents=SECOND_CAMPAIGN_ALLOCATED_CENTS,
    )
    # The second campaign's line item is built separately so it keeps its own key, then
    # the campaign is taken through review to SCHEDULED and left there.
    build_eligible_line_item(
        world,
        key="line_item_b",
        campaign_key="campaign_b",
        **_line_item_overrides(),
    )
    build_scheduled_campaign(world, key="campaign_b", with_line_item=False)
    assert world["campaign_b"]["delivery_status"] == "SCHEDULED"
    assert world["line_item_b"]["line_item_status"] == "ELIGIBLE"

    plan_before = reread_plan(world)
    # Both campaigns reserve: 1000000 + 500000 against a 2000000 commitment, so the
    # plan's headroom is comfortably above the line item's daily budget and the plan
    # guard cannot be the reason this call is refused.
    assert plan_before["plan_status"] == "ACTIVE"
    assert plan_before["reserved_cents"] == (
        CAMPAIGN_ALLOCATED_CENTS + SECOND_CAMPAIGN_ALLOCATED_CENTS
    )
    assert plan_before["available_cents"] >= LINE_ITEM_DAILY_BUDGET_CENTS

    validate_error(
        api_client.activate_line_item(
            world["line_item_b"]["id"], None, ACCOUNT_MANAGER
        ),
        ERR_CAMPAIGN_NOT_DELIVERING,
        expected_status=409,
    )

    assert reread_line_item(world, "line_item_b")["line_item_status"] == "ELIGIBLE"
    assert reread_campaign(world, "campaign_b")["delivery_status"] == "SCHEDULED"
    plan_after = reread_plan(world)
    assert plan_after["reserved_cents"] == (
        CAMPAIGN_ALLOCATED_CENTS + SECOND_CAMPAIGN_ALLOCATED_CENTS
    )
    assert_budget_plan_identity(plan_after)


def test_pausing_a_delivering_campaign_manually_pauses_its_serving_line_item():
    """An operator campaign pause moves the serving line items and holds the reservation.

    PRD 3.3: "Pausing a `DELIVERING` campaign is available to `NetworkAdmin`,
    `AccountManager` and the owning `AdvertiserUser` and carries `pause_reason`, the value
    stamped on every own line item the pause moves to `MANUAL_PAUSED`; an
    operator-initiated campaign pause supplies `MANUAL`. Only line items in `SERVING` are
    moved, and only when the actor is an operator ... The plan's `reserved_cents` is
    unchanged, since `PAUSED` remains a reserving status."
    PRD 3.4 (slot occupancy): "`occupancy_count` itself is derived: the number of line
    items on the slot whose `line_item_status` is `ELIGIBLE`, `SERVING`, `OOS_PAUSED` or
    `MANUAL_PAUSED`."

    Design: Corner/state_machines/campaign_pause_cascades_manual_pause_to_serving_line_item
    """
    world = _delivering_world()

    campaign = validate_success(
        api_client.pause_campaign(
            world["campaign"]["id"], {"pause_reason": "MANUAL"}, ACCOUNT_MANAGER
        )
    )
    # The billing dimension is untouched by a delivery pause.
    assert_campaign_dimensions(campaign, "PAUSED", "ACCRUING")

    line_item = reread_line_item(world)
    assert line_item["line_item_status"] == "MANUAL_PAUSED"
    assert line_item["pause_reason"] == "MANUAL"

    # MANUAL_PAUSED is still an occupying status and PAUSED is still a reserving one, so
    # neither the slot nor the plan moves.
    assert_occupancy_count(reread_slot(world), 1)
    plan = reread_plan(world)
    assert plan["reserved_cents"] == CAMPAIGN_ALLOCATED_CENTS
    assert plan["available_cents"] == PLAN_COMMITTED_CENTS - CAMPAIGN_ALLOCATED_CENTS
    assert_budget_plan_identity(plan)


def test_stock_falling_below_the_serving_threshold_pauses_three_levels_up():
    """One stock adjustment walks assignment, line item and campaign in a single request.

    PRD 3.5: "When the resulting `in_stock_units` falls strictly below
    `min_stock_units_for_serving` and the product was `ELIGIBLE`, the product moves to
    `OUT_OF_STOCK` and the depth-three pausing chain fires. Level one: every assignment
    referencing this product that is `ACTIVE` moves to `PAUSED_OOS`, with its
    `relevance_contribution` zeroed. Level two: each of those assignments triggers a
    recomputation of `eligible_product_count` on its line item, and any line item whose
    recomputed count reaches 0 while it is `SERVING` moves to `OOS_PAUSED` with
    `pause_reason` `OUT_OF_STOCK` and `last_pause_at` stamped. Level three: each line item
    entering `OOS_PAUSED` raises `oos_paused_line_item_count` on its campaign by 1, and a
    campaign whose every non-ended line item is now in `OOS_PAUSED` or `MANUAL_PAUSED` and
    whose `delivery_status` is `DELIVERING` moves to `PAUSED`. The slot's `occupancy_count`
    is unchanged throughout, because `OOS_PAUSED` remains an occupying status."
    PRD 3.5: "The adjustment updates `in_stock_units` and stamps `last_stock_change_at`
    with the current logical time."

    Design: Corner/state_machines/stock_drop_below_min_cascades_three_levels_to_campaign_pause
    """
    world = _delivering_world(product={"in_stock_units": 50})
    assert world["product"]["min_stock_units_for_serving"] == 3
    assignment_id = world["assignment"]["id"]

    # Fifty units less forty-eight leaves two, one short of the three-unit threshold.
    adjust_product_stock(world, -48)
    product = world["product"]
    assert product["in_stock_units"] == 2
    assert product["eligibility_status"] == "OUT_OF_STOCK"
    assert parse_utc(product["last_stock_change_at"]) == parse_utc(DELIVERY_CLOCK)

    assignment = validate_success(
        api_client.get_product_assignment(assignment_id, CATALOG_OPS)
    )
    assert assignment["assignment_status"] == "PAUSED_OOS"
    assert float(assignment["relevance_contribution"]) == 0.0

    line_item = reread_line_item(world)
    assert_line_item_paused(line_item, "OOS_PAUSED", "OUT_OF_STOCK")
    assert line_item["eligible_product_count"] == 0

    campaign = reread_campaign(world)
    assert campaign["oos_paused_line_item_count"] == 1
    assert campaign["delivery_status"] == "PAUSED"

    assert_occupancy_count(reread_slot(world), 1)


def test_restocking_under_a_paused_campaign_returns_the_line_item_to_eligible_only():
    """The reverse adjustment revives the line item but never the campaign above it.

    PRD 3.5: "When the resulting `in_stock_units` returns to
    `min_stock_units_for_serving` or above, the product moves back to `ELIGIBLE`, every
    assignment in `PAUSED_OOS` returns to `ACTIVE` with `relevance_contribution`
    recomputed, and each affected line item recomputes `eligible_product_count`. A line
    item in `OOS_PAUSED` whose recomputed count reaches 1 or more returns to `SERVING`
    with `pause_reason` `NONE` when its campaign is `DELIVERING`, and otherwise — when the
    campaign is `SCHEDULED` or `PAUSED` — returns to `ELIGIBLE` instead, again with
    `pause_reason` cleared. Either way `oos_paused_line_item_count` falls by 1 on the
    campaign. Campaigns paused by the level-three roll-up are not themselves
    auto-resumed."
    PRD 3.6: "The per-assignment `relevance_contribution` is, for each row in that same
    active-and-eligible set, 0.25 multiplied by the product's `margin_pct` divided by the
    count of rows in the set with that count floored at 1, rounded half-up to four decimal
    places."

    Design: Corner/state_machines/restock_returns_line_item_to_eligible_while_campaign_still_paused
    """
    world = _delivering_world(product={"in_stock_units": 50})
    assignment_id = world["assignment"]["id"]
    adjust_product_stock(world, -48)
    assert reread_campaign(world)["delivery_status"] == "PAUSED"

    # Two units plus ten is twelve, comfortably back above the threshold.
    adjust_product_stock(world, 10)
    product = world["product"]
    assert product["in_stock_units"] == 12
    assert product["eligibility_status"] == "ELIGIBLE"

    assignment = validate_success(
        api_client.get_product_assignment(assignment_id, CATALOG_OPS)
    )
    assert assignment["assignment_status"] == "ACTIVE"
    # One row in the active-and-eligible set: 0.25 * 0.3 / 1 = 0.0750.
    assert float(assignment["relevance_contribution"]) == pytest.approx(
        0.0750, abs=1e-9
    )

    line_item = reread_line_item(world)
    # The campaign is PAUSED, not DELIVERING, so the line item stops at ELIGIBLE.
    assert line_item["line_item_status"] == "ELIGIBLE"
    assert line_item["pause_reason"] == "NONE"
    assert line_item["eligible_product_count"] == 1

    campaign = reread_campaign(world)
    assert campaign["oos_paused_line_item_count"] == 0
    assert campaign["delivery_status"] == "PAUSED"

    assert_occupancy_count(reread_slot(world), 1)


def test_resuming_a_campaign_revives_the_manual_pause_but_leaves_the_catalog_pause():
    """A delivery resume clears a manual pause and deliberately ignores a stock pause.

    PRD 3.3: "Resume returns every own line item in `MANUAL_PAUSED` whose `pause_reason`
    is `MANUAL` or `BUDGET_EXHAUSTED` to `SERVING` with `pause_reason` reset to `NONE`,
    recomputes `pacing_index`, and deliberately leaves line items in `OOS_PAUSED` alone —
    a catalog blocker is not cleared by a delivery resume."
    PRD 3.3: "Resuming a `PAUSED` campaign is available to the same three roles and
    requires the advertiser to be `ACTIVE`, the plan to be `ACTIVE` with a strictly
    positive `available_cents`, the current logical time to be strictly before
    `flight_end_at`, and at least one own line item in `ELIGIBLE` or `MANUAL_PAUSED`."

    Two line items share the slot. The second one's own product is driven out of stock, so
    it sits in `OOS_PAUSED`; the campaign is then paused by an operator, which moves only
    the first, still-serving one. The resume must therefore separate the two.

    Design: Corner/state_machines/campaign_resume_revives_manual_paused_but_not_oos_paused_line_items
    """
    world = _delivering_world()
    # A second product with its own stock, so one product can go out of stock without
    # touching the other line item's eligibility.
    build_catalog_product(world, key="product_2", in_stock_units=50)
    build_second_line_item_on_same_slot(
        world,
        key="line_item_2",
        activate=True,
        product_key="product_2",
        **_line_item_overrides(),
    )
    assert world["line_item_2"]["line_item_status"] == "SERVING"

    adjust_product_stock(world, -48, key="product_2")
    assert_line_item_paused(
        reread_line_item(world, "line_item_2"), "OOS_PAUSED", "OUT_OF_STOCK"
    )
    # The first line item is still SERVING, so the level-three roll-up does not fire.
    assert reread_campaign(world)["delivery_status"] == "DELIVERING"

    pause_campaign(world)
    assert world["campaign"]["delivery_status"] == "PAUSED"
    manually_paused = reread_line_item(world)
    assert manually_paused["line_item_status"] == "MANUAL_PAUSED"
    assert manually_paused["pause_reason"] == "MANUAL"

    campaign = validate_success(
        api_client.resume_campaign(world["campaign"]["id"], None, ACCOUNT_MANAGER)
    )
    assert_campaign_dimensions(campaign, "DELIVERING", "ACCRUING")

    revived = reread_line_item(world)
    assert revived["line_item_status"] == "SERVING"
    assert revived["pause_reason"] == "NONE"

    still_blocked = reread_line_item(world, "line_item_2")
    assert still_blocked["line_item_status"] == "OOS_PAUSED"
    assert still_blocked["pause_reason"] == "OUT_OF_STOCK"
    assert reread_product(world, "product_2")["in_stock_units"] == 2
    assert campaign["oos_paused_line_item_count"] == 1

    # Both statuses occupy, so the slot still holds its two rows.
    assert_occupancy_count(reread_slot(world), 2)


def test_delisting_a_product_removes_its_assignments_and_ends_the_line_item():
    """A delist strips every assignment and ends a line item left with no products.

    PRD 3.5: "Delisting is posted by `CatalogOps` or `NetworkAdmin` with a mandatory
    `delist_reason` and is accepted from `RESTRICTED` and from `OUT_OF_STOCK`; from
    `OUT_OF_STOCK` it additionally requires `in_stock_units` to be exactly 0. It moves
    every assignment referencing the product — in any non-terminal status — to `REMOVED`
    with `removed_at` stamped, and recomputes `eligible_product_count` on each affected
    line item; a line item whose recomputed count reaches 0 while it is `SERVING`,
    `ELIGIBLE` or `OOS_PAUSED` moves to `ENDED`, surrendering its slot occupancy."

    Design: Corner/state_machines/delist_removes_assignments_and_ends_line_item
    """
    world = _delivering_world(product={"in_stock_units": 50})
    assignment_id = world["assignment"]["id"]

    # Stock is taken to exactly zero, which both parks the product in OUT_OF_STOCK and
    # satisfies the extra precondition delisting places on that branch.
    adjust_product_stock(world, -50)
    assert world["product"]["in_stock_units"] == 0
    assert world["product"]["eligibility_status"] == "OUT_OF_STOCK"

    product = validate_success(
        api_client.delist_catalog_product(
            world["product"]["id"],
            {"delist_reason": "Vendor discontinued the line"},
            CATALOG_OPS,
        )
    )
    assert product["eligibility_status"] == "DELISTED"
    assert product["in_stock_units"] == 0

    assignment = validate_success(
        api_client.get_product_assignment(assignment_id, CATALOG_OPS)
    )
    assert assignment["assignment_status"] == "REMOVED"
    assert parse_utc(assignment["removed_at"]) == parse_utc(DELIVERY_CLOCK)

    line_item = reread_line_item(world)
    assert line_item["line_item_status"] == "ENDED"
    assert line_item["eligible_product_count"] == 0
    # Ending surrenders the occupancy the eligibility approval had granted.
    assert_occupancy_count(reread_slot(world), 0)


def test_putting_a_slot_into_maintenance_manually_pauses_the_line_items_on_it():
    """A slot amendment reaches down into the line items occupying that slot.

    PRD 3.4: "Moving `slot_status` from `OPEN` to `MAINTENANCE` moves every line item on
    the slot that is `SERVING` to `MANUAL_PAUSED` with `pause_reason` `MANUAL`, and blocks
    any further auction from opening on the slot."
    PRD 3.4: "`occupancy_count` itself is derived: the number of line items on the slot
    whose `line_item_status` is `ELIGIBLE`, `SERVING`, `OOS_PAUSED` or `MANUAL_PAUSED`."

    Design: Corner/state_machines/slot_maintenance_pauses_serving_line_items_on_that_slot
    """
    world = _delivering_world()
    assert world["slot"]["slot_status"] == "OPEN"
    assert reread_line_item(world)["line_item_status"] == "SERVING"

    slot = validate_success(
        api_client.update_placement_slot(
            world["slot"]["id"], {"slot_status": "MAINTENANCE"}, NETWORK_ADMIN
        )
    )
    assert slot["slot_status"] == "MAINTENANCE"

    line_item = reread_line_item(world)
    assert line_item["line_item_status"] == "MANUAL_PAUSED"
    assert line_item["pause_reason"] == "MANUAL"

    # MANUAL_PAUSED is an occupying status, so the maintenance pause moves no occupancy —
    # which is exactly why the slot cannot be retired until its line items are ended.
    assert_occupancy_count(reread_slot(world), 1)
