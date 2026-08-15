"""Payload factories — one per creatable entity, input fields only (PRD §3).

Computed/system fields (status, exposure figures, *_at stamps, *_by_user_id,
on_hand_qty, ...) are never sent by the client; only source:input fields
appear in these payloads.
"""
import itertools

from .constants import (
    DEFAULT_ETA,
    DEFAULT_ETD,
    DEFAULT_VALID_UNTIL,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)

# Unique-suffix counter so repeated fixture calls inside one test never
# collide on unique fields (sku, lot_code per item, imo_number).
_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


# --- ShipAgent (PRD §3.1) ---

def create_ship_agent_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "name": f"Agent {n}",
        "settlement_currency": "USD",
        "credit_limit_cents": 5000000,
        "payment_terms_days": 30,
    }
    defaults.update(overrides)
    return defaults


# --- VesselCall (PRD §3.1) ---

def create_vessel_call_payload(agent_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "vessel_name": f"MV Test-{n}",
        "imo_number": f"90{74760 + n}",
        "agent_id": agent_id,
        "port_code": "SGSIN",
        "scheduled_eta": DEFAULT_ETA,
        "scheduled_etd": DEFAULT_ETD,
        "foreign_going": False,
    }
    defaults.update(overrides)
    return defaults


# --- CatalogItem (PRD §3.1) ---

def create_catalog_item_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "sku": f"SKU-{n}",
        "name": f"Item {n}",
        "category": "PROVISIONS",
        "bonded_eligible": False,
        "requires_cold_chain": False,
        "base_price_cents": 120,
        "duty_rate_pct": 0,
    }
    defaults.update(overrides)
    return defaults


# --- StockLot (PRD §3.2) ---

def create_stock_lot_payload(catalog_item_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "catalog_item_id": catalog_item_id,
        "lot_code": f"LOT-{n}",
        "storage_tier": "DRY_STORE",
        "received_qty": 10000,
        "capacity_qty": 0,
    }
    defaults.update(overrides)
    return defaults


# --- Requisition (PRD §3.3) ---

def create_requisition_payload(catalog_item_id, requested_qty=100,
                               allows_substitution=False, **overrides) -> dict:
    # PRD §3.3: `allows_substitution` is a per-line field ("each line naming a
    # `catalog_item_id`, a `requested_qty` of at least 1, an
    # `allows_substitution` flag, and an optional `notes`") — it must live
    # inside the line dict, not at the payload top level.
    defaults = {
        "title": "Requisition",
        "lines": [
            {
                "catalog_item_id": catalog_item_id,
                "requested_qty": requested_qty,
                "allows_substitution": allows_substitution,
            }
        ],
    }
    defaults.update(overrides)
    return defaults


# --- Quotation (PRD §3.4) ---

def create_quotation_payload(catalog_item_id, qty=100, unit_price_cents=120, **overrides) -> dict:
    defaults = {
        "lines": [
            {
                "catalog_item_id": catalog_item_id,
                "qty": qty,
                "unit_price_cents": unit_price_cents,
                "is_substitution": False,
            }
        ],
        "valid_until": DEFAULT_VALID_UNTIL,
    }
    defaults.update(overrides)
    return defaults


def revise_quotation_payload(catalog_item_id, qty, unit_price_cents,
                             expected_quotation_version, **overrides) -> dict:
    defaults = {
        "lines": [
            {
                "catalog_item_id": catalog_item_id,
                "qty": qty,
                "unit_price_cents": unit_price_cents,
                "is_substitution": False,
            }
        ],
        "valid_until": DEFAULT_VALID_UNTIL,
        "expected_quotation_version": expected_quotation_version,
    }
    defaults.update(overrides)
    return defaults


# --- Delivery (PRD §3.6) ---

def create_delivery_payload(catalog_item_id, qty=100, **overrides) -> dict:
    defaults = {
        "window_start": DEFAULT_WINDOW_START,
        "window_end": DEFAULT_WINDOW_END,
        "lines": [{"catalog_item_id": catalog_item_id, "qty": qty}],
    }
    defaults.update(overrides)
    return defaults


def confirm_delivery_payload(catalog_item_id, qty, **overrides) -> dict:
    defaults = {
        "receiver_name": "Chief Cook",
        "signature_ref": f"sig-{_n()}",
        "confirmed_lines": [{"catalog_item_id": catalog_item_id, "qty": qty}],
    }
    defaults.update(overrides)
    return defaults


# --- Invoice & Payment (PRD §3.9, §3.10) ---

def create_invoice_payload(fx_rate_to_settlement=1.0, **overrides) -> dict:
    defaults = {"fx_rate_to_settlement": fx_rate_to_settlement}
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, currency="USD", **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "currency": currency}
    defaults.update(overrides)
    return defaults


# --- QualityComplaint (PRD §3.12) ---

def create_complaint_payload(catalog_item_id, rejected_qty, reason="DAMAGED", **overrides) -> dict:
    defaults = {
        "lines": [
            {
                "catalog_item_id": catalog_item_id,
                "rejected_qty": rejected_qty,
                "reason": reason,
            }
        ],
        "evidence_note": "evidence",
    }
    defaults.update(overrides)
    return defaults


# --- Stock adjustment (PRD §3.2) ---

def create_adjustment_payload(adjustment_qty, expected_stock_lot_version,
                              reason="cycle count", **overrides) -> dict:
    defaults = {
        "adjustment_qty": adjustment_qty,
        "reason": reason,
        "expected_stock_lot_version": expected_stock_lot_version,
    }
    defaults.update(overrides)
    return defaults
