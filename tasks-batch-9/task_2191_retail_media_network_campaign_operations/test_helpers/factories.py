"""Request payload builders for the retail media network API.

Each builder returns the smallest payload the PRD accepts, with every value inside its
stated bounds, and merges `**overrides` last so a test can vary exactly the one field
it is about and leave the rest valid. A test that wants an invalid payload passes the
invalid value as an override rather than assembling a dict by hand, which keeps the
intent visible.

Fields that must be unique across all rows — an advertiser's `brand_code`, a slot's
`slot_code`, a product's `sku` — are given a fresh suffix on every call, so two
resources built in one test never collide.
"""

import itertools

from .constants import CLOCK_STARTUP_DEFAULT

_COUNTER = itertools.count(1)


def _unique(prefix: str, width: int = 4) -> str:
    """Return a short unique token suitable for a globally unique code field."""
    return "%s%0*d" % (prefix, width, next(_COUNTER))


def reset_unique_counter() -> None:
    """Restart the unique-token counter. Each test gets a fresh database anyway."""
    global _COUNTER
    _COUNTER = itertools.count(1)


# ---------------------------------------------------------------------------
# Advertisers, plans and pools
# ---------------------------------------------------------------------------


def advertiser_payload(**overrides) -> dict:
    """Build a self-serve advertiser registration payload.

    `credit_limit_cents` is set well above any figure the tests commit so credit is
    never the incidental reason a request is refused.
    """
    payload = {
        "legal_name": "Northwind Grocery Brands LLC",
        "brand_code": _unique("BRND"),
        "service_model": "SELF_SERVE",
        "credit_limit_cents": 100000000,
        "self_serve_daily_spend_cap_cents": 500000,
    }
    payload.update(overrides)
    return payload


def managed_advertiser_payload(**overrides) -> dict:
    """Build a managed advertiser registration payload.

    A managed advertiser contributes no self-serve daily spend cap, so the auction
    headroom for its line items is decided by the line item and campaign caps alone.
    The service-model consistency rule requires a `MANAGED` advertiser to carry a
    non-null `account_manager_user_id`, so the account manager's operator identifier
    is named here rather than left for each test to remember.
    """
    payload = {
        "legal_name": "Harbourview Managed Brands LLC",
        "brand_code": _unique("MNGD"),
        "service_model": "MANAGED",
        "credit_limit_cents": 100000000,
        "managed_service_fee_pct": 0.1,
        "account_manager_user_id": "am_001",
    }
    payload.update(overrides)
    return payload


def submit_onboarding_payload(**overrides) -> dict:
    """Build an onboarding submission payload."""
    payload = {"kyc_document_count": 2}
    payload.update(overrides)
    return payload


def kyc_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    """Build a KYC decision payload."""
    payload = {"decision": decision, "decision_note": "KYC cleared"}
    payload.update(overrides)
    return payload


def budget_plan_payload(
    advertiser_id: str, expected_advertiser_version: int, **overrides
) -> dict:
    """Build an all-cash budget plan payload whose window contains the startup clock."""
    payload = {
        "advertiser_id": advertiser_id,
        "fiscal_period_code": "2026-Q3",
        "committed_total_cents": 5000000,
        "trade_fund_share_cents": 0,
        "window_start_at": "2026-07-01T00:00:00Z",
        "window_end_at": "2026-10-01T00:00:00Z",
        "expected_advertiser_version": expected_advertiser_version,
    }
    payload.update(overrides)
    return payload


def trade_fund_account_payload(advertiser_id: str, **overrides) -> dict:
    """Build a trade fund pool payload for the same fiscal period as the plans."""
    payload = {
        "advertiser_id": advertiser_id,
        "fiscal_period_code": "2026-Q3",
        "accrual_basis": "PURCHASE_VOLUME",
        "deduction_cap_pct": 0.6,
    }
    payload.update(overrides)
    return payload


def accrual_payload(amount_cents: int = 3000000, **overrides) -> dict:
    """Build a co-op accrual posting payload."""
    payload = {
        "accrual_amount_cents": amount_cents,
        "accrual_reference": _unique("ACCR-2026-Q3-"),
    }
    payload.update(overrides)
    return payload


