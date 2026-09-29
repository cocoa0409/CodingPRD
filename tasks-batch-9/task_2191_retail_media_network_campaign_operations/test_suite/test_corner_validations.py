"""Refusals at the boundaries where two rules, or two advertisers, disagree.

Each test here pairs a rejection with the reason the neighbouring rule did *not* fire. The
stale-version refusal is checked against a request that is also channel-illegal, so the
precedence list is what decides the code. The self-serve daily-cap refusal is checked
against a managed advertiser sent the identical payload, so the only difference is the
absence of a self-serve cap. The credit-limit refusal is checked on two plans that are each
individually affordable. The buffer conflict is checked on the same adjacent windows that
pass the aggregate-capacity rule on an on-site slot.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    AUCTION_SERVICE,
    BILLING_OPS,
    CATALOG_OPS,
    CREDIT_ANALYST,
    ERR_CAP_EXCEEDS_PARENT_LIMIT,
    ERR_CLAIM_EXCEEDS_INVOICE,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_ENGAGEMENT_OUTSIDE_FLIGHT,
    ERR_NOTHING_TO_INVOICE,
    ERR_SLOT_BUFFER_CONFLICT,
    ERR_STALE_CAMPAIGN_VERSION,
    api_client,
    build_active_advertiser,
    build_active_budget_plan,
    build_active_managed_advertiser,
    build_awarded_auction,
    build_campaign_ready_world,
    build_catalog_product,
    build_completed_campaign,
    build_delivering_campaign,
    build_delivering_world,
    build_draft_budget_plan,
    build_draft_invoice,
    build_eligible_line_item,
    build_engagement_event,
    build_issued_invoice,
    build_line_item,
    build_offsite_placement_slot,
    build_pending_eligibility_line_item,
    build_trade_fund_pool,
    factories,
    reread_advertiser,
    reread_campaign,
    reread_invoice,
    reread_line_item,
    reread_plan,
    reread_slot,
    validate_error,
    validate_success,
)

FLIGHT_START = "2026-08-01T00:00:00Z"
FLIGHT_END = "2026-08-11T00:00:00Z"

EARLY_START = "2026-08-02T00:00:00Z"
BOUNDARY = "2026-08-04T00:00:00Z"
LATE_END = "2026-08-06T00:00:00Z"

Q3_WINDOW = ("2026-08-01T00:00:00Z", "2026-10-01T00:00:00Z")
Q4_WINDOW = ("2026-10-01T00:00:00Z", "2026-12-01T00:00:00Z")

OFFSITE_SLOT = "offsite_slot"
FIRST = "first_line_item"
SECOND = "second_line_item"
SECOND_PRODUCT = "second_product"
PREMIUM = "premium_line_item"
THIN = "thin_margin_line_item"

QUERY = "red shoes sale"
SEGMENT = "RETURNING"
SHOPPER = "sh_validation_1"

# The payload both the self-serve and the managed advertiser are sent, unchanged: the cap
# fits inside the allocation and only the self-serve spend cap can refuse it.
OVERSIZED_CAP_CENTS = 6000000
OVERSIZED_ALLOCATION_CENTS = 10000000


def _campaign_creation_payload(world, name):
    """A campaign whose daily cap is below its allocation but above any self-serve cap."""
    return factories.campaign_payload(
        world["advertiser"]["id"],
        world["plan"]["id"],
        name=name,
        channel_mix="ONSITE_ONLY",
        flight_start_at=FLIGHT_START,
        flight_end_at=FLIGHT_END,
        allocated_budget_cents=OVERSIZED_ALLOCATION_CENTS,
        pacing_mode="EVEN",
        daily_cap_cents=OVERSIZED_CAP_CENTS,
        attribution_model="LAST_TOUCH",
        attribution_window_days=14,
    )


def test_stale_campaign_version_is_reported_before_the_channel_mismatch():
    """An off-site line item on an on-site campaign, sent stale, answers 412 not 422.

    PRD 2.12: "21. On line item creation and on study creation: `expected_campaign_version`
    equals the campaign's current `version` — otherwise `ERR_STALE_CAMPAIGN_VERSION`, 412."

    PRD 2.12: "64. On line item creation and campaign review submission: a campaign whose
    `channel_mix` is `ONSITE_ONLY` has no line item on an off-site slot, a campaign whose
    `channel_mix` is `OFFSITE_ONLY` has no line item on an on-site slot, and an `OMNI`
    campaign has at least one line item on each channel before review submission —
    otherwise `ERR_OFFSITE_CHANNEL_MISMATCH`, 422."

    PRD 2.12: "A stale parent version is detected *after* existence but *before* any state
    or business check, so a client that both holds a stale version and requests an
    undeclared transition sees the stale-version code, not the transition code."

    Design: Corner/validations/stale_campaign_version_outranks_offsite_channel_mismatch_and_returns_412
    """
    world = build_campaign_ready_world(
        plan={"committed_total_cents": 2000000, "trade_fund_share_cents": 0},
        product={"category_code": "FOOTWEAR", "title": "red shoes", "margin_pct": 0.4},
        campaign={
            "channel_mix": "ONSITE_ONLY",
            "flight_start_at": FLIGHT_START,
            "flight_end_at": FLIGHT_END,
            "allocated_budget_cents": 1000000,
            "daily_cap_cents": 200000,
        },
    )
    build_offsite_placement_slot(world, key=OFFSITE_SLOT)
    # One on-site line item, purely to move the campaign's version on so the stale value
    # carried below is a version the campaign genuinely used to hold.
    build_line_item(
        world,
        key=FIRST,
        flight_start_at=FLIGHT_START,
        flight_end_at=FLIGHT_END,
        category_code="FOOTWEAR",
        keyword_match_terms=["red", "shoes"],
    )
    campaign = reread_campaign(world)
    assert campaign["version"] >= 2

    response = api_client.create_line_item(
        factories.line_item_payload(
            campaign["id"],
            world[OFFSITE_SLOT]["id"],
            campaign["version"] - 1,
            bid_cents=200,
            bid_type="CPC",
            flight_start_at=FLIGHT_START,
            flight_end_at=FLIGHT_END,
            daily_budget_cents=100000,
            category_code="FOOTWEAR",
            keyword_match_terms=["red", "shoes"],
        ),
        ACCOUNT_MANAGER,
    )

    validate_error(response, ERR_STALE_CAMPAIGN_VERSION, 412)
    assert reread_campaign(world)["delivery_status"] == "DRAFT"


def test_daily_cap_above_the_self_serve_spend_cap_is_refused():
    """A 6,000,000-cent cap inside a 10,000,000-cent allocation still breaches the cap.

    PRD 2.12: "71. On budget plan creation and campaign creation: `trade_fund_share_cents`
    does not exceed `committed_total_cents`, `daily_cap_cents` does not exceed
    `allocated_budget_cents`, and for a `SELF_SERVE` advertiser `daily_cap_cents` does not
    exceed `self_serve_daily_spend_cap_cents` — otherwise `ERR_CAP_EXCEEDS_PARENT_LIMIT`,
    422."

    PRD 3.3: "The campaign's flight must lie entirely inside the funding plan's window,
    `daily_cap_cents` may not exceed `allocated_budget_cents`, and for a `SELF_SERVE`
    advertiser `daily_cap_cents` may additionally not exceed the advertiser's
    `self_serve_daily_spend_cap_cents`."

    Design: Corner/validations/daily_cap_above_the_self_serve_spend_cap_is_rejected_despite_fitting_the_allocation
    """
    world = build_active_advertiser(self_serve_daily_spend_cap_cents=5000000)
    build_trade_fund_pool(world)
    build_active_budget_plan(
        world, committed_total_cents=2000000, trade_fund_share_cents=0
    )

    response = api_client.create_campaign(
        _campaign_creation_payload(world, "Cap Overreach"), ACCOUNT_MANAGER
    )

    validate_error(response, ERR_CAP_EXCEEDS_PARENT_LIMIT, 422)
    # No campaign was created, so nothing was reserved against the plan.
    assert reread_plan(world)["available_cents"] == 2000000


def test_the_same_daily_cap_is_accepted_for_a_managed_advertiser():
    """The identical payload succeeds when no self-serve spend cap exists to breach.

    PRD 3.3: "The campaign's flight must lie entirely inside the funding plan's window,
    `daily_cap_cents` may not exceed `allocated_budget_cents`, and for a `SELF_SERVE`
    advertiser `daily_cap_cents` may additionally not exceed the advertiser's
    `self_serve_daily_spend_cap_cents`."

    PRD 3.3: "The campaign is born with `delivery_status` `DRAFT` and `billing_status`
    `UNBILLED`, and every computed figure at zero or null."

    Design: Corner/validations/the_same_daily_cap_is_accepted_for_a_managed_advertiser_with_no_self_serve_cap
    """
    world = build_active_managed_advertiser(managed_service_fee_pct=0.15)
    build_trade_fund_pool(world)
    build_active_budget_plan(
        world, committed_total_cents=2000000, trade_fund_share_cents=0
    )

    created = validate_success(
        api_client.create_campaign(
            _campaign_creation_payload(world, "Managed Burst"), ACCOUNT_MANAGER
        ),
        expected_status=201,
    )

    assert created["delivery_status"] == "DRAFT"
    assert created["billing_status"] == "UNBILLED"
    assert created["daily_cap_cents"] == 6000000
    assert created["delivered_spend_cents"] == 0
    # A draft campaign holds no reservation, so the plan's headroom is untouched.
    assert reread_plan(world)["available_cents"] == 2000000


def test_two_individually_affordable_plans_breach_the_limit_together():
    """A second 2,000,000-cent plan against a 3,000,000-cent limit is refused with 402.

    PRD 2.12: "73. On plan approval: the advertiser's `credit_exposure_cents` plus the
    plan's `cash_share_cents` does not exceed the effective credit limit, which is the
    parent advertiser's `credit_limit_cents` when `parent_advertiser_id` is non-null and the
    advertiser's own `credit_limit_cents` otherwise — otherwise
    `ERR_CREDIT_LIMIT_EXCEEDED`, 402."

    PRD 3.1: "It is the sum of `committed_total_cents` over the advertiser's own budget
    plans whose `plan_status` is `APPROVED`, `ACTIVE` or `EXHAUSTED`, plus the sum of
    `net_cash_due_cents` over the advertiser's own invoices whose `invoice_status` is
    `ISSUED`, `DISPUTED` or `ADJUSTED`."

    Design: Corner/validations/two_individually_affordable_plans_breach_the_credit_limit_only_in_aggregate
    """
    world = build_active_advertiser(credit_limit_cents=3000000)
    build_active_budget_plan(
        world,
        committed_total_cents=2000000,
        trade_fund_share_cents=0,
        window_start_at=Q3_WINDOW[0],
        window_end_at=Q3_WINDOW[1],
    )
    # The clock already sits at the Q3 window's opening instant, so approval promoted the
    # first plan straight through to ACTIVE and it is holding the whole exposure.
    assert world["plan"]["plan_status"] == "ACTIVE"
    build_draft_budget_plan(
        world,
        key="fourth_quarter_plan",
        fiscal_period_code="2026-Q4",
        committed_total_cents=2000000,
        trade_fund_share_cents=0,
        window_start_at=Q4_WINDOW[0],
        window_end_at=Q4_WINDOW[1],
    )
    validate_success(
        api_client.submit_budget_plan(
            world["fourth_quarter_plan"]["id"],
            {"submission_note": "fourth quarter commitment"},
            ACCOUNT_MANAGER,
        )
    )

    response = api_client.approve_budget_plan(
        world["fourth_quarter_plan"]["id"],
        {"approval_note": "second commitment"},
        CREDIT_ANALYST,
    )

    validate_error(response, ERR_CREDIT_LIMIT_EXCEEDED, 402)
    # 2,000,000 of exposure plus a 2,000,000 cash share exceeds the 3,000,000 limit, even
    # though the two windows are adjacent and neither plan alone would breach it.
    refused = validate_success(
        api_client.get_budget_plan(
            world["fourth_quarter_plan"]["id"], ACCOUNT_MANAGER
        )
    )
    assert refused["plan_status"] == "PENDING_APPROVAL"
    assert reread_plan(world)["plan_status"] == "ACTIVE"
    assert reread_advertiser(world)["credit_exposure_cents"] == 2000000


def test_engagement_at_the_exclusive_flight_end_instant_is_refused():
    """A click at exactly `flight_end_at` falls outside the half-open flight.

    PRD 2.12: "49. On engagement ingestion: the engagement's `occurred_at` lies inside the
    winning line item's flight and is at or after the auction's `requested_at` — otherwise
    `ERR_ENGAGEMENT_OUTSIDE_FLIGHT`, 422."

    PRD 3.6: "The supplied `occurred_at` must lie inside the winning line item's flight
    under the half-open rule — at or after its `flight_start_at` and strictly before its
    `flight_end_at` — and must be at or after the auction's `requested_at`, since a shopper
    cannot engage with a placement before the request that produced it."

    PRD 2.8: "Every time range in this specification is **half-open**: the start instant is
    inclusive and the end instant is exclusive."

    Design: Corner/validations/engagement_event_at_the_exclusive_flight_end_boundary_is_rejected
    """
    world = build_delivering_world(
        campaign={
            "flight_start_at": FLIGHT_START,
            "flight_end_at": FLIGHT_END,
            "allocated_budget_cents": 1000000,
            "daily_cap_cents": 200000,
        },
        line_item={
            "flight_start_at": FLIGHT_START,
            "flight_end_at": FLIGHT_END,
        },
    )
    build_awarded_auction(world)

    response = api_client.create_engagement_event(
        factories.engagement_event_payload(
            world["line_item"]["id"],
            world["auction"]["id"],
            world["product"]["id"],
            event_type="CLICK",
            occurred_at=FLIGHT_END,
            shopper_hash="sh_9",
            channel="ONSITE",
        ),
        AUCTION_SERVICE,
    )

    validate_error(response, ERR_ENGAGEMENT_OUTSIDE_FLIGHT, 422)
    auction = validate_success(
        api_client.get_auction_event(world["auction"]["id"], AUCTION_SERVICE)
    )
    assert auction["status"] == "AWARDED"
    assert auction["settled_spend_cents"] == 0
    assert reread_line_item(world)["line_item_status"] == "SERVING"


def test_offsite_buffer_makes_adjacent_windows_collide():
    """The sixty-minute buffer inflates 08-04 backwards into the neighbour's flight.

    PRD 2.12: "55. On the line item eligibility decision: the adjacency-buffer rule holds —
    on an off-site slot with a non-zero `buffer_minutes`, no occupying line item overlaps
    the candidate flight inflated by that buffer on both sides — otherwise
    `ERR_SLOT_BUFFER_CONFLICT`, 409."

    PRD 3.4: "Rule C is the adjacency buffer and applies only when the slot's `channel` is
    `OFFSITE` and `buffer_minutes` is greater than 0: the candidate's flight is widened by
    that many whole minutes at the start **and** at the end, and no occupying row may
    overlap the widened interval."

    PRD 3.4: "Because of the widening, flights that merely touch — one ending exactly where
    another begins — do collide under Rule C even though they pass Rule A."

    Design: Corner/validations/offsite_buffer_inflation_makes_adjacent_windows_conflict_and_returns_409
    """
    world = build_campaign_ready_world(
        offsite=True,
        plan={"committed_total_cents": 2000000, "trade_fund_share_cents": 0},
        slot={"buffer_minutes": 60, "max_concurrent_line_items": 2},
        product={"category_code": "FOOTWEAR", "title": "red shoes", "margin_pct": 0.4},
        campaign={
            "channel_mix": "OFFSITE_ONLY",
            "flight_start_at": FLIGHT_START,
            "flight_end_at": FLIGHT_END,
            "allocated_budget_cents": 1000000,
            "daily_cap_cents": 200000,
        },
    )
    build_catalog_product(
        world,
        key=SECOND_PRODUCT,
        category_code="FOOTWEAR",
        title="red sandals",
        margin_pct=0.2,
    )
    build_eligible_line_item(
        world,
        key=FIRST,
        bid_cents=200,
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
        flight_start_at=BOUNDARY,
        flight_end_at=LATE_END,
        daily_budget_cents=100000,
        category_code="FOOTWEAR",
        keyword_match_terms=["red"],
    )

    response = api_client.decide_line_item_eligibility(
        world[SECOND]["id"], factories.decision_payload("APPROVE"), CATALOG_OPS
    )

    # The slot admits two concurrent occupants, so aggregate capacity is not the obstacle.
    validate_error(response, ERR_SLOT_BUFFER_CONFLICT, 409)
    assert reread_line_item(world, SECOND)["line_item_status"] == "PENDING_ELIGIBILITY"
    assert reread_line_item(world, FIRST)["line_item_status"] == "ELIGIBLE"
    assert reread_slot(world)["occupancy_count"] == 1


def test_invoice_with_no_settled_spend_cannot_be_issued():
    """A completed campaign that never held an auction has nothing to bill.

    PRD 2.12: "79. On invoice issuance: the computed `gross_spend_cents` is at least 1; an
    invoice with nothing to bill cannot be issued — otherwise `ERR_NOTHING_TO_INVOICE`,
    422."

    PRD 3.8: "Step three computes `gross_spend_cents` as `onsite_spend_cents` plus
    `offsite_spend_cents`."

    PRD 3.8: "The invoice is born `DRAFT` with `adjustment_round` 0, every money figure at
    0, and `issued_at`, `due_at`, `settled_at` and `issued_by_user_id` all null."

    Design: Corner/validations/issuing_an_invoice_with_zero_gross_spend_is_rejected
    """
    world = build_delivering_world(
        plan={"committed_total_cents": 2000000, "trade_fund_share_cents": 0},
        campaign={
            "flight_start_at": FLIGHT_START,
            "flight_end_at": FLIGHT_END,
            "allocated_budget_cents": 1000000,
            "daily_cap_cents": 200000,
        },
        line_item={
            "flight_start_at": FLIGHT_START,
            "flight_end_at": FLIGHT_END,
        },
    )
    build_completed_campaign(world, at_flight_end=False)
    build_draft_invoice(world, billing_period_code="2026-08")

    response = api_client.issue_invoice(
        world["invoice"]["id"], {"issue_note": "Empty August"}, BILLING_OPS
    )

    validate_error(response, ERR_NOTHING_TO_INVOICE, 422)
    invoice = reread_invoice(world)
    assert invoice["invoice_status"] == "DRAFT"
    assert invoice["gross_spend_cents"] == 0
    assert invoice["net_cash_due_cents"] == 0
    # Completion moved the billing dimension on, and the refused issuance leaves it there.
    assert reread_campaign(world)["billing_status"] == "PENDING_INVOICE"


def test_dispute_claim_above_what_the_invoice_can_return_is_refused():
    """A 300-cent claim against 227 cash plus a 57-cent deduction is refused.

    PRD 2.12: "76. On dispute filing: `claimed_amount_cents` does not exceed the invoice's
    `net_cash_due_cents` plus its `trade_fund_deduction_cents` — otherwise
    `ERR_CLAIM_EXCEEDS_INVOICE`, 422."

    PRD 3.9: "`claimed_amount_cents` is at least 1 and may not exceed the invoice's
    `net_cash_due_cents` plus its `trade_fund_deduction_cents`, which together are the whole
    of what the invoice can give back."

    Design: Corner/validations/dispute_claim_above_net_cash_plus_trade_fund_deduction_is_rejected
    """
    world = _issued_invoice_world()
    assert world["invoice"]["gross_spend_cents"] == 284
    assert world["invoice"]["trade_fund_deduction_cents"] == 57
    assert world["invoice"]["net_cash_due_cents"] == 227

    response = api_client.create_measurement_dispute(
        factories.measurement_dispute_payload(
            world["invoice"]["id"],
            world["invoice"]["version"],
            dispute_category="IMPRESSION_DISCREPANCY",
            claimed_amount_cents=300,
            line_item_id=world[PREMIUM]["id"],
            evidence_note="Over-claim beyond the invoice",
        ),
        ACCOUNT_MANAGER,
    )

    # The invoice can give back 227 + 57 = 284 cents in total, and 300 is above that.
    validate_error(response, ERR_CLAIM_EXCEEDS_INVOICE, 422)
    invoice = reread_invoice(world)
    assert invoice["invoice_status"] == "ISSUED"
    assert invoice["net_cash_due_cents"] == 227
    assert reread_campaign(world)["billing_status"] == "INVOICED"


def _issued_invoice_world():
    """A 2026-08 invoice issued over one 284-cent settled cost-per-click auction.

    The premium line item bids 200 against a 0.40-margin hero product and beats a 150 bid
    against a 0.20-margin one; the clearing figure ceils to 142 and two clicks make 284.
    """
    world = build_campaign_ready_world(
        accrual_cents=500000,
        plan={
            "committed_total_cents": 2000000,
            "trade_fund_share_cents": 200000,
        },
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
            "allocated_budget_cents": 1000000,
            "pacing_mode": "EVEN",
            "daily_cap_cents": 200000,
        },
    )
    build_catalog_product(
        world,
        key=SECOND_PRODUCT,
        category_code="FOOTWEAR",
        title="red canvas shoes",
        margin_pct=0.2,
    )
    for key, product_key, bid_cents, terms in (
        (PREMIUM, "product", 200, ["red", "shoes"]),
        (THIN, SECOND_PRODUCT, 150, ["red"]),
    ):
        build_eligible_line_item(
            world,
            key=key,
            product_key=product_key,
            bid_cents=bid_cents,
            bid_type="CPC",
            keyword_match_terms=terms,
            category_code="FOOTWEAR",
            flight_start_at=FLIGHT_START,
            flight_end_at=FLIGHT_END,
            daily_budget_cents=100000,
        )
    build_delivering_campaign(world, with_line_item=False)
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
    validate_success(
        api_client.settle_auction_event(world["auction"]["id"], None, AUCTION_SERVICE)
    )
    build_completed_campaign(world, at_flight_end=False)
    build_issued_invoice(world, billing_period_code="2026-08")
    return world
