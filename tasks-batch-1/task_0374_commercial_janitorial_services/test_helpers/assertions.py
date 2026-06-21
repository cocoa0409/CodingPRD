"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["billing_email"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["open_complaint_count"], int) and data["open_complaint_count"] >= 0


def assert_site(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["label"], str)
    assert isinstance(data["cleanable_sqft"], int) and data["cleanable_sqft"] > 0
    assert data["floor_type"] in ("CARPET", "VCT", "TERRAZZO", "CONCRETE")
    assert isinstance(data["quality_target"], int) and 0 <= data["quality_target"] <= 100
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["monthly_base_cents"], int) and data["monthly_base_cents"] > 0
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert 0.0 <= data["callback_credit_pct"] <= 1.0
    assert 0.0 <= data["quality_holdback_pct"] <= 1.0
    assert data["status"] in ("DRAFT", "ACTIVE", "TERMINATED")


def assert_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["site_id"], str)
    assert 0 <= data["weekday"] <= 6
    assert 0 <= data["window_start_min"] <= 1439
    assert 1 <= data["window_end_min"] <= 1440
    assert data["window_end_min"] > data["window_start_min"]
    assert data["status"] in ("ACTIVE", "PAUSED")


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["shift_capacity_min"], int) and data["shift_capacity_min"] > 0
    assert data["status"] in ("AVAILABLE", "INACTIVE")


def assert_visit(data: dict):
    _assert_common(data)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["crew_id"], str)
    assert data["visit_kind"] in ("ROUTINE", "PERIODIC", "CALLBACK")
    assert isinstance(data["service_date"], str)
    assert isinstance(data["planned_start_min"], int)
    assert isinstance(data["planned_end_min"], int)
    assert data["planned_end_min"] > data["planned_start_min"]
    assert isinstance(data["estimated_labor_min"], int)
    assert isinstance(data["actual_labor_min"], int)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "MISSED", "CANCELLED")


def assert_time_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["crew_id"], str)
    assert isinstance(data["clock_in_min"], int)
    assert data["status"] in ("OPEN", "COMPLETED", "VOIDED")


def assert_inspection(data: dict):
    _assert_common(data)
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    assert isinstance(data["deficient"], bool)


def assert_periodic_job(data: dict):
    _assert_common(data)
    assert isinstance(data["site_id"], str)
    assert data["job_type"] in ("STRIP_WAX", "DEEP_CARPET")
    assert data["quoted_hours"] > 0
    assert data["status"] in ("REQUESTED", "DISPATCHED", "BILLED", "CANCELLED")


def assert_complaint(data: dict):
    _assert_common(data)
    assert isinstance(data["site_id"], str)
    assert data["severity"] in ("MINOR", "MAJOR")
    assert isinstance(data["description"], str)
    assert isinstance(data["credit_applied_cents"], int)
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "CALLBACK_SCHEDULED", "RESOLVED")


def assert_billing_period(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["period_month"], str)
    assert isinstance(data["base_cents"], int)
    assert isinstance(data["periodic_cents"], int)
    assert isinstance(data["callback_credit_cents"], int)
    assert isinstance(data["holdback_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("OPEN", "CLOSED", "REOPENED", "INVOICED")


def assert_invoice_line(data: dict):
    """InvoiceLine is an immutable append-only ledger row: id + created_at only,
    no version and no updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["line_type"] in ("BASE", "PERIODIC", "CALLBACK_CREDIT", "HOLDBACK")
    assert isinstance(data["amount_cents"], int)
    assert "version" not in data, "InvoiceLine must not carry a version field"
    assert "updated_at" not in data, "InvoiceLine must not carry an updated_at field"


def assert_supply_order(data: dict):
    _assert_common(data)
    assert isinstance(data["site_id"], str)
    assert data["sku"] in ("PAPER_TOWEL", "TRASH_LINER", "FLOOR_FINISH", "RESTROOM_KIT")
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["status"] in ("REQUESTED", "FULFILLED", "CANCELLED")
