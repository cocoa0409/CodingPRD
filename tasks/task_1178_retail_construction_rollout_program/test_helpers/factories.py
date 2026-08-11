"""Payload factories — one per resource, input fields only."""
from .constants import TEST_DEFAULTS as D


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": D["PROGRAM_NAME"],
        "fiscal_year": D["FISCAL_YEAR"],
        "total_budget_cents": D["TOTAL_BUDGET_CENTS"],
        "contingency_pool_cents": D["CONTINGENCY_POOL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_market_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": D["MARKET_NAME"],
        "state_code": D["STATE_CODE"],
        "max_concurrent_vendor_crews": D["MAX_CREWS"],
    }
    defaults.update(overrides)
    return defaults


def create_municipality_profile_payload(**overrides) -> dict:
    defaults = {
        "municipality_code": D["MUNICIPALITY_CODE"],
        "statutory_review_days": D["STATUTORY_REVIEW_DAYS"],
        "observed_avg_review_days": D["OBSERVED_AVG_REVIEW_DAYS"],
        "permit_validity_days": D["PERMIT_VALIDITY_DAYS"],
        "fee_base_cents": D["FEE_BASE_CENTS"],
        "fee_per_sqft_cents": D["FEE_PER_SQFT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(program_id: str, market_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "market_id": market_id,
        "municipality_code": D["MUNICIPALITY_CODE"],
        "address": D["SITE_ADDRESS"],
        "square_footage": D["SQUARE_FOOTAGE"],
        "phase_wave": D["PHASE_WAVE"],
        "budget_allocation_cents": D["BUDGET_ALLOCATION_CENTS"],
        "target_open_date": D["TARGET_OPEN_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_drawing_set_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "jurisdiction_code": D["MUNICIPALITY_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(site_id: str, drawing_set_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "permit_type": "BUILDING",
        "drawing_set_id": drawing_set_id,
    }
    defaults.update(overrides)
    return defaults


def create_contractor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "GC One LLC",
        "license_no": "GC-100",
        "license_state": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_bid_package_payload(market_id: str, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "phase_wave": D["PHASE_WAVE"],
        "scope_description": "Wave 1 GC",
        "bid_open_at": D["BID_OPEN_AT"],
        "bid_close_at": D["BID_CLOSE_AT"],
        "evaluation_mode": "LOWEST_PRICE",
        "max_duration_days": D["MAX_DURATION_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(bid_package_id: str, contractor_id: str, **overrides) -> dict:
    defaults = {
        "bid_package_id": bid_package_id,
        "contractor_id": contractor_id,
        "amount_cents": D["BID_AMOUNT_CENTS"],
        "duration_days": D["BID_DURATION_DAYS"],
        "tech_score": D["BID_TECH_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_mobilization_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "vendor_type": "FIXTURE",
        "vendor_name": "Fixtures R Us",
        "planned_start_on": "2026-06-01",
        "planned_end_on": "2026-06-21",
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "description": "Change order",
        "amount_cents": 100_000,
        "cost_category": "SCOPE",
    }
    defaults.update(overrides)
    return defaults


def create_punch_item_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "description": "Deficiency",
        "severity": "MINOR",
    }
    defaults.update(overrides)
    return defaults


def create_turnover_payload(site_id: str, **overrides) -> dict:
    defaults = {"site_id": site_id}
    defaults.update(overrides)
    return defaults
