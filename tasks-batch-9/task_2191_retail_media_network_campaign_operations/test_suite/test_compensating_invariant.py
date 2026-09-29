"""Conserved quantities across a forward action and its compensating action.

Three separate conserved quantities are exercised here: the budget plan's cent identity,
the trade fund pool's cent identity, and a slot's cardinal occupancy count. In each case
a forward action moves the quantity and a compensating action must return it to exactly
where it started, with no drift.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    BILLING_OPS,
    CATALOG_OPS,
    CREDIT_ANALYST,
    NETWORK_ADMIN,
    api_client,
    assert_budget_plan_identity,
    assert_no_drift,
    assert_occupancy_count,
    assert_plan_reservation_matches_campaigns,
    assert_slot_occupancy_matches_line_items,
    assert_trade_fund_identity,
    build_active_advertiser,
    build_active_budget_plan,
    build_catalog_product,
    build_draft_budget_plan,
    build_draft_campaign,
    build_pending_eligibility_line_item,
    build_pending_review_campaign,
    build_placement_slot,
    build_trade_fund_pool,
    reread_line_item,
    reread_plan,
    reread_pool,
    reread_slot,
    set_clock,
    validate_success,
    whole_day_periods,
)


# ---------------------------------------------------------------------------
# The budget plan identity across schedule then archive
# ---------------------------------------------------------------------------


def _plan_world_with_campaign_in_review():
    """An active plan of 5,000,000 cents with a 2,000,000-cent campaign awaiting review.

    The plan carries no trade fund share, so its whole commitment is cash and the pool
    identity plays no part. No auction is ever settled, so `consumed_cents` stays 0
    throughout.
    """
    world = build_active_advertiser()
    build_active_budget_plan(world, committed_total_cents=5000000, trade_fund_share_cents=0)
    build_placement_slot(world)
    build_catalog_product(world)
    build_draft_campaign(world, allocated_budget_cents=2000000)
    build_pending_review_campaign(world)
    return world


def test_plan_headroom_returns_to_its_pre_reservation_value_after_archive():
    """Scheduling reserves the allocation and archiving from SCHEDULED releases it whole.

    PRD 2.9: "The budget identity governs a budget plan: its `committed_total_cents`
    plus its `top_up_total_cents` always equals its `available_cents` plus its
    `reserved_cents` plus its `consumed_cents`."

    PRD 2.9: "When a campaign is approved for delivery its allocation becomes reserved;
    when that campaign is archived straight out of the scheduled state, the allocation
    is released and the plan's headroom returns to exactly the value it held before the
    reservation."

    Design: Difficulty/compensating_invariant/ci_budget_plan_cents_conserved_across_schedule_then_archive
    """
    world = _plan_world_with_campaign_in_review()

    before = reread_plan(world)
    assert before["committed_total_cents"] == 5000000
    assert before["top_up_total_cents"] == 0
    assert before["available_cents"] == 5000000
    assert before["reserved_cents"] == 0
    assert before["consumed_cents"] == 0
    assert_budget_plan_identity(before)

    # Forward action: approval for delivery reserves the campaign's allocation.
    validate_success(
        api_client.decide_campaign_review(
            world["campaign"]["id"],
            {"decision": "APPROVE", "decision_note": "reserve the allocation"},
            NETWORK_ADMIN,
        )
    )
    mid = reread_plan(world)
    assert mid["available_cents"] == 3000000
    assert mid["reserved_cents"] == 2000000
    assert mid["consumed_cents"] == 0
    assert_budget_plan_identity(mid)

    # Compensating action: archiving straight out of SCHEDULED releases it outright.
    validate_success(
        api_client.archive_campaign(
            world["campaign"]["id"],
            {"archive_reason": "release the untouched reservation"},
            NETWORK_ADMIN,
        )
    )
    after = reread_plan(world)
    assert after["available_cents"] == 5000000
    assert after["reserved_cents"] == 0
    assert after["consumed_cents"] == 0
    assert_budget_plan_identity(after)

    assert_no_drift(before["available_cents"], after["available_cents"], "available_cents")
    assert_no_drift(before["reserved_cents"], after["reserved_cents"], "reserved_cents")
    assert_no_drift(before["consumed_cents"], after["consumed_cents"], "consumed_cents")
    assert after["committed_total_cents"] == 5000000
    assert after["top_up_total_cents"] == 0
    assert after["plan_status"] == "ACTIVE"


def test_archive_from_scheduled_ends_the_line_item_and_empties_the_reservation_population():
    """The released reservation is a recomputation over the campaigns, not a stored balance.

    PRD 2.9: "`reserved_cents` is not a stored balance: it is at all times the sum of
    `allocated_budget_cents` over the plan's campaigns whose delivery status is
    scheduled, delivering or paused. Draft, pending-review, completed, rejected and
    archived campaigns reserve nothing."

    PRD 3.3: "From `SCHEDULED` it requires `delivered_spend_cents` to be exactly 0; it
    moves every own line item in `ELIGIBLE`, `PENDING_ELIGIBILITY` or `DRAFT` to
    `ENDED`, each surrendering its slot occupancy, and releases the reservation
    outright — the plan's `reserved_cents` falls by exactly `allocated_budget_cents`
    and its `available_cents` rises by exactly the same amount, restoring the plan's
    headroom to the value it held before the campaign was scheduled."

    Design: Difficulty/compensating_invariant/ci_budget_plan_cents_conserved_across_schedule_then_archive
    """
    world = _plan_world_with_campaign_in_review()

    scheduled = validate_success(
        api_client.decide_campaign_review(
            world["campaign"]["id"],
            {"decision": "APPROVE", "decision_note": "reserve the allocation"},
            NETWORK_ADMIN,
        )
    )
    assert scheduled["delivery_status"] == "SCHEDULED"
    assert scheduled["delivered_spend_cents"] == 0
    world["campaign"] = scheduled
    assert_plan_reservation_matches_campaigns(reread_plan(world), [scheduled])

    archived = validate_success(
        api_client.archive_campaign(
            world["campaign"]["id"], {"archive_reason": "release outright"}, NETWORK_ADMIN
        )
    )
    assert archived["delivery_status"] == "ARCHIVED"
    world["campaign"] = archived

    # The ELIGIBLE line item was carried to ENDED and gave up its slot occupancy.
    line_item = reread_line_item(world)
    assert line_item["line_item_status"] == "ENDED"
    assert_occupancy_count(reread_slot(world), 0)
    assert_slot_occupancy_matches_line_items(world["slot"], [line_item])

    # An archived campaign reserves nothing, so the derived reservation is empty.
    plan = reread_plan(world)
    assert_plan_reservation_matches_campaigns(plan, [archived])
    assert plan["reserved_cents"] == 0
    assert plan["available_cents"] == 5000000
    assert_budget_plan_identity(plan)


# ---------------------------------------------------------------------------
# The trade fund identity across plan approval then plan closure
# ---------------------------------------------------------------------------


def _pool_world_with_draft_plan():
    """A pool accrued 3,000,000 cents and a draft plan claiming 1,250,000 of it.

    The plan's window closes on 2026-08-15, which is the instant closure becomes
    available. No campaign and no invoice reference the plan, so nothing else can hold
    closure up.
    """
    world = build_active_advertiser()
    build_trade_fund_pool(world, accrual_cents=3000000, deduction_cap_pct=0.6)
    build_draft_budget_plan(
        world,
        committed_total_cents=2500000,
        trade_fund_share_cents=1250000,
        window_start_at="2026-07-01T00:00:00Z",
        window_end_at="2026-08-15T00:00:00Z",
    )
    return world


def test_pool_drawable_returns_to_its_pre_reservation_value_after_plan_closure():
    """A plan closure moves the share back to drawable, leaving accrued untouched.

    PRD 2.9: "The trade fund identity governs a fund pool: its `accrued_cents` always
    equals its `available_cents` plus its `reserved_cents` plus its `deducted_cents`."

    PRD 2.9: "A plan submission moves its trade-fund share from drawable to reserved; a
    revision return or a plan closure moves it back."

    PRD 3.4: "Closure releases the residual trade fund reservation — the pool's
    `reserved_cents` recomputed downward and its `available_cents` upward — and
    recomputes the advertiser's exposure."

    Design: Difficulty/compensating_invariant/ci_trade_fund_cents_conserved_across_approve_then_close
    """
    world = _pool_world_with_draft_plan()

    before = reread_pool(world)
    assert before["accrued_cents"] == 3000000
    assert before["available_cents"] == 3000000
    assert before["reserved_cents"] == 0
    assert before["deducted_cents"] == 0
    assert_trade_fund_identity(before)

    # Forward action: the share leaves drawable and is held against the plan.
    validate_success(
        api_client.submit_budget_plan(
            world["plan"]["id"],
            {"submission_note": "submit the trade-fund share"},
            ACCOUNT_MANAGER,
        )
    )
    validate_success(
        api_client.approve_budget_plan(
            world["plan"]["id"],
            {"approval_note": "reserve the trade-fund share"},
            CREDIT_ANALYST,
        )
    )
    mid = reread_pool(world)
    assert mid["accrued_cents"] == 3000000
    assert mid["reserved_cents"] == 1250000
    assert mid["available_cents"] == 1750000
    assert mid["deducted_cents"] == 0
    assert_trade_fund_identity(mid)

    # Compensating action: closure, once the plan's window has run out.
    set_clock(world, "2026-08-15T00:00:00Z")
    closed = validate_success(
        api_client.close_budget_plan(
            world["plan"]["id"],
            {"closure_note": "release the unspent trade-fund reservation"},
            BILLING_OPS,
        )
    )
    assert closed["plan_status"] == "CLOSED"

    after = reread_pool(world)
    assert after["accrued_cents"] == 3000000
    assert after["available_cents"] == 3000000
    assert after["reserved_cents"] == 0
    assert after["deducted_cents"] == 0
    assert_trade_fund_identity(after)

    assert_no_drift(before["available_cents"], after["available_cents"], "available_cents")
    assert_no_drift(before["accrued_cents"], after["accrued_cents"], "accrued_cents")
    assert after["account_status"] == "OPEN"


def test_pool_reservation_tracks_only_approved_and_active_plans_of_the_period():
    """The pool's held amount is derived from the plans holding it, not incremented.

    PRD 3.4: "`reserved_cents` is the sum of `trade_fund_share_cents` over budget plans
    of the same advertiser and period whose `plan_status` is `APPROVED` or `ACTIVE`"

    PRD 2.9: "Accruals raise the accrued total and the drawable amount together."

    Design: Difficulty/compensating_invariant/ci_trade_fund_cents_conserved_across_approve_then_close
    """
    world = _pool_world_with_draft_plan()

    # A DRAFT plan is in neither holding status, so it holds nothing yet.
    assert reread_pool(world)["reserved_cents"] == 0

    validate_success(
        api_client.submit_budget_plan(
            world["plan"]["id"], {"submission_note": "submitted"}, ACCOUNT_MANAGER
        )
    )
    approved = validate_success(
        api_client.approve_budget_plan(
            world["plan"]["id"], {"approval_note": "approved"}, CREDIT_ANALYST
        )
    )
    # The plan window is already open, so approval carries it straight to ACTIVE.
    assert approved["plan_status"] == "ACTIVE"
    assert approved["trade_fund_share_cents"] == 1250000
    assert reread_pool(world)["reserved_cents"] == approved["trade_fund_share_cents"]

    set_clock(world, "2026-08-15T00:00:00Z")
    closed = validate_success(
        api_client.close_budget_plan(
            world["plan"]["id"], {"closure_note": "closed"}, BILLING_OPS
        )
    )
    # CLOSED is neither APPROVED nor ACTIVE, so the plan drops out of the population.
    assert closed["plan_status"] == "CLOSED"
    pool = reread_pool(world)
    assert pool["reserved_cents"] == 0
    assert pool["deducted_cents"] == 0
    assert pool["accrued_cents"] == 3000000
    assert_trade_fund_identity(pool)


# ---------------------------------------------------------------------------
# Slot occupancy across the eligibility grant then the line item's end
# ---------------------------------------------------------------------------


def _single_capacity_slot_world():
    """A slot admitting one line item, with a line item awaiting its eligibility decision.

    The campaign stays in DRAFT, so it reserves nothing against the plan and the plan's
    headroom is unaffected by anything this test does. No auction is run, so the line
    item's `spend_cents` stays 0 and it remains endable from `ELIGIBLE`.
    """
    world = build_active_advertiser()
    build_active_budget_plan(world, committed_total_cents=5000000, trade_fund_share_cents=0)
    build_placement_slot(world, max_concurrent_line_items=1)
    build_catalog_product(world)
    build_draft_campaign(world, allocated_budget_cents=1500000, daily_cap_cents=150000)
    build_pending_eligibility_line_item(
        world,
        bid_cents=200,
        daily_budget_cents=100000,
        flight_start_at="2026-08-06T00:00:00Z",
        flight_end_at="2026-08-16T00:00:00Z",
    )
    return world


def test_slot_occupancy_returns_to_zero_after_the_line_item_ends():
    """The grant raises occupancy by one and the end lowers it by one, back to zero.

    PRD 2.10: "a slot's `occupancy_count` (the number of line items on the slot whose
    status is `ELIGIBLE`, `SERVING`, `OOS_PAUSED` or `MANUAL_PAUSED`)"

    PRD 3.5: "It lands the line item in `ELIGIBLE`, raises the slot's `occupancy_count`
    by 1, and computes `reserved_cents` as `daily_budget_cents` multiplied by the number
    of whole twenty-four-hour periods in the line item's flight, with that day count
    floored at 1 — a flight shorter than a day reserves exactly one day of budget."

    PRD 3.5: "In every case ending lowers the slot's `occupancy_count` by 1 and
    recomputes the plan's `reserved_cents` and `available_cents`, which is the
    compensating release of the occupancy granted at eligibility approval."

    Design: Difficulty/compensating_invariant/ci_slot_occupancy_count_conserved_across_grant_then_end
    """
    world = _single_capacity_slot_world()

    assert_occupancy_count(reread_slot(world), 0)
    occupancy_before = world["slot"]["occupancy_count"]

    # Forward action: the eligibility grant takes occupancy from 0 to 1.
    eligible = validate_success(
        api_client.decide_line_item_eligibility(
            world["line_item"]["id"],
            {"decision": "APPROVE", "decision_note": "grant slot occupancy"},
            CATALOG_OPS,
        )
    )
    assert eligible["line_item_status"] == "ELIGIBLE"
    world["line_item"] = eligible
    assert_occupancy_count(reread_slot(world), 1)

    # Compensating action: ending surrenders the occupancy again.
    ended = validate_success(
        api_client.end_line_item(
            world["line_item"]["id"],
            {"end_reason": "release slot occupancy"},
            ACCOUNT_MANAGER,
        )
    )
    assert ended["line_item_status"] == "ENDED"
    world["line_item"] = ended

    occupancy_after = reread_slot(world)["occupancy_count"]
    assert_occupancy_count(world["slot"], 0)
    assert_no_drift(occupancy_before, occupancy_after, "occupancy_count")
    # ENDED is outside the occupying set, so the derived count equals its population.
    assert_slot_occupancy_matches_line_items(world["slot"], [ended])


def test_eligibility_grant_reserves_one_day_of_budget_per_whole_flight_day():
    """The grant's reservation is the daily budget times the whole days of flight.

    PRD 3.5: "computes `reserved_cents` as `daily_budget_cents` multiplied by the number
    of whole twenty-four-hour periods in the line item's flight, with that day count
    floored at 1"

    PRD 3.5: "from `ELIGIBLE` it requires `spend_cents` to be exactly 0"

    Design: Difficulty/compensating_invariant/ci_slot_occupancy_count_conserved_across_grant_then_end
    """
    world = _single_capacity_slot_world()

    eligible = validate_success(
        api_client.decide_line_item_eligibility(
            world["line_item"]["id"],
            {"decision": "APPROVE", "decision_note": "grant slot occupancy"},
            CATALOG_OPS,
        )
    )
    world["line_item"] = eligible

    flight_days = whole_day_periods("2026-08-06T00:00:00Z", "2026-08-16T00:00:00Z")
    assert flight_days == 10
    assert eligible["reserved_cents"] == 100000 * flight_days
    # Nothing has been auctioned, so the line item may still be ended from ELIGIBLE.
    assert eligible["spend_cents"] == 0

    validate_success(
        api_client.end_line_item(
            world["line_item"]["id"], {"end_reason": "no spend to date"}, ACCOUNT_MANAGER
        )
    )

    # The campaign never left DRAFT, so the plan's headroom never moved.
    plan = reread_plan(world)
    assert plan["available_cents"] == 5000000
    assert plan["reserved_cents"] == 0
    assert_budget_plan_identity(plan)
