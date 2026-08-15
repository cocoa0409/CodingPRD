"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def requisition_line(**overrides) -> dict:
    defaults = {
        "commodity_code": "GEN",
        "description": "generic line",
        "quantity": 1,
        "unit_price_cents": 100000,
        "cost_category": "SUPPLIES",
    }
    defaults.update(overrides)
    return defaults


def create_department_payload(**overrides) -> dict:
    defaults = {
        "name": _seq("Dept"),
        "cost_center": _seq("CC"),
        "diversity_goal_pct": TEST_DEFAULTS["DIVERSITY_GOAL_PCT"],
        "sustainability_goal_pct": TEST_DEFAULTS["SUSTAINABILITY_GOAL_PCT"],
        "default_approval_limit_cents": TEST_DEFAULTS["DEPARTMENT_APPROVAL_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {"legal_name": _seq("Vendor")}
    defaults.update(overrides)
    return defaults


def create_grant_payload(**overrides) -> dict:
    defaults = {
        "grant_code": _seq("G"),
        "sponsor": "Test Sponsor",
        "total_award_cents": 10000000,
        "f_and_a_rate": TEST_DEFAULTS["F_AND_A_RATE"],
        "allowed_categories": ["SUPPLIES", "EQUIPMENT"],
        "budget_start": TEST_DEFAULTS["GRANT_BUDGET_START"],
        "budget_end": TEST_DEFAULTS["GRANT_BUDGET_END"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "vendor_id": None,  # caller must supply
        "commodity_code": _seq("COMM"),
        "value_cents": 9000000,
        "effective_start": TEST_DEFAULTS["CONTRACT_EFFECTIVE_START"],
        "effective_end": TEST_DEFAULTS["CONTRACT_EFFECTIVE_END"],
        "terms_text": "standard terms",
    }
    defaults.update(overrides)
    return defaults


def create_requisition_payload(**overrides) -> dict:
    defaults = {
        "department_id": None,  # caller must supply
        "requester_id": TEST_DEFAULTS["REQUESTER_ID"],
        "lines": [requisition_line()],
    }
    defaults.update(overrides)
    return defaults


def create_solicitation_payload(**overrides) -> dict:
    defaults = {"response_deadline": "2026-08-08T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_quote_payload(**overrides) -> dict:
    defaults = {"vendor_id": None, "price_cents": 3000000}  # caller supplies vendor_id
    defaults.update(overrides)
    return defaults


def create_receipt_payload(**overrides) -> dict:
    defaults = {"lines": [{"line_no": 0, "quantity": 1}]}
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "invoice_number": _seq("INV"),
        "lines": [{"line_no": 0, "quantity": 1, "unit_price_cents": 100000}],
    }
    defaults.update(overrides)
    return defaults


def create_pcard_payload(**overrides) -> dict:
    defaults = {
        "department_id": None,  # caller must supply
        "cardholder_name": _seq("Cardholder"),
        "single_txn_limit_cents": TEST_DEFAULTS["CARD_SINGLE_TXN_LIMIT_CENTS"],
        "monthly_limit_cents": TEST_DEFAULTS["CARD_MONTHLY_LIMIT_CENTS"],
        "allowed_mccs": [],
    }
    defaults.update(overrides)
    return defaults


def create_elevation_payload(**overrides) -> dict:
    defaults = {
        "elevated_single_txn_limit_cents": 200000,
        "window_start": "2026-08-10T00:00:00Z",
        "window_end": "2026-08-12T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 10000,
        "entry_type": "DEBIT",
        "merchant_name": "Test Merchant",
        "mcc_code": "5942",
    }
    defaults.update(overrides)
    return defaults


def create_surplus_asset_payload(**overrides) -> dict:
    defaults = {
        "asset_tag": _seq("AST"),
        "department_id": None,  # caller must supply
        "description": "surplus item",
        "condition": "GOOD",
        "estimated_value_cents": 100000,
    }
    defaults.update(overrides)
    return defaults
