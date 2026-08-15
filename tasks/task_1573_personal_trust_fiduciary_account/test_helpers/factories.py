"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "TRUST_NAME": "Test Trust",
    "TRUST_TYPE": "IRREVOCABLE",
    "GRANTOR_NAME": "Test Grantor",
    "GOVERNING_STATE": "DE",
    "FISCAL_YEAR_END_MONTH": 12,
    "DISTRIBUTION_STANDARD": "DISCRETIONARY",
    "DOC_SUMMARY": "instrument summary",
    "BENEFICIARY_CLASS": "INCOME",
    "SHARE_BPS": 10000,
    "DATE_OF_BIRTH": "1955-01-01",
    "TERM_START": "2026-01-01",
    "TERM_END": "2028-12-31",
    "ALLOCATION_SOURCE": "INCOME_ONLY",
    "PURPOSE_CATEGORY": "OTHER",
    "IPS_EFFECTIVE_FROM": "2026-08-01",
    "IPS_EFFECTIVE_TO": "2027-08-01",
    "EQUITY_TARGET_PCT": 60.00,
    "EQUITY_BAND_PCT": 5.00,
    "FIXED_INCOME_TARGET_PCT": 30.00,
    "FIXED_INCOME_BAND_PCT": 5.00,
    "ASSET_CLASS": "EQUITY",
    "VALUE_DATE": "2026-08-05",
    "PERIOD_START": "2026-07-01",
    "PERIOD_END": "2026-09-30",
    "FEE_VARIANT": "FINAL",
    "FISCAL_YEAR": 2026,
    "TAX_YEAR": 2026,
}

_ein_counter = [0]


def _next_ein() -> str:
    _ein_counter[0] += 1
    return f"04-{_ein_counter[0]:07d}"


def create_trust_payload(**overrides) -> dict:
    defaults = {
        "trust_name": DEFAULTS["TRUST_NAME"],
        "trust_type": DEFAULTS["TRUST_TYPE"],
        "grantor_name": DEFAULTS["GRANTOR_NAME"],
        "governing_state": DEFAULTS["GOVERNING_STATE"],
        "ein": _next_ein(),
        "fiscal_year_end_month": DEFAULTS["FISCAL_YEAR_END_MONTH"],
        "distribution_standard": DEFAULTS["DISTRIBUTION_STANDARD"],
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    defaults = {
        "version_number": 1,
        "summary": DEFAULTS["DOC_SUMMARY"],
    }
    defaults.update(overrides)
    return defaults


def create_beneficiary_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Beneficiary",
        "beneficiary_class": DEFAULTS["BENEFICIARY_CLASS"],
        "share_bps": DEFAULTS["SHARE_BPS"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
    }
    defaults.update(overrides)
    return defaults


def create_committee_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Committee Member",
        "term_start": DEFAULTS["TERM_START"],
        "term_end": DEFAULTS["TERM_END"],
    }
    defaults.update(overrides)
    return defaults


def create_distribution_request_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 100000,
        "allocation_source": DEFAULTS["ALLOCATION_SOURCE"],
        "purpose_category": DEFAULTS["PURPOSE_CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def create_ips_payload(**overrides) -> dict:
    defaults = {
        "effective_from": DEFAULTS["IPS_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["IPS_EFFECTIVE_TO"],
        "equity_target_pct": DEFAULTS["EQUITY_TARGET_PCT"],
        "equity_band_pct": DEFAULTS["EQUITY_BAND_PCT"],
        "fixed_income_target_pct": DEFAULTS["FIXED_INCOME_TARGET_PCT"],
        "fixed_income_band_pct": DEFAULTS["FIXED_INCOME_BAND_PCT"],
        "alternatives_allowed": False,
    }
    defaults.update(overrides)
    return defaults


def create_holding_payload(**overrides) -> dict:
    defaults = {
        "asset_class": DEFAULTS["ASSET_CLASS"],
        "ticker": "AAA",
        "units": 1000,
        "unit_price_cents": 25000,
    }
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(**overrides) -> dict:
    defaults = {
        "entry_kind": "RECEIPT",
        "receipt_type": "INTEREST",
        "amount_cents": 100000,
        "value_date": DEFAULTS["VALUE_DATE"],
        "description": "test entry",
    }
    defaults.update(overrides)
    return defaults


def create_fee_assessment_payload(**overrides) -> dict:
    defaults = {
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "variant": DEFAULTS["FEE_VARIANT"],
    }
    defaults.update(overrides)
    return defaults


def create_annual_statement_payload(**overrides) -> dict:
    defaults = {
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_tax_filing_payload(**overrides) -> dict:
    defaults = {
        "tax_year": DEFAULTS["TAX_YEAR"],
    }
    defaults.update(overrides)
    return defaults
