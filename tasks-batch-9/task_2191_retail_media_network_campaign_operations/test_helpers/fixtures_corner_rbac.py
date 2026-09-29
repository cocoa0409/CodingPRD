"""Composite builders for the corner-case suites that exercise breadth.

The corner suites all stand on one shared chain, stated once here so the figures a
corner test asserts are traceable to the payload that produced them:

* a self-serve advertiser with a 50,000,000-cent credit limit and a 5,000,000-cent
  daily self-serve cap, active through KYC;
* a 2026-Q3 budget plan committing 2,000,000 cents over the window that opens at the
  startup clock;
* one on-site search-results slot with a 50-cent floor and room for two line items;
* an on-site-only campaign allocated 1,000,000 cents over a ten-day flight;
* line item A bidding 200 cents on "red shoes" and line item B bidding 150 cents on
  "red", each with its own hero product, so an auction has both a winner and a
  runner-up.

Each builder takes the same override dictionaries the base fixtures take, so a test
can vary the one figure its rule is about — a plan's commitment, a slot's floor, a
line item's daily budget — and leave the rest of the chain alone.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .fixtures import (
    build_active_advertiser,
    build_active_budget_plan,
    build_awarded_auction,
    build_catalog_product,
    build_delivering_campaign,
    build_draft_campaign,
    build_engagement_event,
    build_offsite_placement_slot,
    build_placement_slot,
    build_second_line_item_on_same_slot,
    build_trade_fund_pool,
    build_world,
)
from .test_users import AUCTION_SERVICE, BILLING_OPS

# ---------------------------------------------------------------------------
# The shared payload figures
# ---------------------------------------------------------------------------

BASELINE_ADVERTISER = {
    "legal_name": "Nordvale Foods LLC",
    "service_model": "SELF_SERVE",
    "credit_limit_cents": 50000000,
    "self_serve_daily_spend_cap_cents": 5000000,
}

BASELINE_PLAN = {
    "fiscal_period_code": "2026-Q3",
    "committed_total_cents": 2000000,
    "trade_fund_share_cents": 0,
    "window_start_at": "2026-08-01T00:00:00Z",
    "window_end_at": "2026-10-01T00:00:00Z",
}

BASELINE_SLOT = {
    "slot_code": "SRP-A1",
    "channel": "ONSITE",
    "page_type": "SEARCH_RESULTS",
    "position_index": 1,
    "max_concurrent_line_items": 2,
    "floor_cpc_cents": 50,
    "relevance_weight": 1.0,
}

BASELINE_CAMPAIGN = {
    "name": "Back to School",
    "channel_mix": "ONSITE_ONLY",
    "flight_start_at": "2026-08-01T00:00:00Z",
    "flight_end_at": "2026-08-11T00:00:00Z",
    "allocated_budget_cents": 1000000,
    "pacing_mode": "EVEN",
    "daily_cap_cents": 200000,
    "attribution_model": "LAST_TOUCH",
    "attribution_window_days": 14,
}

BASELINE_PRODUCT_A = {
    "sku": "SKU-RED-1",
    "category_code": "FOOTWEAR",
    "title": "red shoes",
    "price_cents": 5000,
    "in_stock_units": 50,
    "margin_pct": 0.4,
}

BASELINE_PRODUCT_B = {
    "sku": "SKU-RED-2",
    "category_code": "FOOTWEAR",
    "title": "red sandals",
    "price_cents": 4000,
    "in_stock_units": 40,
    "margin_pct": 0.2,
}

BASELINE_LINE_ITEM_A = {
    "bid_cents": 200,
    "bid_type": "CPC",
    "flight_start_at": "2026-08-01T00:00:00Z",
    "flight_end_at": "2026-08-11T00:00:00Z",
    "daily_budget_cents": 100000,
    "category_code": "FOOTWEAR",
    "keyword_match_terms": ["red", "shoes"],
}

BASELINE_LINE_ITEM_B = {
    "bid_cents": 150,
    "bid_type": "CPC",
    "flight_start_at": "2026-08-01T00:00:00Z",
    "flight_end_at": "2026-08-11T00:00:00Z",
    "daily_budget_cents": 100000,
    "category_code": "FOOTWEAR",
    "keyword_match_terms": ["red"],
}

BASELINE_AUCTION = {
    "request_context_query": "red shoes sale",
    "shopper_segment": "RETURNING",
    "requested_at": "2026-08-01T12:00:00Z",
}

# The three engagements the baseline auction carries: one view and two clicks, the
# first click and the impression sharing a shopper so a single-touch credit has an
# unambiguous target.
BASELINE_ENGAGEMENTS = (
    ("IMPRESSION", "2026-08-01T12:05:00Z", "sh_1"),
    ("CLICK", "2026-08-01T12:10:00Z", "sh_1"),
    ("CLICK", "2026-08-01T12:20:00Z", "sh_2"),
)


def _merged(base: dict, overrides: dict = None) -> dict:
    """Return the baseline figures with a test's own overrides applied last."""
    merged = dict(base)
    merged.update(overrides or {})
    return merged


# ---------------------------------------------------------------------------
# Layer by layer
# ---------------------------------------------------------------------------


