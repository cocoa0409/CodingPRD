"""Entity assertions and domain invariant checkers.

Validate response structures against the PRD contract using the framework's
generic helpers (is_valid_uuid, is_iso8601_timestamp).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields carried by every primary resource (PRD §2.4):
    id (UUID), created_at, updated_at (ISO 8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents is never negative"
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_service_catalog(data: dict):
    _assert_common(data)
    assert data["service_type"] in ("STEAM", "DRY")
    assert isinstance(data["base_rate_cents_per_sqft"], int)
    assert data["base_rate_cents_per_sqft"] >= 1
    for fld in ("stain_addon_cents", "pet_addon_cents",
                "protectant_cents_per_sqft", "move_furniture_flat_cents"):
        assert isinstance(data[fld], int) and data[fld] >= 0
    assert isinstance(data["dry_time_minutes"], int) and data["dry_time_minutes"] >= 1


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["crew_name"], str) and len(data["crew_name"]) > 0
    assert data["supported_service_type"] in ("STEAM", "DRY")
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert data["turnaround_buffer_minutes"] >= 0
    assert data["status"] in ("AVAILABLE", "OUT_OF_SERVICE")


def assert_recurring_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["cadence"] in ("MONTHLY", "QUARTERLY", "SEMIANNUAL")
    assert isinstance(data["completed_visit_count"], int)
    assert data["completed_visit_count"] >= 0
    assert data["status"] in ("ACTIVE", "PAUSED")


def assert_cleaning_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["service_catalog_id"])
    assert data["lifecycle_status"] in (
        "DRAFT", "QUOTED", "BOOKED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "INVOICED", "PAID")
    assert isinstance(data["move_furniture"], bool)
    assert isinstance(data["total_sqft"], int) and data["total_sqft"] >= 0


def assert_room(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cleaning_job_id"])
    assert isinstance(data["area_label"], str) and len(data["area_label"]) > 0
    assert isinstance(data["area_sqft"], int) and data["area_sqft"] >= 1
    assert data["soiling_level"] in ("LIGHT", "MODERATE", "HEAVY")


def assert_addon(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cleaning_job_id"])
    assert data["addon_type"] in ("STAIN", "PET", "PROTECTANT")
    assert isinstance(data["line_price_cents"], int)
    assert data["line_price_cents"] >= 0


def assert_scheduled_slot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["crew_id"])
    assert is_valid_uuid(data["cleaning_job_id"])
    assert isinstance(data["start_minute"], int) and data["start_minute"] >= 0
    assert isinstance(data["end_minute"], int)
    assert data["end_minute"] > data["start_minute"]
    assert data["status"] in ("RESERVED", "RELEASED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cleaning_job_id"])
    for fld in ("amount_due_cents", "wallet_applied_cents",
                "net_payable_cents", "amount_paid_cents"):
        assert isinstance(data[fld], int) and data[fld] >= 0
    assert data["status"] in ("OPEN", "SETTLED", "VOID")


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["invoice_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["method"] in ("CARD", "CASH", "CHECK")
    assert data["status"] == "APPLIED"


def assert_guarantee_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cleaning_job_id"])
    assert isinstance(data["reason"], str)
    assert isinstance(data["filed_at_minute"], int) and data["filed_at_minute"] >= 0
    assert data["status"] in ("FILED", "GRANTED", "DENIED")


def assert_wallet_ledger_entry(data: dict):
    """Append-only ledger record (PRD §2.4): carries ONLY id + created_at —
    no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "WalletLedgerEntry has no updated_at"
    assert "version" not in data, "WalletLedgerEntry has no version"
    assert isinstance(data["delta_cents"], int)
    assert data["reason"] in ("GUARANTEE_CREDIT", "INVOICE_APPLIED", "INVOICE_REFUND")
