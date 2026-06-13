"""Payload factories — one per entity, input fields only (PRD §3)."""

from .constants import TEST_DEFAULTS


def create_spend_category_payload(**overrides) -> dict:
    """PRD §2.9, §3.1. name, code, approval/director thresholds, optional preferred_vendor_id."""
    defaults = {
        "name": "Office Supplies",
        "code": "OFFICE",
        "approval_threshold_cents": TEST_DEFAULTS["HIGH_APPROVAL_THRESHOLD"],
        "director_threshold_cents": TEST_DEFAULTS["HIGH_DIRECTOR_THRESHOLD"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    """PRD §2.9, §3. name, tax_id, optional grace_days."""
    defaults = {
        "name": "Acme Vendor",
        "tax_id": "TAX-DEFAULT",
    }
    defaults.update(overrides)
    return defaults


def create_requisition_payload(spend_category_id, lines=None, **overrides) -> dict:
    """PRD §3.1. spend_category_id, title, lines [{sku, description, quantity, estimated_unit_price_cents}]."""
    defaults = {
        "spend_category_id": spend_category_id,
        "title": "Test Requisition",
        "lines": lines if lines is not None else [
            {"sku": "A", "description": "Item A", "quantity": 1, "estimated_unit_price_cents": 1000},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_rfq_payload(requisition_id, open_at, close_at, **overrides) -> dict:
    """PRD §3.2. requisition_id, open_at, close_at."""
    defaults = {
        "requisition_id": requisition_id,
        "open_at": open_at,
        "close_at": close_at,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(rfq_id, vendor_id, submitted_at, unit_prices=None, **overrides) -> dict:
    """PRD §3.2. rfq_id, vendor_id, submitted_at, unit_prices [{sku, unit_price_cents, promised_lead_days}]."""
    defaults = {
        "rfq_id": rfq_id,
        "vendor_id": vendor_id,
        "submitted_at": submitted_at,
        "unit_prices": unit_prices if unit_prices is not None else [
            {"sku": "A", "unit_price_cents": 1000, "promised_lead_days": 5},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_standard_po_payload(vendor_id, spend_category_id, requisition_id, source_quote_id, **overrides) -> dict:
    """PRD §3.3. STANDARD PO from an approved requisition + awarded quote."""
    defaults = {
        "vendor_id": vendor_id,
        "spend_category_id": spend_category_id,
        "po_type": "STANDARD",
        "requisition_id": requisition_id,
        "source_quote_id": source_quote_id,
    }
    defaults.update(overrides)
    return defaults


def create_blanket_po_payload(vendor_id, spend_category_id, ceiling_amount_cents,
                              valid_from, valid_to, **overrides) -> dict:
    """PRD §3.3. BLANKET PO carrying ceiling + validity interval."""
    defaults = {
        "vendor_id": vendor_id,
        "spend_category_id": spend_category_id,
        "po_type": "BLANKET",
        "ceiling_amount_cents": ceiling_amount_cents,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }
    defaults.update(overrides)
    return defaults


def create_release_order_payload(blanket_po_id, amount_cents, expected_purchase_order_version,
                                 lines=None, **overrides) -> dict:
    """PRD §3.4. blanket_po_id, amount_cents, lines, expected_purchase_order_version (OCC)."""
    defaults = {
        "blanket_po_id": blanket_po_id,
        "amount_cents": amount_cents,
        "lines": lines if lines is not None else [
            {"sku": "A", "quantity": 1, "unit_price_cents": amount_cents},
        ],
        "expected_purchase_order_version": expected_purchase_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_goods_receipt_payload(purchase_order_id, received_lines, received_at, **overrides) -> dict:
    """PRD §3.5. purchase_order_id, optional release_order_id, received_lines, received_at."""
    defaults = {
        "purchase_order_id": purchase_order_id,
        "received_lines": received_lines,
        "received_at": received_at,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(vendor_id, purchase_order_id, goods_receipt_id,
                           invoice_number, lines=None, **overrides) -> dict:
    """PRD §3.6. vendor_id, purchase_order_id, goods_receipt_id, invoice_number, lines."""
    defaults = {
        "vendor_id": vendor_id,
        "purchase_order_id": purchase_order_id,
        "goods_receipt_id": goods_receipt_id,
        "invoice_number": invoice_number,
        "lines": lines if lines is not None else [
            {"sku": "A", "billed_qty": 1, "billed_unit_price_cents": 1000},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_scorecard_payload(vendor_id, period_start, period_end, **overrides) -> dict:
    """PRD §3.8. vendor_id, period_start, period_end, optional on_time_variant."""
    defaults = {
        "vendor_id": vendor_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults
