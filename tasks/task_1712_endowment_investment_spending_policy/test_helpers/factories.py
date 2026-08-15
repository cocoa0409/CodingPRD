"""Payload factories — one per entity, input fields only (PRD §4)."""

DEFAULTS = {
    "POOL_NAME": "University Endowment Pool",
    "INCEPTION_FY": 2026,
    "SPENDING_RATE_BPS": 500,
    "SMOOTHING_WINDOW_QUARTERS": 4,
    "BAND_FLOOR_BPS": 0,
    "BAND_CAP_BPS": 10000,
    "DONOR_NAME": "Test Donor",
    "DONOR_TYPE": "INDIVIDUAL",
    "FUND_CODE": "FUND-1",
    "FUND_NAME": "Test Fund",
    "ENDOWMENT_CLASS": "TRUE_ENDOWMENT",
    "PURPOSE_RESTRICTION": "UNRESTRICTED",
    "GIFT_TYPE": "CORPUS",
    "GIFT_AMOUNT_CENTS": 10_000_000,
    "MANAGER_NAME": "Test Manager",
    "ASSET_CLASS": "US_EQUITY",
    "BENCHMARK_CODE": "SPX",
    "REBALANCE_BAND_BPS": 500,
    "PROGRAM_PURPOSE": "RESEARCH",
    "JUSTIFICATION": "bridge funding",
}


def create_pool_payload(**overrides) -> dict:
    defaults = {
        "pool_name": DEFAULTS["POOL_NAME"],
        "inception_fiscal_year": DEFAULTS["INCEPTION_FY"],
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(pool_id: str, **overrides) -> dict:
    defaults = {
        "pool_id": pool_id,
        "spending_rate_bps": DEFAULTS["SPENDING_RATE_BPS"],
        "smoothing_window_quarters": DEFAULTS["SMOOTHING_WINDOW_QUARTERS"],
        "band_floor_bps": DEFAULTS["BAND_FLOOR_BPS"],
        "band_cap_bps": DEFAULTS["BAND_CAP_BPS"],
        "effective_from_fiscal_year": DEFAULTS["INCEPTION_FY"],
    }
    defaults.update(overrides)
    return defaults


def create_valuation_payload(pool_id: str, **overrides) -> dict:
    defaults = {
        "pool_id": pool_id,
        "estimated_pool_market_value_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_donor_payload(**overrides) -> dict:
    defaults = {
        "donor_name": DEFAULTS["DONOR_NAME"],
        "donor_type": DEFAULTS["DONOR_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_fund_payload(pool_id: str, **overrides) -> dict:
    defaults = {
        "pool_id": pool_id,
        "fund_code": DEFAULTS["FUND_CODE"],
        "fund_name": DEFAULTS["FUND_NAME"],
        "endowment_class": DEFAULTS["ENDOWMENT_CLASS"],
        "purpose_restriction": DEFAULTS["PURPOSE_RESTRICTION"],
    }
    defaults.update(overrides)
    return defaults


def create_gift_payload(fund_id: str, donor_id, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "donor_id": donor_id,
        "external_ref": "GIFT-1",
        "gift_type": DEFAULTS["GIFT_TYPE"],
        "amount_cents": DEFAULTS["GIFT_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_distribution_payload(fund_id: str, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "fiscal_year": DEFAULTS["INCEPTION_FY"],
    }
    defaults.update(overrides)
    return defaults


def create_exception_payload(fund_id: str, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "fiscal_year": DEFAULTS["INCEPTION_FY"],
        "requested_amount_cents": 300_000,
        "justification": DEFAULTS["JUSTIFICATION"],
    }
    defaults.update(overrides)
    return defaults


def create_payout_payload(distribution_id: str, **overrides) -> dict:
    defaults = {
        "distribution_id": distribution_id,
        "program_code": "PROG-1",
        "program_purpose": DEFAULTS["PROGRAM_PURPOSE"],
        "allocated_amount_cents": 200_000,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_item(asset_class: str, target_pct_bps: int, rebalance_band_bps: int = 500) -> dict:
    return {
        "asset_class": asset_class,
        "target_pct_bps": target_pct_bps,
        "rebalance_band_bps": rebalance_band_bps,
    }


def bulk_upsert_allocations_payload(pool_id: str, items: list) -> dict:
    return {"pool_id": pool_id, "items": items}


def create_manager_payload(pool_id: str, **overrides) -> dict:
    defaults = {
        "pool_id": pool_id,
        "manager_name": DEFAULTS["MANAGER_NAME"],
        "asset_class": DEFAULTS["ASSET_CLASS"],
        "benchmark_code": DEFAULTS["BENCHMARK_CODE"],
        "coverage_start_quarter": 1,
    }
    defaults.update(overrides)
    return defaults


def create_manager_report_payload(manager_id: str, quarter_index: int, **overrides) -> dict:
    defaults = {
        "manager_id": manager_id,
        "quarter_index": quarter_index,
        "beginning_mv_cents": 0,
        "ending_mv_cents": 0,
        "flows": [],
        "benchmark_return_bps": 0,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(pool_id: str, **overrides) -> dict:
    defaults = {
        "pool_id": pool_id,
        "report_type": "SPENDING_COMPLIANCE",
        "fiscal_year": DEFAULTS["INCEPTION_FY"],
    }
    defaults.update(overrides)
    return defaults
