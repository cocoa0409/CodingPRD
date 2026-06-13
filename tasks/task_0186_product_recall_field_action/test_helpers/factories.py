"""Payload factories — one per entity, input fields only.

Only fields the client supplies are included; computed/system fields
(classification, status, affected, refund_amount_cents, version, ...) are
never sent. Defaults are chosen to satisfy PRD body-validation rules.
"""
import itertools

_sku_counter = itertools.count(1)
_lot_counter = itertools.count(1)


def unique_sku(prefix="SKU") -> str:
    return f"{prefix}-{next(_sku_counter)}"


def unique_lot_code(prefix="LOT") -> str:
    return f"{prefix}-{next(_lot_counter)}"


def create_product_payload(**overrides) -> dict:
    """POST /products — sku, name, regulator, unit_list_price_cents."""
    defaults = {
        "sku": unique_sku(),
        "name": "Test Product",
        "regulator": "FDA",
        "unit_list_price_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(product_id, **overrides) -> dict:
    """POST /lots — product_id, lot_code, serial_start, serial_end."""
    defaults = {
        "product_id": product_id,
        "lot_code": unique_lot_code(),
        "serial_start": 1,
        "serial_end": 100,
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(lot_id, customer_id, **overrides) -> dict:
    """POST /units — lot_id, serial_number, customer_id, sale_price_cents."""
    defaults = {
        "lot_id": lot_id,
        "serial_number": 1,
        "customer_id": customer_id,
        "sale_price_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """POST /customers — name, contact_channel, contact_address, reachable?."""
    defaults = {
        "name": "Test Customer",
        "contact_channel": "EMAIL",
        "contact_address": "test@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(product_id, **overrides) -> dict:
    """POST /recalls — product_id, reason, hazard_severity, injury_reported?,
    serial_filter_start?, serial_filter_end?."""
    defaults = {
        "product_id": product_id,
        "reason": "hazard",
        "hazard_severity": "SERIOUS",
        "injury_reported": False,
    }
    defaults.update(overrides)
    return defaults


def add_affected_lot_payload(lot_id, expected_recall_version, **overrides) -> dict:
    """POST /recalls/{id}/affected-lots — lot_id, expected_recall_version."""
    defaults = {
        "lot_id": lot_id,
        "expected_recall_version": expected_recall_version,
    }
    defaults.update(overrides)
    return defaults


def create_disposition_payload(recall_id, unit_id, expected_recall_version, **overrides) -> dict:
    """POST /dispositions — recall_id, unit_id, disposition_type,
    refund_basis?, expected_recall_version."""
    defaults = {
        "recall_id": recall_id,
        "unit_id": unit_id,
        "disposition_type": "RETURN",
        "expected_recall_version": expected_recall_version,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(recall_id, **overrides) -> dict:
    """POST /regulatory-reports — recall_id, report_kind."""
    defaults = {
        "recall_id": recall_id,
        "report_kind": "INITIAL",
    }
    defaults.update(overrides)
    return defaults


def create_effectiveness_check_payload(recall_id, **overrides) -> dict:
    """POST /effectiveness-checks — recall_id."""
    defaults = {"recall_id": recall_id}
    defaults.update(overrides)
    return defaults
