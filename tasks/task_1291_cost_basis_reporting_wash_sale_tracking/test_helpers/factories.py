"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "LEGAL_NAME": "Test Brokerage Firm",
    "TAXPAYER_TIN": "TIN-000-1",
    "DISPLAY_NAME": "Test Customer",
    "ACCOUNT_NUMBER": "A1",
    "ACCOUNT_TYPE": "TAXABLE",
    "CUSIP": "123456789",
    "TICKER": "TST",
    "SECURITY_TYPE": "EQUITY",
    "COVERED_EFFECTIVE": "2011-01-01T00:00:00Z",
    "ACQ_DATE": "2025-01-05T00:00:00Z",
    "TRADE_DATE": "2025-06-10T00:00:00Z",
    "SETTLE_DATE": "2025-06-11T00:00:00Z",
    "TRANSFER_DATE": "2025-04-01T00:00:00Z",
    "EFFECTIVE_DATE": "2025-03-01T00:00:00Z",
}


def create_firm_payload(**overrides) -> dict:
    defaults = {"legal_name": DEFAULTS["LEGAL_NAME"]}
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "taxpayer_tin": DEFAULTS["TAXPAYER_TIN"],
        "display_name": DEFAULTS["DISPLAY_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {
        "account_number": DEFAULTS["ACCOUNT_NUMBER"],
        "account_type": DEFAULTS["ACCOUNT_TYPE"],
        "default_disposal_method": "FIFO",
    }
    defaults.update(overrides)
    return defaults


def create_security_payload(**overrides) -> dict:
    defaults = {
        "cusip": DEFAULTS["CUSIP"],
        "ticker": DEFAULTS["TICKER"],
        "security_type": DEFAULTS["SECURITY_TYPE"],
        "covered_security_effective_date": DEFAULTS["COVERED_EFFECTIVE"],
    }
    defaults.update(overrides)
    return defaults


def create_tax_lot_payload(**overrides) -> dict:
    defaults = {
        "security_id": None,
        "acquisition_date": DEFAULTS["ACQ_DATE"],
        "quantity": 10,
        "original_cost_basis_cents": 10000,
        "acquisition_kind": "PURCHASE",
    }
    defaults.update(overrides)
    return defaults


def create_disposition_payload(**overrides) -> dict:
    defaults = {
        "security_id": None,
        "trade_date": DEFAULTS["TRADE_DATE"],
        "settlement_date": DEFAULTS["SETTLE_DATE"],
        "quantity": 10,
        "proceeds_cents": 15000,
        "method": "FIFO",
    }
    defaults.update(overrides)
    return defaults


def create_corporate_action_payload(**overrides) -> dict:
    defaults = {
        "action_type": "SPLIT",
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_transfer_statement_payload(**overrides) -> dict:
    defaults = {
        "direction": "INBOUND",
        "counterparty_firm_name": "Other Broker",
        "security_id": None,
        "quantity": 10,
        "transfer_date": DEFAULTS["TRANSFER_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_tax_form_payload(**overrides) -> dict:
    defaults = {"tax_year": 2025}
    defaults.update(overrides)
    return defaults


def create_basis_change_request_payload(**overrides) -> dict:
    defaults = {
        "tax_lot_id": None,
        "request_kind": "BASIS_AMOUNT_CORRECTION",
        "proposed_basis_cents": 12000,
        "supporting_doc_ref": "DOC-1",
    }
    defaults.update(overrides)
    return defaults
