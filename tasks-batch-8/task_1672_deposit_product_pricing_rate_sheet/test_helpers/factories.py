"""Payload factories — one per creatable resource, input fields only (PRD §3, §4)."""
from typing import List, Optional

from .constants import TEST_DEFAULTS
from .types import TierRow


def tier(tier_index: int, lower_bound_cents: int, upper_bound_cents: int,
         rate_bp: int, projected_balance_cents: int = 1_000_000) -> TierRow:
    """Build one tier row. upper_bound_cents=-1 marks the unbounded final tier."""
    return {
        "tier_index": tier_index,
        "lower_bound_cents": lower_bound_cents,
        "upper_bound_cents": upper_bound_cents,
        "rate_bp": rate_bp,
        "projected_balance_cents": projected_balance_cents,
    }


def single_tier(rate_bp: int, projected_balance_cents: int = 1_000_000) -> List[TierRow]:
    """A structurally valid single-tier set: [0, unbounded) at the given rate."""
    return [tier(0, 0, -1, rate_bp, projected_balance_cents)]


def create_product_payload(**overrides) -> dict:
    defaults = {
        "product_code": "SAV-STD",
        "product_class": "SAVINGS",
        "term_months": 0,
        "tier_application": "WHOLE_BALANCE",
        "rate_cap_bp": TEST_DEFAULTS["RATE_CAP_BP"],
        "allows_promos": True,
        "allows_exceptions": True,
    }
    defaults.update(overrides)
    return defaults


def create_rate_sheet_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "market_code": TEST_DEFAULTS["MARKET"],
        "effective_date": TEST_DEFAULTS["EFFECTIVE_DATE"],
        "disclosure_lead_days": TEST_DEFAULTS["DISCLOSURE_LEAD_DAYS"],
        "margin_floor_bp": TEST_DEFAULTS["MARGIN_FLOOR_BP"],
        "tiers": single_tier(100),
    }
    defaults.update(overrides)
    return defaults


def create_scan_payload(**overrides) -> dict:
    defaults = {
        "market_code": TEST_DEFAULTS["MARKET"],
        "scan_date": "2026-08-01",
        "source_name": "RateWatch",
        "entries": [],
    }
    defaults.update(overrides)
    return defaults


def scan_entry(competitor_name: str, product_class: str, rate_bp: int,
               tier_balance_cents: int) -> dict:
    return {
        "competitor_name": competitor_name,
        "product_class": product_class,
        "rate_bp": rate_bp,
        "tier_balance_cents": tier_balance_cents,
    }


def create_repricing_cycle_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "market_code": TEST_DEFAULTS["MARKET"],
        "cadence_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_promo_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "market_code": TEST_DEFAULTS["MARKET"],
        "promo_rate_bp": 500,
        "promo_term_days": 30,
        "enrollment_start": "2026-08-15",
        "enrollment_end": "2026-09-30",
        "min_opening_balance_cents": 0,
        "rollover_treatment": "ROLL_TO_SHEET",
    }
    defaults.update(overrides)
    return defaults


def create_exception_request_payload(account_id: str, sheet_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "sheet_id": sheet_id,
        "requested_rate_bp": 500,
        "term_days": 60,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "customer_ref": "CUST-1",
        "product_id": product_id,
        "market_code": TEST_DEFAULTS["MARKET"],
        "opening_balance_cents": 1_000_000,
        "channel": "ONLINE",
    }
    defaults.update(overrides)
    return defaults


def create_funding_curve_payload(**overrides) -> dict:
    defaults = {
        "curve_date": "2026-08-01",
        "points": [{"tenor_months": 0, "cost_bp": 210}],
    }
    defaults.update(overrides)
    return defaults


def create_bundle_payload(**overrides) -> dict:
    defaults = {
        "bundle_code": "PREMIER",
        "bonus_bp": 25,
        "min_combined_balance_cents": 10_000_000,
        "required_product_classes": ["MONEY_MARKET", "SAVINGS"],
        "eligible_product_classes": ["MONEY_MARKET"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(bundle_id: str, customer_ref: str) -> dict:
    return {"bundle_id": bundle_id, "customer_ref": customer_ref}


def create_migration_batch_payload(source_sheet_id: str, target_sheet_id: str) -> dict:
    return {"source_sheet_id": source_sheet_id, "target_sheet_id": target_sheet_id}
