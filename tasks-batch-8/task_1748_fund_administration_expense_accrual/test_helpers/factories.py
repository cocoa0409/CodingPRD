"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "FUND_NAME": "Alpha Fund",
    "TICKER": "ALPHX",
    "BASE_CURRENCY": "USD",
    "FISCAL_YEAR_END": "12-31",
    "ADVISER_NAME": "Alpha Advisers",
    "ADMIN_FEE_BPS": 10,
    "DAY_COUNT": "ACT_365",
    "CLASS_TICKER": "ALPHXI",
    "DISTRIBUTION_FREQUENCY": "QUARTERLY",
    "SECURITY_IDENTIFIER": "CUSIP0001",
    "SECURITY_DESCRIPTION": "Acme Corp",
    "ASSET_CLASS": "EQUITY",
    "PRICING_LEVEL": "LEVEL_1",
    "CURRENCY": "USD",
    "QUANTITY": 1000,
    "COST_BASIS": 50000,
    "OPENED_DATE": "2026-08-03",
    "PRICE": 100.00,
    "PRICE_SOURCE": "EXCHANGE_CLOSE",
    "ACCOUNTING_DATE": "2026-08-04",
    "ACTIVITY_DATE": "2026-08-03",
    "CAP_BPS": 10,
    "EFFECTIVE_FROM": "2026-08-01",
    "EFFECTIVE_TO": "2026-12-31",
    "RECOVERY_WINDOW_MONTHS": 3,
    "BREAK_TYPE": "CUSTODIAN_POSITION",
    "FEE_TYPE": "ADVISER",
    "FILING_TYPE": "N_PORT",
}

# Standard two-tier adviser schedule used across the domain tests.
TIERED_FEE_SCHEDULE = [
    {"up_to_net_assets": 100000000, "rate_bps": 50},
    {"up_to_net_assets": None, "rate_bps": 40},
]
# Flat single-tier adviser schedule.
FLAT_FEE_SCHEDULE = [{"up_to_net_assets": None, "rate_bps": 50}]


def create_fund_payload(**overrides) -> dict:
    defaults = {
        "fund_name": DEFAULTS["FUND_NAME"],
        "ticker": DEFAULTS["TICKER"],
        "base_currency": DEFAULTS["BASE_CURRENCY"],
        "fiscal_year_end": DEFAULTS["FISCAL_YEAR_END"],
        "adviser_name": DEFAULTS["ADVISER_NAME"],
        "admin_fee_bps": DEFAULTS["ADMIN_FEE_BPS"],
        "adviser_fee_tiers": [dict(t) for t in FLAT_FEE_SCHEDULE],
        "day_count_convention": DEFAULTS["DAY_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_share_class_payload(fund_id, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "class_ticker": DEFAULTS["CLASS_TICKER"],
        "distribution_frequency": DEFAULTS["DISTRIBUTION_FREQUENCY"],
    }
    defaults.update(overrides)
    return defaults


def create_security_payload(**overrides) -> dict:
    defaults = {
        "security_identifier": DEFAULTS["SECURITY_IDENTIFIER"],
        "description": DEFAULTS["SECURITY_DESCRIPTION"],
        "asset_class": DEFAULTS["ASSET_CLASS"],
        "default_pricing_level": DEFAULTS["PRICING_LEVEL"],
        "currency": DEFAULTS["CURRENCY"],
    }
    defaults.update(overrides)
    return defaults


def create_position_payload(share_class_id, security_id, **overrides) -> dict:
    defaults = {
        "share_class_id": share_class_id,
        "security_id": security_id,
        "quantity": DEFAULTS["QUANTITY"],
        "cost_basis_total": DEFAULTS["COST_BASIS"],
        "opened_date": DEFAULTS["OPENED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_price_observation_payload(security_id, **overrides) -> dict:
    defaults = {
        "security_id": security_id,
        "price_date": DEFAULTS["ACCOUNTING_DATE"],
        "price": DEFAULTS["PRICE"],
        "source": DEFAULTS["PRICE_SOURCE"],
        "pricing_level": DEFAULTS["PRICING_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def create_nav_record_payload(share_class_id, **overrides) -> dict:
    defaults = {
        "share_class_id": share_class_id,
        "accounting_date": DEFAULTS["ACCOUNTING_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_expense_accrual_payload(share_class_id, accrual_date, **overrides) -> dict:
    defaults = {
        "share_class_id": share_class_id,
        "accrual_date": accrual_date,
        "category": "CUSTODY_FEE",
        "annual_rate_bps": 5,
    }
    defaults.update(overrides)
    return defaults


def create_waiver_agreement_payload(share_class_id, **overrides) -> dict:
    defaults = {
        "share_class_id": share_class_id,
        "cap_bps": DEFAULTS["CAP_BPS"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
        "recovery_window_months": DEFAULTS["RECOVERY_WINDOW_MONTHS"],
    }
    defaults.update(overrides)
    return defaults


def create_recoupment_payload(**overrides) -> dict:
    defaults = {"amount": 0.01, "recoup_date": "2026-08-10"}
    defaults.update(overrides)
    return defaults


def create_distribution_payload(share_class_id, **overrides) -> dict:
    defaults = {
        "share_class_id": share_class_id,
        "declaration_date": "2026-08-05",
        "ex_date": "2026-08-06",
        "record_date": "2026-08-07",
        "payable_date": "2026-08-10",
    }
    defaults.update(overrides)
    return defaults


def create_reconciliation_break_payload(fund_id, position_id, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "position_id": position_id,
        "break_type": DEFAULTS["BREAK_TYPE"],
        "break_date": "2026-08-04",
        "counterparty_quantity": 900,
    }
    defaults.update(overrides)
    return defaults


def create_fee_invoice_payload(fund_id, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "fee_type": DEFAULTS["FEE_TYPE"],
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
    }
    defaults.update(overrides)
    return defaults


def create_regulatory_filing_payload(fund_id, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "filing_type": DEFAULTS["FILING_TYPE"],
        "period_end": "2026-07-31",
    }
    defaults.update(overrides)
    return defaults
