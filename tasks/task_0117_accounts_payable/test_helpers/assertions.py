"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system fields for full first-class entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def _assert_lightweight(data: dict):
    """Lightweight records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "lightweight record must not carry updated_at"
    assert "version" not in data, "lightweight record must not carry version"


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["payment_method"] in ("ACH", "CHECK", "CARD")
    assert data["status"] in ("ACTIVE", "ON_HOLD")
    assert isinstance(data["is_1099"], bool)
    assert isinstance(data["ytd_1099_paid_cents"], int)
    assert isinstance(data["net_terms_days"], int)


def assert_gl_account(data: dict):
    _assert_lightweight(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["is_postable"], bool)


def assert_purchase_order(data: dict):
    _assert_common(data)
    assert isinstance(data["ordered_amount_cents"], int)
    assert isinstance(data["received_amount_cents"], int)
    assert isinstance(data["matched_amount_cents"], int)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_goods_receipt(data: dict):
    _assert_common(data)
    assert isinstance(data["received_amount_cents"], int)
    assert data["status"] in ("DRAFT", "POSTED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["invoice_number"], str) and len(data["invoice_number"]) > 0
    assert isinstance(data["total_amount_cents"], int)
    assert isinstance(data["variance_cents"], int)
    assert data["status"] in (
        "CAPTURED", "CODING_REVIEW", "MATCHED", "PENDING_APPROVAL",
        "APPROVED", "SCHEDULED", "PAID", "REJECTED",
    )


def assert_invoice_line(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["gl_account_code"], str)


def assert_match_exception(data: dict):
    _assert_common(data)
    assert data["reason"] in ("PRICE_VARIANCE", "QTY_VARIANCE")
    assert data["resolution"] in ("PENDING", "RESOLVED", "WRITTEN_OFF", "ESCALATED")
    assert isinstance(data["variance_cents"], int)


def assert_approval_route(data: dict):
    _assert_lightweight(data)
    assert isinstance(data["min_amount_cents"], int)
    assert isinstance(data["max_amount_cents"], int)
    assert isinstance(data["required_levels"], int) and data["required_levels"] >= 1


def assert_approval_step(data: dict):
    _assert_common(data)
    assert isinstance(data["level"], int) and data["level"] >= 1
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")


def assert_payment_batch(data: dict):
    _assert_common(data)
    assert data["payment_method"] in ("ACH", "CHECK", "CARD")
    assert isinstance(data["total_disbursed_cents"], int)
    assert data["status"] in ("BUILDING", "RELEASED", "SETTLED", "VOID")


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["discount_taken_cents"], int)
    assert isinstance(data["net_amount_cents"], int)
    assert data["settlement_status"] in ("PENDING", "SETTLED", "RETURNED")
    # net = gross - discount (PRD §3.7).
    assert data["net_amount_cents"] == data["gross_amount_cents"] - data["discount_taken_cents"], (
        "net_amount_cents must equal gross_amount_cents - discount_taken_cents"
    )


def assert_accrual(data: dict):
    _assert_common(data)
    assert isinstance(data["estimated_cents"], int)
    assert isinstance(data["final_cents"], int)
    assert data["status"] in ("BOOKED", "REVERSED")


def assert_audit_event(data: dict):
    _assert_lightweight(data)
    assert isinstance(data["event_type"], str) and len(data["event_type"]) > 0
    assert isinstance(data["actor_user_id"], str)
