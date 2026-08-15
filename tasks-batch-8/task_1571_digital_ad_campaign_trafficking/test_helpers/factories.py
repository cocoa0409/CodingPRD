"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import TEST_DEFAULTS


def create_insertion_order_payload(**overrides) -> dict:
    defaults = {
        "advertiser_name": "Acme",
        "total_budget_cents": TEST_DEFAULTS["IO_TOTAL_BUDGET_CENTS"],
        "flight_start": TEST_DEFAULTS["FLIGHT_START"],
        "flight_end": TEST_DEFAULTS["FLIGHT_END"],
        "billing_basis": "LOWER_OF",
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(io_id, **overrides) -> dict:
    defaults = {
        "io_id": io_id,
        "name": "LI1",
        "goal_impressions": TEST_DEFAULTS["GOAL_IMPRESSIONS"],
        "cpm_rate_cents": TEST_DEFAULTS["CPM_RATE_CENTS"],
        "start_date": TEST_DEFAULTS["FLIGHT_START"],
        "end_date": TEST_DEFAULTS["FLIGHT_END"],
        "pacing_mode": "EVEN",
    }
    defaults.update(overrides)
    return defaults


def create_creative_payload(line_item_id, **overrides) -> dict:
    defaults = {
        "line_item_id": line_item_id,
        "name": "CR1",
        "asset_url": "https://cdn.example.com/a.jpg",
        "width": 300,
        "height": 250,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_snapshot_payload(line_item_id, snapshot_date, impressions,
                                     clicks, **overrides) -> dict:
    defaults = {
        "line_item_id": line_item_id,
        "snapshot_date": snapshot_date,
        "impressions": impressions,
        "clicks": clicks,
    }
    defaults.update(overrides)
    return defaults


def create_impression_event_payload(line_item_id, user_key, **overrides) -> dict:
    defaults = {
        "line_item_id": line_item_id,
        "user_key": user_key,
    }
    defaults.update(overrides)
    return defaults


def create_verification_report_payload(line_item_id, **overrides) -> dict:
    defaults = {
        "line_item_id": line_item_id,
        "vendor": "MOAT",
        "period_start": "2026-08-01",
        "period_end": "2026-08-07",
        "measured_impressions": 100000,
        "viewable_impressions": 80000,
        "ivt_impressions": 0,
    }
    defaults.update(overrides)
    return defaults


def create_make_good_payload(verification_report_id, **overrides) -> dict:
    defaults = {
        "verification_report_id": verification_report_id,
        "kind": "CREDIT",
        "credit_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_reconciliation_payload(line_item_id, **overrides) -> dict:
    defaults = {
        "line_item_id": line_item_id,
        "period_start": "2026-08-01",
        "period_end": "2026-08-10",
        "third_party_impressions": 0,
    }
    defaults.update(overrides)
    return defaults


def create_wrap_report_payload(io_id, **overrides) -> dict:
    defaults = {
        "io_id": io_id,
        "attribution_model": "LINEAR_CLICKS",
        "total_conversions": 10,
    }
    defaults.update(overrides)
    return defaults
