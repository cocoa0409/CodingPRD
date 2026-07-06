"""Entity assertions."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_customer(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["phone"], str)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["cumulative_deposits_paid_cents"], int)
    assert data["credit_balance_cents"] >= 0
    assert data["cumulative_deposits_paid_cents"] >= 0


def assert_designer(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["active"], bool)


def assert_paper_stock(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["lead_days"], int) and data["lead_days"] >= 0
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert isinstance(data["reserved_units"], int) and data["reserved_units"] >= 0


def assert_finish_option(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["surcharge_cents"], int) and data["surcharge_cents"] >= 0
    assert isinstance(data["additional_lead_days"], int) and data["additional_lead_days"] >= 0
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_event_package(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["package_type"] in ("WEDDING", "ANNOUNCEMENT", "CUSTOM")
    assert 0.0 < float(data["deposit_pct"]) <= 1.0
    assert isinstance(data["min_qty"], int) and data["min_qty"] >= 1
    assert isinstance(data["proof_expiry_days"], int) and data["proof_expiry_days"] >= 1
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_design(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["event_package_id"])
    assert is_valid_uuid(data["paper_stock_id"])
    assert is_valid_uuid(data["finish_option_id"])
    assert data["status"] in ("DRAFT", "PROOFING", "APPROVED", "ARCHIVED")


def assert_proof(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "EXPIRED", "CANCELLED")
    assert isinstance(data["current_revision_number"], int) and data["current_revision_number"] >= 0
    assert isinstance(data["revision_fee_cents"], int) and data["revision_fee_cents"] >= 0


def assert_order(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in (
        "CART", "DEPOSIT_PENDING", "IN_PRODUCTION", "READY_TO_SHIP",
        "SHIPPED", "DELIVERED", "CANCELLED",
    )
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["deposit_due_cents"], int) and data["deposit_due_cents"] >= 0
    assert isinstance(data["deposit_paid_cents"], int) and data["deposit_paid_cents"] >= 0


def assert_line_item(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["captured_base_price_cents"], int)
    assert isinstance(data["captured_finish_surcharge_cents"], int)
    assert isinstance(data["line_price_cents"], int) and data["line_price_cents"] >= 0


def assert_addressing_job(data: dict) -> None:
    _assert_common(data)
    assert data["job_type"] in ("ADDRESSING", "ASSEMBLY")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_work_order(data: dict) -> None:
    _assert_common(data)
    assert data["production_status"] in ("NOT_STARTED", "PRINTING", "FINISHING", "COMPLETED")
    assert data["addressing_status"] in ("NOT_APPLICABLE", "PENDING", "IN_PROGRESS", "COMPLETED")


def assert_shipment(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("PREPARING", "DISPATCHED", "DELIVERED", "CANCELLED")
