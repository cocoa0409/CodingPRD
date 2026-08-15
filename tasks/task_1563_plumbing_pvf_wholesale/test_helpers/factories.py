"""Payload factories — one per creatable resource, input fields only (PRD §3–§4)."""
from .constants import TEST_DEFAULTS


def create_branch_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["BRANCH_NAME"],
        "code": TEST_DEFAULTS["BRANCH_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": TEST_DEFAULTS["SKU"],
        "description": "PVC pipe",
        "category": "PIPE",
        "list_price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"],
        "cost_cents": TEST_DEFAULTS["COST_CENTS"],
        "manufacturer_name": TEST_DEFAULTS["MANUFACTURER"],
        "cubes_per_unit": TEST_DEFAULTS["CUBES_PER_UNIT"],
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {
        "company_name": TEST_DEFAULTS["COMPANY_NAME"],
        "pricing_tier": TEST_DEFAULTS["PRICING_TIER"],
        "terms": TEST_DEFAULTS["TERMS"],
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_stock_record_payload(product_id: str, **overrides) -> dict:
    defaults = {"product_id": product_id, "initial_on_hand": 0}
    defaults.update(overrides)
    return defaults


def create_stock_receipt_payload(lines: list) -> dict:
    return {"lines": lines}


def create_payment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "method": "ACH"}
    defaults.update(overrides)
    return defaults


def create_quote_payload(account_id: str, branch_id: str, lines: list, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "branch_id": branch_id,
        "job_name": "JOB-1",
        "valid_until": TEST_DEFAULTS["VALID_UNTIL"],
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_quote_revision_payload(expected_quote_version: int, **overrides) -> dict:
    defaults = {
        "expected_quote_version": expected_quote_version,
        "valid_until": TEST_DEFAULTS["VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_sheet_payload(account_id: str, branch_id: str, selections: list, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "branch_id": branch_id,
        "customer_name": "Homeowner H",
        "selections": selections,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(account_id: str, branch_id: str, **overrides) -> dict:
    defaults = {"account_id": account_id, "branch_id": branch_id}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id: str, qty: int, **overrides) -> dict:
    defaults = {"product_id": product_id, "qty": qty}
    defaults.update(overrides)
    return defaults


def create_kit_payload(order_line_ids: list, **overrides) -> dict:
    defaults = {"floor_label": "F1", "order_line_ids": order_line_ids}
    defaults.update(overrides)
    return defaults


def create_stage_kit_payload(**overrides) -> dict:
    defaults = {
        "staging_bin": "B1",
        "window_start": "2026-08-02T08:00:00Z",
        "window_end": "2026-08-02T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_delivery_slot_payload(**overrides) -> dict:
    defaults = {
        "truck_label": "T1",
        "window_start": TEST_DEFAULTS["SLOT_WINDOW_START"],
        "window_end": TEST_DEFAULTS["SLOT_WINDOW_END"],
        "capacity_cubes": 100,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(slot_id: str, expected_order_version: int) -> dict:
    return {"slot_id": slot_id, "expected_order_version": expected_order_version}


def create_program_payload(**overrides) -> dict:
    defaults = {
        "manufacturer_name": TEST_DEFAULTS["MANUFACTURER"],
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-06-30T00:00:00Z",
        "tiers": [{"threshold_cents": 100000, "rebate_pct": 1}],
        "committed_stock_value_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(order_id: str, lines: list, **overrides) -> dict:
    defaults = {"order_id": order_id, "reason": "job surplus", "lines": lines}
    defaults.update(overrides)
    return defaults
