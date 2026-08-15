"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from uuid import uuid4

from .constants import DEFAULT_PICKUP_SLOT, DEFAULT_ROUTE_DATE


def _tag() -> str:
    return uuid4().hex[:8].upper()


def create_branch_payload(**overrides) -> dict:
    defaults = {
        "branch_code": f"BR-{_tag()}",
        "hazmat_storage_certified": True,
        "peak_season_start": "04-01",
        "peak_season_end": "09-30",
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {
        "account_number": f"ACCT-{_tag()}",
        "account_type": "DEALER",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": f"SKU-{_tag()}",
        "product_family": "PARTS",
        "base_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_stock_lot_payload(branch_id, product_id, **overrides) -> dict:
    defaults = {
        "branch_id": branch_id,
        "product_id": product_id,
        "lot_code": f"LOT-{_tag()}",
        "qty_on_hand": 10,
    }
    defaults.update(overrides)
    return defaults


def create_seasonal_program_payload(branch_id, **overrides) -> dict:
    defaults = {
        "branch_id": branch_id,
        "program_name": f"Early-Buy {_tag()}",
        "order_window_start": "2026-01-01T00:00:00Z",
        "order_window_end": "2026-02-15T00:00:00Z",
        "ship_window_start": "2026-03-01T00:00:00Z",
        "ship_window_end": "2026-05-31T00:00:00Z",
        "early_buy_discount_pct": 10,
        "pool_cap_units": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_seasonal_commitment_payload(
    program_id, account_id, committed_units, expected_program_version, **overrides
) -> dict:
    defaults = {
        "program_id": program_id,
        "account_id": account_id,
        "committed_units": committed_units,
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def order_line(product_id, qty) -> dict:
    return {"product_id": product_id, "qty": qty}


def create_order_payload(branch_id, account_id, channel="WILL_CALL", lines=None, **overrides) -> dict:
    defaults = {
        "branch_id": branch_id,
        "account_id": account_id,
        "channel": channel,
        "lines": lines if lines is not None else [],
    }
    if channel == "WILL_CALL":
        defaults["requested_pickup_slot"] = DEFAULT_PICKUP_SLOT
    else:
        defaults["route_date"] = DEFAULT_ROUTE_DATE
    defaults.update(overrides)
    return defaults


def create_service_center_payload(**overrides) -> dict:
    defaults = {
        "center_name": f"Center {_tag()}",
        "region_code": "SW",
        "authorized_brands": ["AquaFlow"],
        "labor_rate_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(account_id, product_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "product_id": product_id,
        "serial_number": f"SN-{_tag()}",
        "brand": "AquaFlow",
        "purchase_date": "2026-01-01",
        "failure_description": "unit failure under normal use",
    }
    defaults.update(overrides)
    return defaults


def create_rma_payload(account_id, order_id, product_id, lot_id, qty, reason, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "order_id": order_id,
        "product_id": product_id,
        "lot_id": lot_id,
        "qty": qty,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults
