"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_vendor_payload(**overrides) -> dict:
    """Vendor: legal_name + payment_method required; the rest optional (PRD §3.1)."""
    defaults = {
        "legal_name": "Test Vendor",
        "payment_method": "ACH",
    }
    defaults.update(overrides)
    return defaults


def create_gl_account_payload(**overrides) -> dict:
    """GL account: code + name required; is_postable defaults true (PRD §3.1)."""
    defaults = {
        "code": "5000",
        "name": "COGS",
        "is_postable": True,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(vendor_id, **overrides) -> dict:
    """Purchase order (PRD §3.1)."""
    defaults = {
        "vendor_id": vendor_id,
        "gl_account_code": "5000",
        "ordered_amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_goods_receipt_payload(po_id, **overrides) -> dict:
    """Goods receipt (PRD §3.2). coverage_days optional (defaults 1)."""
    defaults = {
        "po_id": po_id,
        "received_amount_cents": 100000,
        "received_date": "2026-05-01",
        "coverage_days": 5,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(vendor_id, **overrides) -> dict:
    """Invoice capture (PRD §3.3). po_id and ocr_confidence optional."""
    defaults = {
        "vendor_id": vendor_id,
        "invoice_number": "INV-1",
        "invoice_date": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_line_payload(**overrides) -> dict:
    """Invoice coding line (PRD §3.3). description optional."""
    defaults = {
        "gl_account_code": "5000",
        "amount_cents": 50000,
        "description": "line",
    }
    defaults.update(overrides)
    return defaults


def create_approval_route_payload(**overrides) -> dict:
    """Approval route tier (PRD §3.1)."""
    defaults = {
        "min_amount_cents": 0,
        "max_amount_cents": 1_000_000_000,
        "required_levels": 1,
    }
    defaults.update(overrides)
    return defaults


def create_payment_batch_payload(**overrides) -> dict:
    """Payment batch (PRD §3.6)."""
    defaults = {
        "payment_method": "ACH",
        "run_date": "2026-05-10",
    }
    defaults.update(overrides)
    return defaults


def add_payment_payload(invoice_id, **overrides) -> dict:
    """Add an approved invoice to a batch (PRD §3.6)."""
    defaults = {"invoice_id": invoice_id}
    defaults.update(overrides)
    return defaults


def release_batch_payload(expected_version, **overrides) -> dict:
    """Release a batch with the OCC version field (PRD §2.9, §3.6)."""
    defaults = {"expected_paymentbatch_version": expected_version}
    defaults.update(overrides)
    return defaults


def create_accrual_payload(po_id, **overrides) -> dict:
    """Period-end accrual (PRD §3.8)."""
    defaults = {
        "po_id": po_id,
        "period_label": "2026-05",
        "period_start": "2026-05-01",
        "period_end": "2026-05-31",
    }
    defaults.update(overrides)
    return defaults


def hold_vendor_payload(on_hold: bool) -> dict:
    """Place/release a vendor hold (PRD §3.1)."""
    return {"on_hold": on_hold}
