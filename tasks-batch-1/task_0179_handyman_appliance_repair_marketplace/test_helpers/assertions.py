"""Entity assertions and domain invariant checkers.

Per-entity structural assertions validate the response shape against the PRD contract.
The invariant checkers encode money/derived-field reconciliation rules that must hold
after any operation.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_full(data: dict):
    """Entities that carry the full quartet of common fields (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_common_immutable(data: dict):
    """Configuration entities carrying only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_service_category(data: dict):
    """ServiceCategory is immutable config: id + created_at, no version/updated_at (PRD §2.4)."""
    _assert_common_immutable(data)
    assert "version" not in data, "ServiceCategory must not expose a version field"
    assert "updated_at" not in data, "ServiceCategory must not expose an updated_at field"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str)
    assert data["pricing_model"] in ("HOURLY", "FLAT")
    assert isinstance(data["requires_license"], bool)
    assert isinstance(data["instant_quote_eligible"], bool)
    assert isinstance(data["callback_warranty_days"], int)
    assert isinstance(data["skill_tags"], list)


def assert_customer(data: dict):
    _assert_common_full(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["zip_code"], str)
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0


def assert_pro(data: dict):
    _assert_common_full(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["home_zip_code"], str)
    assert isinstance(data["skill_tags"], list)
    assert data["background_check_status"] in ("PENDING", "CLEARED", "FLAGGED")
    assert data["license_status"] in ("NONE", "VERIFIED", "EXPIRED")
    assert isinstance(data["truck_stock_markup_pct"], (int, float))
    assert 0 <= data["truck_stock_markup_pct"] <= 1
    assert isinstance(data["completed_job_count"], int) and data["completed_job_count"] >= 0
    assert isinstance(data["callback_job_count"], int) and data["callback_job_count"] >= 0
    assert isinstance(data["callback_rate"], (int, float)) and data["callback_rate"] >= 0


def assert_job(data: dict):
    _assert_common_full(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["category_id"], str)
    assert data["status"] in (
        "REQUESTED", "INSTANT_QUOTED", "ESTIMATE_REQUESTED", "ESTIMATED",
        "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CALLBACK_OPEN", "CANCELLED",
    )
    assert data["quote_path"] in ("INSTANT", "IN_HOME", None)
    assert isinstance(data["is_warranty_callback"], bool)
    assert isinstance(data["address_zip_code"], str)


def assert_quote(data: dict):
    _assert_common_full(data)
    assert isinstance(data["job_id"], str)
    assert data["quote_type"] in ("INSTANT", "IN_HOME")
    assert isinstance(data["priced_amount_cents"], int) and data["priced_amount_cents"] >= 0
    assert isinstance(data["accepted"], bool)
    assert isinstance(data["superseded"], bool)


def assert_dispatch_window(data: dict):
    _assert_common_full(data)
    assert isinstance(data["pro_id"], str)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["service_zip_code"], str)
    assert data["hold_state"] in ("FREE", "BOOKED", "RELEASED")


def assert_labor_line(data: dict):
    _assert_common_full(data)
    assert isinstance(data["job_id"], str)
    assert isinstance(data["rate_cents_per_hour"], int) and data["rate_cents_per_hour"] >= 0
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] >= 0


def assert_part_line(data: dict):
    _assert_common_full(data)
    assert isinstance(data["job_id"], str)
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["from_truck_stock"], bool)
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] >= 0


def assert_work_visit(data: dict):
    _assert_common_full(data)
    assert isinstance(data["job_id"], str)
    assert isinstance(data["dispatch_window_id"], str)
    assert data["outcome"] in ("OPEN", "RESOLVED")


def assert_invoice(data: dict):
    _assert_common_full(data)
    assert isinstance(data["job_id"], str)
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    assert isinstance(data["refunded_cents"], int) and data["refunded_cents"] >= 0
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "REFUNDED", "VOID")


def assert_dispute(data: dict):
    _assert_common_full(data)
    assert isinstance(data["job_id"], str)
    assert isinstance(data["invoice_id"], str)
    assert data["reason"] in ("WORK_INCOMPLETE", "OVERCHARGED", "DAMAGE", "NO_SHOW")
    assert isinstance(data["requested_refund_cents"], int) and data["requested_refund_cents"] >= 1
    assert data["refund_destination"] in ("ORIGINAL", "WALLET")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "APPROVED", "DENIED", "WITHDRAWN")


def assert_background_check(data: dict):
    _assert_common_full(data)
    assert isinstance(data["pro_id"], str)
    assert data["check_type"] in ("CRIMINAL", "IDENTITY", "LICENSE")
    assert data["decision"] in ("PENDING", "PASS", "FAIL")


def assert_invoice_balance_reconciled(data: dict):
    """PRD §3.7 derived-field reconciliation: balance_due = total - amount_paid + refunded."""
    expected = data["total_cents"] - data["amount_paid_cents"] + data["refunded_cents"]
    assert data["balance_due_cents"] == expected, (
        f"balance_due_cents {data['balance_due_cents']} != "
        f"total {data['total_cents']} - paid {data['amount_paid_cents']} "
        f"+ refunded {data['refunded_cents']} = {expected}"
    )
