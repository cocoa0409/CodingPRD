"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_account_counter = itertools.count(1)
_sku_counter = itertools.count(1)
_serial_counter = itertools.count(1)  # cylinders and machines share one pool
_attendee_counter = itertools.count(1)


def next_account_no(prefix="ACC"):
    """Unique branch account numbers (duplicate account_no is rejected)."""
    return f"{prefix}-{next(_account_counter):05d}"


def next_sku(prefix="SKU"):
    """Unique SKUs (duplicate sku is rejected)."""
    return f"{prefix}-{next(_sku_counter):05d}"


def next_serial(prefix="SN"):
    """Unique serials across cylinders and machines (one uniqueness pool)."""
    return f"{prefix}-{next(_serial_counter):05d}"


def next_attendee_name(prefix="Attendee"):
    return f"{prefix} {next(_attendee_counter):05d}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "account_no": next_account_no(),
        "name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_price_book_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Book",
        "scope": "RETAIL",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
        "default_discount_pct": 0.10,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": next_sku(),
        "name": "Test Product",
        "category": "HARDGOOD",
        "retail_price_cents": TEST_DEFAULTS["HARDGOOD_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_cylinder_asset_payload(**overrides) -> dict:
    defaults = {
        "serial_no": next_serial("CYL"),
        "gas_grade": "ARGON",
        "size": "MEDIUM",
    }
    defaults.update(overrides)
    return defaults


def create_machine_payload(**overrides) -> dict:
    defaults = {
        "model": "Miller 252",
        "serial_no": next_serial("M"),
        "daily_rate_cents": TEST_DEFAULTS["MACHINE_DAILY_CENTS"],
        "weekly_rate_cents": TEST_DEFAULTS["MACHINE_WEEKLY_CENTS"],
        "monthly_rate_cents": TEST_DEFAULTS["MACHINE_MONTHLY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rental_agreement_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "item_type": "CYLINDER",
        "rate_plan": "DEMURRAGE",
        "start_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_delivery_route_payload(**overrides) -> dict:
    defaults = {
        "route_date": "2026-08-02",
        "truck_capacity_units": TEST_DEFAULTS["ROUTE_CAPACITY_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, lines, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "order_type": "RETAIL",
        "fulfillment": "WILL_CALL",
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_training_class_payload(**overrides) -> dict:
    defaults = {
        "title": "Oxy-Fuel Safety",
        "room": "ROOM_A",
        "start_at": "2026-09-01T09:00:00Z",
        "end_at": "2026-09-01T11:00:00Z",
        "capacity": 5,
        "price_cents": TEST_DEFAULTS["CLASS_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(class_id, customer_id, **overrides) -> dict:
    defaults = {
        "class_id": class_id,
        "customer_id": customer_id,
        "attendee_name": next_attendee_name(),
    }
    defaults.update(overrides)
    return defaults


def create_repair_ticket_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "machine_desc": "Miller 252 (customer-owned)",
        "issue_desc": "Wire feed erratic",
    }
    defaults.update(overrides)
    return defaults