def deduction_payload(
    amount_cents: int, expected_trade_fund_account_version: int, **overrides
) -> dict:
    """Build a manual trade fund deduction payload."""
    payload = {
        "deduction_amount_cents": amount_cents,
        "deduction_reference": _unique("DEDU-2026-Q3-"),
        "expected_trade_fund_account_version": expected_trade_fund_account_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Inventory and catalog
# ---------------------------------------------------------------------------


def placement_slot_payload(**overrides) -> dict:
    """Build an on-site placement slot payload.

    `buffer_minutes` is zero and `exclusivity_category_code` is absent, so only the
    aggregate capacity rule can refuse a candidate on this slot.
    """
    payload = {
        "slot_code": _unique("ONSITE-SR-"),
        "channel": "ONSITE",
        "page_type": "SEARCH_RESULTS",
        "position_index": 1,
        "max_concurrent_line_items": 2,
        "floor_cpc_cents": 40,
        "relevance_weight": 1.0,
        "buffer_minutes": 0,
    }
    payload.update(overrides)
    return payload


def offsite_placement_slot_payload(**overrides) -> dict:
    """Build an off-site placement slot payload carrying an adjacency buffer.

    `buffer_minutes` has effect only on an off-site slot, so the buffer rule can be
    exercised here and nowhere else.
    """
    payload = {
        "slot_code": _unique("OFFSITE-SOC-"),
        "channel": "OFFSITE",
        "page_type": "OFFSITE_SOCIAL",
        "position_index": 1,
        "max_concurrent_line_items": 4,
        "floor_cpc_cents": 60,
        "relevance_weight": 1.0,
        "buffer_minutes": 60,
    }
    payload.update(overrides)
    return payload


def catalog_product_payload(**overrides) -> dict:
    """Build an in-stock catalog product payload."""
    payload = {
        "sku": _unique("SKU-"),
        "category_code": "COFFEE",
        "title": "cold brew coffee concentrate",
        "price_cents": 899,
        "in_stock_units": 220,
        "margin_pct": 0.3,
        "min_stock_units_for_serving": 3,
    }
    payload.update(overrides)
    return payload


def stock_adjustment_payload(delta_units: int, **overrides) -> dict:
    """Build a signed stock movement payload."""
    payload = {
        "delta_units": delta_units,
        "adjustment_reference": _unique("STK-"),
    }
    payload.update(overrides)
    return payload


def product_assignment_payload(
    line_item_id: str, catalog_product_id: str, expected_line_item_version: int, **overrides
) -> dict:
    """Build a hero product assignment payload."""
    payload = {
        "line_item_id": line_item_id,
        "catalog_product_id": catalog_product_id,
        "is_hero": True,
        "expected_line_item_version": expected_line_item_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Campaigns and line items
# ---------------------------------------------------------------------------


def campaign_payload(
    advertiser_id: str, budget_plan_id: str, **overrides
) -> dict:
    """Build an on-site-only campaign payload with an even-paced flight.

    The flight opens after the startup clock, so the campaign can be taken through
    review before any flight window gate applies.
    """
    payload = {
        "advertiser_id": advertiser_id,
        "budget_plan_id": budget_plan_id,
        "name": "Northwind Q3 Search",
        "channel_mix": "ONSITE_ONLY",
        "flight_start_at": "2026-08-05T00:00:00Z",
        "flight_end_at": "2026-08-20T00:00:00Z",
        "allocated_budget_cents": 2000000,
        "pacing_mode": "EVEN",
        "daily_cap_cents": 200000,
        "attribution_model": "LAST_TOUCH",
        "attribution_window_days": 14,
    }
    payload.update(overrides)
    return payload


def line_item_payload(
    campaign_id: str, placement_slot_id: str, expected_campaign_version: int, **overrides
) -> dict:
    """Build a cost-per-click line item payload nested inside the campaign flight."""
    payload = {
        "campaign_id": campaign_id,
        "placement_slot_id": placement_slot_id,
        "bid_cents": 150,
        "bid_type": "CPC",
        "flight_start_at": "2026-08-05T00:00:00Z",
        "flight_end_at": "2026-08-19T00:00:00Z",
        "daily_budget_cents": 100000,
        "category_code": "COFFEE",
        "keyword_match_terms": ["cold", "brew", "coffee"],
        "expected_campaign_version": expected_campaign_version,
    }
    payload.update(overrides)
    return payload


def decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    """Build a generic approve-or-reject fork payload."""
    payload = {"decision": decision, "decision_note": "reviewed"}
    payload.update(overrides)
    return payload


def pause_payload(pause_reason: str = "MANUAL", **overrides) -> dict:
    """Build a pause payload carrying the reason stamped on affected line items."""
    payload = {"pause_reason": pause_reason}
    payload.update(overrides)
    return payload


def offsite_reconciliation_payload(reported_spend_cents: int, **overrides) -> dict:
    """Build a partner-reported off-site spend payload."""
    payload = {
        "offsite_reported_spend_cents": reported_spend_cents,
        "reporting_partner_code": "PARTNER_SOCIAL",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Auctions, engagements and sales
# ---------------------------------------------------------------------------


def auction_event_payload(
    placement_slot_id: str,
    requested_at: str = CLOCK_STARTUP_DEFAULT,
    **overrides,
) -> dict:
    """Build an auction request payload for one slot impression."""
    payload = {
        "placement_slot_id": placement_slot_id,
        "request_context_query": "coffee",
        "shopper_segment": "LOYALTY",
        "requested_at": requested_at,
    }
    payload.update(overrides)
    return payload


def engagement_event_payload(
    line_item_id: str,
    auction_event_id: str,
    catalog_product_id: str,
    event_type: str = "CLICK",
    occurred_at: str = CLOCK_STARTUP_DEFAULT,
    **overrides,
) -> dict:
    """Build an engagement record payload attached to one auction."""
    payload = {
        "line_item_id": line_item_id,
        "auction_event_id": auction_event_id,
        "catalog_product_id": catalog_product_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "shopper_hash": _unique("shopper-"),
        "channel": "ONSITE",
    }
    payload.update(overrides)
    return payload


def attributed_sale_payload(
    engagement_event_id: str,
    catalog_product_id: str,
    sale_cents: int = 5000,
    occurred_at: str = CLOCK_STARTUP_DEFAULT,
    **overrides,
) -> dict:
    """Build an attributed sale ingestion payload."""
    payload = {
        "engagement_event_id": engagement_event_id,
        "catalog_product_id": catalog_product_id,
        "retail_order_ref": _unique("ORD-"),
        "sale_cents": sale_cents,
        "units": 1,
        "occurred_at": occurred_at,
        "match_type": "CLICK_THROUGH",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def incrementality_study_payload(
    campaign_id: str, expected_campaign_version: int, **overrides
) -> dict:
    """Build a geo-holdout study design payload."""
    payload = {
        "campaign_id": campaign_id,
        "design_method": "GEO_HOLDOUT",
        "holdout_pct": 0.2,
        "window_start_at": "2026-08-05T00:00:00Z",
        "window_end_at": "2026-08-12T00:00:00Z",
        "expected_campaign_version": expected_campaign_version,
    }
    payload.update(overrides)
    return payload


def study_start_payload(
    exposed_group_size: int = 50000, control_group_size: int = 12500, **overrides
) -> dict:
    """Build a study start payload with both cohorts populated."""
    payload = {
        "exposed_group_size": exposed_group_size,
        "control_group_size": control_group_size,
    }
    payload.update(overrides)
    return payload


def study_measure_payload(
    exposed_conversions: int,
    control_conversions: int,
    exposed_sales_cents: int,
    control_sales_cents: int,
    **overrides,
) -> dict:
    """Build a study measurement payload from the four cohort counters."""
    payload = {
        "exposed_conversions": exposed_conversions,
        "control_conversions": control_conversions,
        "exposed_sales_cents": exposed_sales_cents,
        "control_sales_cents": control_sales_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------


def invoice_payload(
    advertiser_id: str,
    budget_plan_id: str,
    trade_fund_account_id: str,
    billing_period_code: str = "2026-08",
    **overrides,
) -> dict:
    """Build a draft invoice payload for one billing month."""
    payload = {
        "advertiser_id": advertiser_id,
        "budget_plan_id": budget_plan_id,
        "trade_fund_account_id": trade_fund_account_id,
        "billing_period_code": billing_period_code,
    }
    payload.update(overrides)
    return payload


def measurement_dispute_payload(
    invoice_id: str,
    expected_invoice_version: int,
    dispute_category: str = "IMPRESSION_DISCREPANCY",
    claimed_amount_cents: int = 10000,
    **overrides,
) -> dict:
    """Build a measurement dispute filing payload."""
    payload = {
        "invoice_id": invoice_id,
        "dispute_category": dispute_category,
        "claimed_amount_cents": claimed_amount_cents,
        "evidence_note": "partner log discrepancy attached",
        "expected_invoice_version": expected_invoice_version,
    }
    payload.update(overrides)
    return payload


def dispute_resolution_payload(
    decision: str = "UPHOLD", approved_credit_amount_cents: int = 0, **overrides
) -> dict:
    """Build a dispute resolution payload."""
    payload = {
        "decision": decision,
        "approved_credit_amount_cents": approved_credit_amount_cents,
        "resolution_note": "adjudicated",
    }
    payload.update(overrides)
    return payload
