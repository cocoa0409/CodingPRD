"""Payload factories — input fields only (PRD §3 creation payloads)."""

DEFAULTS = {
    "LEGAL_NAME": "Test REIT Trust",
    "CHARTER_LIMIT_PCT": 9.8,
    "TAXABLE_YEAR_START": "2026-01-01",
    "TAXABLE_YEAR": 2026,
    "ASSET_NAME": "Test Asset",
    "ASSET_CLASS": "REAL_ESTATE",
    "ACQUISITION_DATE": "2024-01-01",
    "ASSET_VALUE_CENTS": 1_000_000,
    "QUARTER_LABEL": "2026-Q1",
    "QUARTER_START": "2026-01-01",
    "QUARTER_END": "2026-03-31",
    "INCOME_CLASS": "RENTS",
    "INCOME_AMOUNT_CENTS": 100_000,
    "ACCRUED_AT": "2026-02-01",
    "SNAPSHOT_DATE": "2026-06-30",
    "TOTAL_SHARES": 1000,
    "TAXABLE_INCOME_CENTS": 500_000,
    "NET_CAPITAL_GAIN_CENTS": 0,
    "DIVIDEND_AMOUNT_CENTS": 10_000,
    "DECLARATION_DATE": "2026-03-01",
    "RECORD_DATE": "2026-03-10",
    "PAYABLE_DATE": "2026-03-20",
    "EP_KIND": "TAXABLE_INCOME",
    "EP_AMOUNT_CENTS": 100_000,
    "EFFECTIVE_DATE": "2026-01-15",
    "SALE_PRICE_CENTS": 1_500_000,
    "BASIS_CENTS": 1_000_000,
    "SALE_DATE": "2026-06-01",
    "DISCLOSURE_TITLE": "Quarterly compliance disclosure",
    "DISCLOSURE_BODY": "Detail of the referenced compliance artifact.",
}

_ticker_seq = [0]


def next_ticker() -> str:
    """Unique four-letter tickers so parallel tests never trip PRD §2.10."""
    _ticker_seq[0] += 1
    return f"T{_ticker_seq[0]:04d}"[-4:] if _ticker_seq[0] < 26000 else f"Z{_ticker_seq[0]:05d}"[-4:]


def create_reit_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "ticker": next_ticker(),
        "charter_ownership_limit_pct": DEFAULTS["CHARTER_LIMIT_PCT"],
        "taxable_year_start": DEFAULTS["TAXABLE_YEAR_START"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_holding_payload(reit_id: str, **overrides) -> dict:
    defaults = {
        "reit_id": reit_id,
        "asset_name": DEFAULTS["ASSET_NAME"],
        "asset_class": DEFAULTS["ASSET_CLASS"],
        "held_by_trs": False,
        "is_dealer_inventory": False,
        "acquisition_date": DEFAULTS["ACQUISITION_DATE"],
        "value_cents": DEFAULTS["ASSET_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_quarter_payload(reit_id: str, **overrides) -> dict:
    defaults = {
        "reit_id": reit_id,
        "label": DEFAULTS["QUARTER_LABEL"],
        "period_start": DEFAULTS["QUARTER_START"],
        "period_end": DEFAULTS["QUARTER_END"],
    }
    defaults.update(overrides)
    return defaults


def create_income_item_payload(reit_id: str, quarter_id: str, **overrides) -> dict:
    defaults = {
        "reit_id": reit_id,
        "quarter_id": quarter_id,
        "income_class": DEFAULTS["INCOME_CLASS"],
        "amount_cents": DEFAULTS["INCOME_AMOUNT_CENTS"],
        "source_is_trs": False,
        "accrued_at": DEFAULTS["ACCRUED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_test_report_payload(reit_id: str, quarter_id: str) -> dict:
    return {"reit_id": reit_id, "quarter_id": quarter_id}


def create_income_test_report_payload(reit_id: str, quarter_id: str) -> dict:
    return {"reit_id": reit_id, "quarter_id": quarter_id}


def create_shareholder_payload(reit_id: str, display_name: str,
                               holder_type: str = "INDIVIDUAL",
                               **overrides) -> dict:
    defaults = {
        "reit_id": reit_id,
        "display_name": display_name,
        "holder_type": holder_type,
    }
    defaults.update(overrides)
    return defaults


def create_shareholder_snapshot_payload(reit_id: str, **overrides) -> dict:
    defaults = {
        "reit_id": reit_id,
        "snapshot_date": DEFAULTS["SNAPSHOT_DATE"],
        "total_shares_outstanding": DEFAULTS["TOTAL_SHARES"],
    }
    defaults.update(overrides)
    return defaults


def create_shareholder_position_payload(snapshot_id: str, shareholder_id: str,
                                        shares_held: int) -> dict:
    return {
        "snapshot_id": snapshot_id,
        "shareholder_id": shareholder_id,
        "shares_held": shares_held,
    }


def create_distribution_requirement_payload(reit_id: str, **overrides) -> dict:
    defaults = {
        "reit_id": reit_id,
        "taxable_year": DEFAULTS["TAXABLE_YEAR"],
        "taxable_income_cents": DEFAULTS["TAXABLE_INCOME_CENTS"],
        "net_capital_gain_cents": DEFAULTS["NET_CAPITAL_GAIN_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_dividend_declaration_payload(reit_id: str, expected_reit_version: int,
                                        **overrides) -> dict:
    defaults = {
        "reit_id": reit_id,
        "taxable_year": DEFAULTS["TAXABLE_YEAR"],
        "amount_cents": DEFAULTS["DIVIDEND_AMOUNT_CENTS"],
        "declaration_date": DEFAULTS["DECLARATION_DATE"],
        "record_date": DEFAULTS["RECORD_DATE"],
        "payable_date": DEFAULTS["PAYABLE_DATE"],
        "expected_reit_version": expected_reit_version,
    }
    defaults.update(overrides)
    return defaults


def create_ep_adjustment_payload(reit_id: str, quarter_id: str,
                                 expected_reit_version: int,
                                 **overrides) -> dict:
    defaults = {
        "reit_id": reit_id,
        "quarter_id": quarter_id,
        "kind": DEFAULTS["EP_KIND"],
        "amount_cents": DEFAULTS["EP_AMOUNT_CENTS"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "expected_reit_version": expected_reit_version,
    }
    defaults.update(overrides)
    return defaults


def create_asset_sale_payload(reit_id: str, asset_holding_id: str,
                              **overrides) -> dict:
    defaults = {
        "reit_id": reit_id,
        "asset_holding_id": asset_holding_id,
        "sale_price_cents": DEFAULTS["SALE_PRICE_CENTS"],
        "basis_cents": DEFAULTS["BASIS_CENTS"],
        "sale_date": DEFAULTS["SALE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_compliance_disclosure_payload(reit_id: str, disclosure_type: str,
                                         reference_id: str, **overrides) -> dict:
    defaults = {
        "reit_id": reit_id,
        "disclosure_type": disclosure_type,
        "reference_id": reference_id,
        "title": DEFAULTS["DISCLOSURE_TITLE"],
        "body": DEFAULTS["DISCLOSURE_BODY"],
    }
    defaults.update(overrides)
    return defaults
