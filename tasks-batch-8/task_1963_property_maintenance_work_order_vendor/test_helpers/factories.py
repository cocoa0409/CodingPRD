"""Payload factories — one per entity/action, input fields only."""

from .constants import (
    DEFAULT_INSURANCE_VALID_UNTIL,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)


def create_property_payload(**overrides) -> dict:
    """Only `name` is mandatory; every policy field may be omitted (defaults apply)."""
    defaults = {"name": "Test Property"}
    defaults.update(overrides)
    return defaults


def create_resident_payload(**overrides) -> dict:
    defaults = {
        "property_id": None,
        "unit_number": "101",
        "full_name": "Resident One",
        "email": "resident@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "property_id": None,
        "full_name": "Tech One",
        "trade": "PLUMBING",
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "property_id": None,
        "company_name": "Vendor Co",
        "trade": "PLUMBING",
        "insurance_valid_until": DEFAULT_INSURANCE_VALID_UNTIL,
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    defaults = {
        "property_id": None,
        "sku": "SKU-1",
        "name": "Part",
        "unit_cost_cents": 100,
        "reorder_level": 0,
        "initial_stock": 0,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(**overrides) -> dict:
    defaults = {
        "property_id": None,
        "resident_id": None,
        "category": "PLUMBING",
        "priority": "ROUTINE",
        "description": "Test job",
    }
    defaults.update(overrides)
    return defaults


def dispatch_payload(**overrides) -> dict:
    """In-house dispatch by default; pass assignment_type='VENDOR' + vendor_id for vendor.
    Fields left at None (e.g. technician_id on a vendor dispatch) are omitted."""
    defaults = {
        "assignment_type": "IN_HOUSE",
        "technician_id": None,
        "scheduled_start_at": DEFAULT_WINDOW_START,
        "scheduled_end_at": DEFAULT_WINDOW_END,
        "entry_authorization": "RESIDENT_CONSENT",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def complete_payload(**overrides) -> dict:
    defaults = {
        "photo_urls": ["https://example.com/photo-1.jpg"],
        "damage_reported": False,
    }
    defaults.update(overrides)
    return defaults


def purchase_request_payload(**overrides) -> dict:
    defaults = {
        "part_id": None,
        "quantity": 1,
        "quoted_unit_cost_cents": 100,
        "shipping_fee_cents": 0,
        "expected_work_order_version": None,
    }
    defaults.update(overrides)
    return defaults


def chargeback_line(**overrides) -> dict:
    defaults = {
        "description": "Repair line",
        "quantity": 1,
        "unit_cost_cents": 1000,
        "resident_share_pct": 1.0,
    }
    defaults.update(overrides)
    return defaults
