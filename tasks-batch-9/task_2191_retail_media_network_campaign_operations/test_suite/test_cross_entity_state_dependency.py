"""Transitions refused by the state of a neighbouring entity, not by their own subject.

In both cases every field and every own precondition of the target resource is valid. What
refuses the request lives on another row: a sibling plan holding the co-op money, and a
parent campaign that the line item's own pause rolled out of delivery.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    BILLING_OPS,
    ERR_CAMPAIGN_NOT_DELIVERING,
    ERR_TRADE_FUND_INSUFFICIENT,
    api_client,
    assert_budget_plan_identity,
    assert_campaign_dimensions,
    assert_line_item_paused,
    assert_occupancy_count,
    assert_trade_fund_identity,
    build_active_advertiser,
    build_active_budget_plan,
    build_delivering_world,
    build_draft_budget_plan,
    build_trade_fund_pool,
    reread_campaign,
    reread_line_item,
    reread_plan,
    reread_pool,
    reread_slot,
    validate_error,
    validate_success,
)

# --- The sibling-plan trade fund reservation -------------------------------

POOL_ACCRUAL_CENTS = 3000000
PLAN_A_TRADE_FUND_SHARE_CENTS = 2500000
PLAN_B_TRADE_FUND_SHARE_CENTS = 600000
PLAN_WINDOW = ("2026-07-01T00:00:00Z", "2026-10-01T00:00:00Z")


def _two_plan_world():
    """A pool of 3,000,000 cents with an active plan holding 2,500,000 of it.

    A second plan, still in DRAFT, asks for 600,000 of a pool that has only 500,000
    drawable. Every field of the second plan is individually valid: its committed total
    clears the submission floor and its share is smaller than the pool's whole accrual.
    """
    world = build_active_advertiser()
    build_trade_fund_pool(world, accrual_cents=POOL_ACCRUAL_CENTS, deduction_cap_pct=0.6)
    build_active_budget_plan(
        world,
        key="plan_a",
        committed_total_cents=5000000,
        trade_fund_share_cents=PLAN_A_TRADE_FUND_SHARE_CENTS,
        window_start_at=PLAN_WINDOW[0],
        window_end_at=PLAN_WINDOW[1],
    )
    build_draft_budget_plan(
        world,
        key="plan_b",
        committed_total_cents=1200000,
        trade_fund_share_cents=PLAN_B_TRADE_FUND_SHARE_CENTS,
        window_start_at=PLAN_WINDOW[0],
        window_end_at=PLAN_WINDOW[1],
    )
    return world


def test_plan_submission_is_refused_by_the_drawable_amount_a_sibling_plan_left():
    """A sibling plan's hold on the pool is what refuses this plan's submission.

    PRD 3.4: "It requires `committed_total_cents` of at least 100,000 cents, and — when
    `trade_fund_share_cents` is greater than 0 — an `OPEN` trade fund pool existing for
    the same advertiser and the same `fiscal_period_code` with `available_cents` of at
    least `trade_fund_share_cents`."

    PRD 3.4: "`reserved_cents` is the sum of `trade_fund_share_cents` over budget plans of
    the same advertiser and period whose `plan_status` is `APPROVED` or `ACTIVE`"

    PRD 2.12: "74. On manual deduction the pool's `available_cents` is at least the
    requested amount, and on plan submission it is at least the plan's
    `trade_fund_share_cents` — otherwise `ERR_TRADE_FUND_INSUFFICIENT`, 402."

    Design: Difficulty/cross_entity_state_dependency/cesd_plan_submit_blocked_by_sibling_plan_trade_fund_reservation
    """
    world = _two_plan_world()

    # The pool's drawable amount is what plan A's activation left behind.
    pool_before = reread_pool(world)
    assert pool_before["accrued_cents"] == POOL_ACCRUAL_CENTS
    assert pool_before["reserved_cents"] == PLAN_A_TRADE_FUND_SHARE_CENTS
    assert pool_before["available_cents"] == 500000
    assert_trade_fund_identity(pool_before)
    assert reread_plan(world, "plan_a")["plan_status"] == "ACTIVE"

    # The share plan B asks for exceeds what is drawable, and nothing else about it does.
    assert PLAN_B_TRADE_FUND_SHARE_CENTS > pool_before["available_cents"]
    assert world["plan_b"]["committed_total_cents"] >= 100000
    assert PLAN_B_TRADE_FUND_SHARE_CENTS < POOL_ACCRUAL_CENTS

    validate_error(
        api_client.submit_budget_plan(
            world["plan_b"]["id"],
            {"submission_note": "Q3 incremental commitment"},
            ACCOUNT_MANAGER,
        ),
        ERR_TRADE_FUND_INSUFFICIENT,
    )

    plan_b = reread_plan(world, "plan_b")
    assert plan_b["plan_status"] == "DRAFT"
    assert plan_b["trade_fund_share_cents"] == PLAN_B_TRADE_FUND_SHARE_CENTS
    assert plan_b["submitted_by_user_id"] is None


def test_the_pool_is_unmoved_by_the_refused_submission():
    """The refused submission holds nothing, so the pool's four figures stand still.

    PRD 2.9: "The trade fund identity governs a fund pool: its `accrued_cents` always
    equals its `available_cents` plus its `reserved_cents` plus its `deducted_cents`."

    PRD 2.9: "A plan submission moves its trade-fund share from drawable to reserved; a
    revision return or a plan closure moves it back."

    Design: Difficulty/cross_entity_state_dependency/cesd_plan_submit_blocked_by_sibling_plan_trade_fund_reservation
    """
    world = _two_plan_world()
    before = reread_pool(world)

    validate_error(
        api_client.submit_budget_plan(
            world["plan_b"]["id"], {"submission_note": "refused"}, ACCOUNT_MANAGER
        ),
        ERR_TRADE_FUND_INSUFFICIENT,
    )

    after = reread_pool(world)
    assert after["accrued_cents"] == before["accrued_cents"] == POOL_ACCRUAL_CENTS
    assert after["reserved_cents"] == PLAN_A_TRADE_FUND_SHARE_CENTS
    assert after["deducted_cents"] == 0
    assert after["available_cents"] == 500000
    assert after["account_status"] == "OPEN"
    assert_trade_fund_identity(after)

    # Raising the drawable amount by the shortfall is enough to let the same plan through,
    # which pins the refusal on the pool rather than on plan B.
    validate_success(
        api_client.post_trade_fund_accrual(
            world["pool"]["id"],
            {"accrual_amount_cents": 100000, "accrual_reference": "ACCR-TOP-UP"},
            BILLING_OPS,
        )
    )
    submitted = validate_success(
        api_client.submit_budget_plan(
            world["plan_b"]["id"], {"submission_note": "now funded"}, ACCOUNT_MANAGER
        )
    )
    assert submitted["plan_status"] == "PENDING_APPROVAL"


# ---------------------------------------------------------------------------
# The paused parent campaign
# ---------------------------------------------------------------------------


def _single_line_item_delivering_world():
    """A delivering campaign whose only line item is serving, mid-flight.

    Because the campaign has exactly one line item, pausing it leaves the campaign with
    nothing still serving, which is the condition that rolls the campaign up to PAUSED.
    """
    return build_delivering_world(
        plan={"committed_total_cents": 5000000, "trade_fund_share_cents": 0},
        campaign={"allocated_budget_cents": 2000000},
        activate_at="2026-08-06T00:00:00Z",
        accrual_cents=0,
    )


def test_line_item_resume_is_refused_because_its_own_pause_paused_the_campaign():
    """Pausing the last serving line item paused the campaign, which then blocks the resume.

    PRD 3.5: "When the pause leaves the campaign with no line item still `SERVING`, the
    campaign rolls up from `DELIVERING` to `PAUSED`."

    PRD 3.5: "Resuming is available to `NetworkAdmin`, `AccountManager`, `CatalogOps` and
    the owning `AdvertiserUser`, and requires the campaign to be `DELIVERING`,
    `eligible_product_count` of at least 1, the plan's `available_cents` to be at least
    `daily_budget_cents`, and the current logical time to be strictly before
    `flight_end_at`; it returns the line item to `SERVING` with `pause_reason` reset to
    `NONE`."

    PRD 2.12: "31. On line item activation and line item resume: the owning campaign's
    `delivery_status` is `DELIVERING` — otherwise `ERR_CAMPAIGN_NOT_DELIVERING`, 409."

    Design: Difficulty/cross_entity_state_dependency/cesd_line_item_resume_blocked_by_paused_parent_campaign
    """
    world = _single_line_item_delivering_world()
    assert world["line_item"]["line_item_status"] == "SERVING"
    assert_campaign_dimensions(reread_campaign(world), "DELIVERING", "ACCRUING")

    paused = validate_success(
        api_client.pause_line_item(
            world["line_item"]["id"], {"pause_reason": "MANUAL"}, ACCOUNT_MANAGER
        )
    )
    assert_line_item_paused(paused, "MANUAL_PAUSED", "MANUAL")
    world["line_item"] = paused

    # The line item's own pause rolled its parent out of delivery.
    assert_campaign_dimensions(reread_campaign(world), "PAUSED", "ACCRUING")

    validate_error(
        api_client.resume_line_item(world["line_item"]["id"], None, ACCOUNT_MANAGER),
        ERR_CAMPAIGN_NOT_DELIVERING,
    )

    # MANUAL_PAUSED is a declared origin of the resume and the line item's own
    # preconditions all hold, so only the parent's state can be refusing it.
    line_item = reread_line_item(world)
    assert line_item["line_item_status"] == "MANUAL_PAUSED"
    assert line_item["pause_reason"] == "MANUAL"
    assert line_item["eligible_product_count"] == 1
    plan = reread_plan(world)
    assert plan["plan_status"] == "ACTIVE"
    assert plan["available_cents"] >= line_item["daily_budget_cents"]


def test_the_line_item_pause_leaves_slot_occupancy_and_plan_reservation_alone():
    """A paused line item still occupies its slot and its campaign still reserves.

    PRD 3.5: "Pausing changes neither the slot's `occupancy_count` nor the plan's
    `reserved_cents`."

    PRD 2.10: "pausing a line item does not change its slot's `occupancy_count`, and does
    not change its plan's `reserved_cents`, because a paused line item still occupies its
    slot and its campaign is still in a reserving delivery status."

    Design: Difficulty/cross_entity_state_dependency/cesd_line_item_resume_blocked_by_paused_parent_campaign
    """
    world = _single_line_item_delivering_world()

    occupancy_before = reread_slot(world)["occupancy_count"]
    plan_before = reread_plan(world)
    assert occupancy_before == 1
    assert plan_before["reserved_cents"] == 2000000
    assert plan_before["available_cents"] == 3000000

    validate_success(
        api_client.pause_line_item(
            world["line_item"]["id"], {"pause_reason": "MANUAL"}, ACCOUNT_MANAGER
        )
    )
    validate_error(
        api_client.resume_line_item(world["line_item"]["id"], None, ACCOUNT_MANAGER),
        ERR_CAMPAIGN_NOT_DELIVERING,
    )

    # PAUSED is still a reserving delivery status and MANUAL_PAUSED still occupies.
    assert_occupancy_count(reread_slot(world), occupancy_before)
    plan_after = reread_plan(world)
    assert plan_after["reserved_cents"] == plan_before["reserved_cents"]
    assert plan_after["available_cents"] == 3000000
    assert_budget_plan_identity(plan_after)