def build_baseline_advertiser(world: dict = None, **overrides):
    """Register the baseline self-serve advertiser and take it to ACTIVE."""
    return build_active_advertiser(world, **_merged(BASELINE_ADVERTISER, overrides))


def build_baseline_plan(world: dict, **overrides):
    """Approve the baseline 2026-Q3 plan for this world's advertiser."""
    return build_active_budget_plan(world, **_merged(BASELINE_PLAN, overrides))


def build_baseline_inventory(world: dict, offsite: bool = False, slot: dict = None,
                             product: dict = None):
    """Add the baseline slot and the baseline hero product."""
    if offsite:
        build_offsite_placement_slot(world, **_merged(BASELINE_SLOT, slot))
    else:
        build_placement_slot(world, **_merged(BASELINE_SLOT, slot))
    build_catalog_product(world, **_merged(BASELINE_PRODUCT_A, product))
    return world


def build_baseline_campaign_world(
    world: dict = None,
    advertiser: dict = None,
    plan: dict = None,
    pool: dict = None,
    slot: dict = None,
    product: dict = None,
    campaign: dict = None,
    offsite: bool = False,
):
    """Advertiser, plan, inventory and a DRAFT campaign, with no line item yet.

    A trade fund pool is opened only when `pool` is supplied, because a plan whose
    trade fund share is 0 needs none. The pool dictionary may carry `accrual_cents`
    alongside the pool's own fields.
    """
    world = build_world() if world is None else world
    build_baseline_advertiser(world, **(advertiser or {}))
    if pool is not None:
        build_trade_fund_pool(world, **pool)
    build_baseline_plan(world, **(plan or {}))
    build_baseline_inventory(world, offsite=offsite, slot=slot, product=product)
    build_draft_campaign(world, **_merged(BASELINE_CAMPAIGN, campaign))
    return world


def build_baseline_delivering_world(world: dict = None, line_item: dict = None, **kwargs):
    """The baseline campaign DELIVERING with line item A carried to SERVING.

    Campaign activation takes every eligible line item to SERVING by itself, so the
    line item is never activated a second time.
    """
    world = build_baseline_campaign_world(world, **kwargs)
    build_delivering_campaign(world, **_merged(BASELINE_LINE_ITEM_A, line_item))
    return world


def build_baseline_second_line_item(world: dict, product: dict = None, **overrides):
    """Add line item B on the same slot with its own hero product, serving.

    Line item B is the auction's runner-up: it is what gives the second-price
    clearing figure something to be second to.
    """
    build_catalog_product(world, key="product_b", **_merged(BASELINE_PRODUCT_B, product))
    return build_second_line_item_on_same_slot(
        world,
        key="second_line_item",
        activate=True,
        product_key="product_b",
        **_merged(BASELINE_LINE_ITEM_B, overrides),
    )


def build_baseline_engagements(world: dict, auction_key: str = "auction"):
    """Record the baseline impression and the two clicks on the awarded auction."""
    for event_type, occurred_at, shopper_hash in BASELINE_ENGAGEMENTS:
        build_engagement_event(
            world,
            event_type=event_type,
            auction_key=auction_key,
            occurred_at=occurred_at,
            shopper_hash=shopper_hash,
        )
    return world


def build_baseline_awarded_auction(world: dict, key: str = "auction", **overrides):
    """Open, rank and award the baseline auction, then record its engagements."""
    build_awarded_auction(world, key=key, **_merged(BASELINE_AUCTION, overrides))
    build_baseline_engagements(world, auction_key=key)
    return world


def build_baseline_settled_auction(world: dict, key: str = "auction", headers: dict = None,
                                   **overrides):
    """Take the baseline auction to SETTLED, recognising the two clicks as spend."""
    build_baseline_awarded_auction(world, key=key, **overrides)
    world[key] = get_success_data(
        api_client.settle_auction_event(
            world[key]["id"], None, headers or AUCTION_SERVICE
        )
    )
    return world


def build_baseline_billing_world(world: dict = None, **kwargs):
    """The whole baseline chain delivered, settled and completed, ready to invoice.

    The campaign is completed without moving the clock, so the invoice that follows
    is issued at the same instant the campaign delivered and its due date follows
    from that instant alone.
    """
    kwargs.setdefault("pool", {"accrual_cents": 500000, "deduction_cap_pct": 0.6})
    kwargs.setdefault("plan", {"trade_fund_share_cents": 200000})
    world = build_baseline_delivering_world(world, **kwargs)
    build_baseline_second_line_item(world)
    build_baseline_settled_auction(world)
    world["campaign"] = get_success_data(
        api_client.complete_campaign(world["campaign"]["id"], None, BILLING_OPS)
    )
    return world


def build_baseline_draft_invoice(world: dict, billing_period_code: str = "2026-08"):
    """Open the 2026-08 invoice against the baseline plan and pool."""
    invoice = get_success_data(
        api_client.create_invoice(
            f.invoice_payload(
                world["advertiser"]["id"],
                world["plan"]["id"],
                world["pool"]["id"],
                billing_period_code=billing_period_code,
            ),
            BILLING_OPS,
        )
    )
    world["invoice"] = invoice
    world["invoices"].append(invoice)
    return world
