"""Single requests that break two documented rules at once.

The refusal order is a single ordered list, so a request that trips two conditions has
exactly one correct answer: the condition standing earlier in the list. Each pair below
is verified twice — once for the reported identifier, and once by removing the winning
condition and watching the loser surface, which proves both conditions really were live.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    BILLING_OPS,
    ERR_FLIGHT_WINDOW_OUTSIDE_CAMPAIGN,
    ERR_OFFSITE_CHANNEL_MISMATCH,
    ERR_TRADE_FUND_FROZEN,
    ERR_TRADE_FUND_INSUFFICIENT,
    api_client,
    assert_refusal_beats,
    assert_trade_fund_identity,
    build_active_advertiser,
    build_draft_budget_plan,
    build_draft_campaign,
    build_frozen_trade_fund_pool,
    build_offsite_placement_slot,
    factories,
    reread_campaign,
    reread_pool,
    validate_error,
    validate_paginated,
    validate_success,
)

# --- A frozen pool against an overdrawn one --------------------------------

POOL_ACCRUAL_CENTS = 100000
REQUESTED_DEDUCTION_CENTS = 500000


def _frozen_underfunded_pool_world():
    """A pool holding 100,000 drawable cents, frozen for an audit.

    A manual deduction of 500,000 cents against it breaks two rules at once: the pool is
    not `OPEN`, and the amount exceeds what is drawable. No budget plan references the
    pool, so its held amount stays 0 and its drawable amount is its whole accrual.
    """
    world = build_active_advertiser()
    build_frozen_trade_fund_pool(
        world,
        accrual_cents=POOL_ACCRUAL_CENTS,
        frozen_reason="AUDIT",
        deduction_cap_pct=0.6,
    )
    return world


def test_the_frozen_pool_state_is_reported_ahead_of_the_shortfall():
    """A frozen pool refuses the deduction on state before it ever weighs the amount.

    PRD 2.12: "When a single request violates several rules, the response is determined
    by exactly one of them: the checks below are evaluated **strictly in the order
    listed**, and the first one that fails supplies both the `error_id` and the HTTP
    status. A later check never masks an earlier one, and an earlier failure means later
    checks are not evaluated at all."

    PRD 2.12: "39. On fund accruals, manual deductions and invoice issuance drawing on a
    pool: the pool's `account_status` is `OPEN`; `FROZEN`, `RECONCILING` and `CLOSED` all
    reject — otherwise `ERR_TRADE_FUND_FROZEN`, 409."

    PRD 2.12: "74. On manual deduction the pool's `available_cents` is at least the
    requested amount, and on plan submission it is at least the plan's
    `trade_fund_share_cents` — otherwise `ERR_TRADE_FUND_INSUFFICIENT`, 402."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_frozen_pool_state_beats_fiscal_insufficiency
    """
    world = _frozen_underfunded_pool_world()

    # Both conditions are true of this one request.
    pool = reread_pool(world)
    assert pool["account_status"] == "FROZEN"
    assert pool["frozen_reason"] == "AUDIT"
    assert pool["available_cents"] == POOL_ACCRUAL_CENTS
    assert REQUESTED_DEDUCTION_CENTS > pool["available_cents"]

    assert_refusal_beats(
        api_client.post_trade_fund_deduction(
            pool["id"],
            factories.deduction_payload(
                REQUESTED_DEDUCTION_CENTS,
                pool["version"],
                deduction_reference="MAN-DED-001",
            ),
            BILLING_OPS,
        ),
        ERR_TRADE_FUND_FROZEN,
        ERR_TRADE_FUND_INSUFFICIENT,
    )

    # Nothing was posted, so the pool's four figures are exactly where they were.
    after = reread_pool(world)
    assert after["account_status"] == "FROZEN"
    assert after["accrued_cents"] == POOL_ACCRUAL_CENTS
    assert after["deducted_cents"] == 0
    assert after["reserved_cents"] == 0
    assert after["available_cents"] == POOL_ACCRUAL_CENTS
    assert_trade_fund_identity(after)


def test_unfreezing_the_pool_surfaces_the_shortfall_that_the_freeze_had_masked():
    """With the state condition gone, the same deduction fails on the money instead.

    PRD 3.2: "Unfreezing is available to the same roles from `FROZEN`, requires
    `available_cents` to be at least 0, accepts an optional `run_reconciliation` flag
    which defaults to false, sets `frozen_reason` back to `NONE`, and lands the pool in
    `OPEN`."

    PRD 2.12: "74. On manual deduction the pool's `available_cents` is at least the
    requested amount, and on plan submission it is at least the plan's
    `trade_fund_share_cents` — otherwise `ERR_TRADE_FUND_INSUFFICIENT`, 402."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_frozen_pool_state_beats_fiscal_insufficiency
    """
    world = _frozen_underfunded_pool_world()

    unfrozen = validate_success(
        api_client.unfreeze_trade_fund_account(
            world["pool"]["id"], {"run_reconciliation": False}, BILLING_OPS
        )
    )
    assert unfrozen["account_status"] == "OPEN"
    assert unfrozen["frozen_reason"] == "NONE"
    world["pool"] = unfrozen

    # The amount is untouched, so only the losing condition of the pair is still true.
    assert REQUESTED_DEDUCTION_CENTS > unfrozen["available_cents"]
    validate_error(
        api_client.post_trade_fund_deduction(
            unfrozen["id"],
            factories.deduction_payload(
                REQUESTED_DEDUCTION_CENTS,
                unfrozen["version"],
                deduction_reference="MAN-DED-002",
            ),
            BILLING_OPS,
        ),
        ERR_TRADE_FUND_INSUFFICIENT,
    )

    after = reread_pool(world)
    assert after["account_status"] == "OPEN"
    assert after["deducted_cents"] == 0
    assert after["available_cents"] == POOL_ACCRUAL_CENTS
    assert_trade_fund_identity(after)


# ---------------------------------------------------------------------------
# A flight window outside the campaign against an off-site channel mismatch
# ---------------------------------------------------------------------------

CAMPAIGN_FLIGHT = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")
OUTSIDE_FLIGHT = ("2026-09-05T00:00:00Z", "2026-09-10T00:00:00Z")
INSIDE_FLIGHT = ("2026-08-05T00:00:00Z", "2026-08-10T00:00:00Z")


def _onsite_only_campaign_with_offsite_slot():
    """An on-site-only campaign and an off-site slot to hang a line item on.

    The slot carries no adjacency buffer and the campaign holds no line item yet, so
    neither the buffer rule nor any capacity rule has anything to say. The two conditions
    the created line item will break are the only two live conditions in the world.
    """
    world = build_active_advertiser()
    build_draft_budget_plan(
        world,
        committed_total_cents=1000000,
        trade_fund_share_cents=0,
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-11-01T00:00:00Z",
    )
    build_offsite_placement_slot(
        world,
        page_type="OFFSITE_SOCIAL",
        max_concurrent_line_items=2,
        floor_cpc_cents=1000,
        buffer_minutes=0,
    )
    build_draft_campaign(
        world,
        channel_mix="ONSITE_ONLY",
        flight_start_at=CAMPAIGN_FLIGHT[0],
        flight_end_at=CAMPAIGN_FLIGHT[1],
        allocated_budget_cents=500000,
        daily_cap_cents=400000,
    )
    return world


def _create_line_item(world, flight):
    """Ask for a CPM line item on the off-site slot over the given flight."""
    campaign = reread_campaign(world)
    return api_client.create_line_item(
        factories.line_item_payload(
            campaign["id"],
            world["slot"]["id"],
            campaign["version"],
            bid_cents=5000,
            bid_type="CPM",
            flight_start_at=flight[0],
            flight_end_at=flight[1],
            keyword_match_terms=["coffee"],
        ),
        ACCOUNT_MANAGER,
    )


def test_the_flight_window_breach_is_reported_ahead_of_the_channel_mismatch():
    """A flight wholly after the campaign's own is refused before the channel is judged.

    PRD 2.12: "46. On line item creation: the line item's flight lies entirely inside the
    owning campaign's flight under half-open semantics, with its own start strictly
    before its own end — otherwise `ERR_FLIGHT_WINDOW_OUTSIDE_CAMPAIGN`, 422."

    PRD 2.12: "64. On line item creation and campaign review submission: a campaign whose
    `channel_mix` is `ONSITE_ONLY` has no line item on an off-site slot, a campaign whose
    `channel_mix` is `OFFSITE_ONLY` has no line item on an on-site slot, and an `OMNI`
    campaign has at least one line item on each channel before review submission —
    otherwise `ERR_OFFSITE_CHANNEL_MISMATCH`, 422."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_flight_window_temporal_beats_channel_mix_constraint
    """
    world = _onsite_only_campaign_with_offsite_slot()

    # Both conditions are true: the flight starts after the campaign's flight ends, and
    # an on-site-only campaign may hold nothing on this off-site slot.
    assert OUTSIDE_FLIGHT[0] > CAMPAIGN_FLIGHT[1]
    assert world["campaign"]["channel_mix"] == "ONSITE_ONLY"
    assert world["slot"]["channel"] == "OFFSITE"

    assert_refusal_beats(
        _create_line_item(world, OUTSIDE_FLIGHT),
        ERR_FLIGHT_WINDOW_OUTSIDE_CAMPAIGN,
        ERR_OFFSITE_CHANNEL_MISMATCH,
    )

    # The refused creation left the campaign without a line item.
    items, _ = validate_paginated(
        api_client.list_line_items(
            ACCOUNT_MANAGER, campaign_id=world["campaign"]["id"]
        )
    )
    assert items == []


def test_moving_the_flight_inside_the_campaign_surfaces_the_channel_mismatch():
    """With the window condition satisfied, the same off-site slot fails on the channel.

    PRD 2.12: "64. On line item creation and campaign review submission: a campaign whose
    `channel_mix` is `ONSITE_ONLY` has no line item on an off-site slot, a campaign whose
    `channel_mix` is `OFFSITE_ONLY` has no line item on an on-site slot, and an `OMNI`
    campaign has at least one line item on each channel before review submission —
    otherwise `ERR_OFFSITE_CHANNEL_MISMATCH`, 422."

    PRD 2.8: "Every time range in this specification is **half-open**: the start instant
    is inclusive and the end instant is exclusive."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_flight_window_temporal_beats_channel_mix_constraint
    """
    world = _onsite_only_campaign_with_offsite_slot()

    # The flight now sits wholly inside the campaign's own flight.
    assert INSIDE_FLIGHT[0] >= CAMPAIGN_FLIGHT[0]
    assert INSIDE_FLIGHT[1] <= CAMPAIGN_FLIGHT[1]

    validate_error(
        _create_line_item(world, INSIDE_FLIGHT), ERR_OFFSITE_CHANNEL_MISMATCH
    )
