"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields on every versioned resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version is int >= 1"


def assert_spend_category(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["approval_threshold_cents"], int)
    assert isinstance(data["director_threshold_cents"], int)
    assert data["director_threshold_cents"] >= data["approval_threshold_cents"]
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["tax_id"], str) and len(data["tax_id"]) > 0
    assert isinstance(data["grace_days"], int) and data["grace_days"] >= 0
    assert isinstance(data["exception_count"], int) and data["exception_count"] >= 0
    assert data["status"] in ("APPROVED", "PROBATION", "BLOCKED")


def assert_requisition(data: dict):
    _assert_common(data)
    assert isinstance(data["requester_id"], str) and len(data["requester_id"]) > 0
    assert isinstance(data["spend_category_id"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in ("DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "CANCELLED")


def assert_approval_step(data: dict):
    _assert_common(data)
    assert isinstance(data["requisition_id"], str)
    assert data["level"] in (1, 2, 3)
    assert data["required_role"] in ("MANAGER", "DIRECTOR", "CFO")
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "SKIPPED")


def assert_rfq(data: dict):
    _assert_common(data)
    assert isinstance(data["requisition_id"], str)
    assert isinstance(data["round_index"], int) and data["round_index"] >= 0
    assert is_iso8601_timestamp(data["open_at"])
    assert is_iso8601_timestamp(data["close_at"])
    assert data["status"] in ("OPEN", "AWARDED", "CANCELLED", "CLOSED_NO_AWARD")


def assert_quote(data: dict):
    _assert_common(data)
    assert isinstance(data["rfq_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["quoted_total_cents"], int)
    assert data["status"] in ("SUBMITTED", "AWARDED", "VOIDED")


def assert_purchase_order(data: dict):
    _assert_common(data)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["spend_category_id"], str)
    assert data["po_type"] in ("STANDARD", "BLANKET")
    assert isinstance(data["total_amount_cents"], int)
    assert isinstance(data["is_maverick"], bool)
    assert data["status"] in ("ISSUED", "CLOSED", "CANCELLED")


def assert_release_order(data: dict):
    _assert_common(data)
    assert isinstance(data["blanket_po_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0
    assert data["status"] in ("OPEN", "RECEIVED", "CANCELLED")


def assert_goods_receipt(data: dict):
    _assert_common(data)
    assert isinstance(data["purchase_order_id"], str)
    assert isinstance(data["received_lines"], list) and len(data["received_lines"]) > 0
    assert is_iso8601_timestamp(data["received_at"])
    assert isinstance(data["posted_by_id"], str) and len(data["posted_by_id"]) > 0
    assert data["status"] in ("POSTED", "REVERSED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["purchase_order_id"], str)
    assert isinstance(data["goods_receipt_id"], str)
    assert isinstance(data["invoice_number"], str) and len(data["invoice_number"]) > 0
    assert isinstance(data["invoice_total_cents"], int)
    assert data["match_status"] in ("UNMATCHED", "MATCHED", "EXCEPTION")
    assert data["payment_status"] in ("PENDING", "APPROVED_FOR_PAY", "PAID", "REJECTED")


def assert_match_exception(data: dict):
    _assert_common(data)
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert data["reason"] in (
        "PRICE_OVER_TOLERANCE", "QTY_OVER_TOLERANCE",
        "AMOUNT_OVER_TOLERANCE", "NO_RECEIPT",
    )
    assert data["status"] in ("OPEN", "RESOLVED", "WAIVED")


def assert_vendor_scorecard(data: dict):
    _assert_common(data)
    assert isinstance(data["vendor_id"], str)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["on_time_variant"] in ("STRICT", "GRACE")
    for field in ("on_time_rate_pct", "price_compliance_pct", "exception_pct", "composite_score"):
        assert isinstance(data[field], int), f"{field} is an integer percent/score"
        assert 0 <= data[field] <= 100, f"{field} in range 0..100"
    assert data["status"] == "FINAL"


def assert_po_line_received_total(po: dict, sku: str, expected: int):
    """Assert the PO line for `sku` has the expected conserved received_total ledger value."""
    line = next((ln for ln in (po.get("lines") or []) if ln.get("sku") == sku), None)
    assert line is not None, f"PO has no line for sku={sku}"
    assert line["received_total"] == expected, (
        f"received_total for sku={sku} expected {expected}, got {line['received_total']}"
    )
