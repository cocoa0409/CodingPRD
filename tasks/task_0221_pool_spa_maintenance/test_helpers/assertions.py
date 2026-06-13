"""Entity assertions and domain invariant checkers (Pool & Spa Maintenance)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_POOL_STATUSES = {"CLOSED", "OPEN", "GREEN_RECOVERY", "WINTERIZED"}
_VISIT_STATUSES = {"SCHEDULED", "COMPLETED", "SKIPPED", "RECOVERY_SCHEDULED", "CANCELLED"}
_PLAN_STATUSES = {"DRAFT", "ACTIVE", "COMPLETED", "CANCELLED"}
_ROUTE_STATUSES = {"PLANNED", "DISPATCHED", "CLOSED"}
_WO_STATUSES = {"OPEN", "DIAGNOSED", "AWAITING_APPROVAL", "ON_HOLD", "RESOLVED", "CANCELLED"}
_SE_STATUSES = {"REQUESTED", "APPLIED", "VOIDED"}
_INVOICE_STATUSES = {"DRAFT", "ISSUED", "PAID", "VOIDED"}


def _assert_common_core(data: dict):
    """id, created_at, updated_at, version on a full common-core entity."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _assert_common_core(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["billing_terms"] in {"PER_VISIT", "MONTHLY_ACCRUAL"}
    assert data["account_status"] in {"ACTIVE", "SUSPENDED"}


def assert_pool(data: dict):
    _assert_common_core(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert isinstance(data["label"], str)
    assert data["water_type"] in {"CHLORINE", "SALTWATER", "BROMINE_SPA"}
    assert isinstance(data["volume_gallons"], int) and data["volume_gallons"] >= 100
    assert data["service_status"] in _POOL_STATUSES, f"bad service_status {data['service_status']!r}"
    assert isinstance(data["open_work_order_count"], int) and data["open_work_order_count"] >= 0
    assert isinstance(data["balance_due_cents"], int) and data["balance_due_cents"] >= 0


def assert_service_plan(data: dict):
    _assert_common_core(data)
    assert is_valid_uuid(data.get("pool_id", "")), "pool_id must be a UUID"
    assert data["plan_type"] in {"RECURRING", "ONE_TIME"}
    assert data["frequency"] in {"WEEKLY", "BIWEEKLY", "MONTHLY", "NONE"}
    assert isinstance(data["per_visit_rate_cents"], int) and data["per_visit_rate_cents"] >= 0
    assert isinstance(data["prepaid_visit_count"], int) and data["prepaid_visit_count"] >= 0
    assert isinstance(data["visits_remaining"], int) and data["visits_remaining"] >= 0
    assert data["status"] in _PLAN_STATUSES


def assert_route(data: dict):
    _assert_common_core(data)
    assert isinstance(data["technician_id"], str)
    assert isinstance(data["service_date"], str)
    assert isinstance(data["window_start_minute"], int)
    assert isinstance(data["window_end_minute"], int)
    assert data["window_end_minute"] > data["window_start_minute"]
    assert isinstance(data["capacity_visits"], int) and data["capacity_visits"] >= 1
    assert data["status"] in _ROUTE_STATUSES


def assert_visit(data: dict):
    _assert_common_core(data)
    assert is_valid_uuid(data.get("pool_id", "")), "pool_id must be a UUID"
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert is_valid_uuid(data.get("route_id", "")), "route_id must be a UUID"
    assert isinstance(data["slot_start_minute"], int)
    assert isinstance(data["slot_end_minute"], int)
    assert data["slot_end_minute"] > data["slot_start_minute"]
    assert data["status"] in _VISIT_STATUSES
    assert data["skip_reason"] in {"NONE", "WEATHER", "HOLIDAY", "CUSTOMER_REQUEST"}
    assert isinstance(data["billed_amount_cents"], int) and data["billed_amount_cents"] >= 0


def assert_reading(data: dict):
    """ChemicalReading is append-only: ONLY id + created_at in the system core
    (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ChemicalReading is append-only: must NOT carry updated_at"
    assert "version" not in data, "ChemicalReading is append-only: must NOT carry version"
    assert is_valid_uuid(data.get("visit_id", "")), "visit_id must be a UUID"
    assert isinstance(data["free_chlorine_ppm"], (int, float)) and data["free_chlorine_ppm"] >= 0
    assert isinstance(data["ph"], (int, float)) and 0 <= data["ph"] <= 14
    assert isinstance(data["total_alkalinity_ppm"], (int, float)) and data["total_alkalinity_ppm"] >= 0
    assert isinstance(data["recommended_dose_grams"], (int, float)) and data["recommended_dose_grams"] >= 0


def assert_work_order(data: dict):
    _assert_common_core(data)
    assert is_valid_uuid(data.get("pool_id", "")), "pool_id must be a UUID"
    assert data["component"] in {"PUMP", "FILTER", "HEATER", "CHLORINATOR", "LINER"}
    assert data["severity"] in {"MINOR", "MAJOR", "CRITICAL"}
    assert isinstance(data["quoted_parts_cents"], int) and data["quoted_parts_cents"] >= 0
    assert isinstance(data["labor_minutes"], int) and data["labor_minutes"] >= 0
    assert data["status"] in _WO_STATUSES
    assert isinstance(data["repair_total_cents"], int) and data["repair_total_cents"] >= 0


def assert_seasonal_event(data: dict):
    _assert_common_core(data)
    assert is_valid_uuid(data.get("pool_id", "")), "pool_id must be a UUID"
    assert data["event_type"] in {"OPEN", "CLOSE"}
    assert isinstance(data["effective_date"], str)
    assert data["status"] in _SE_STATUSES


def assert_invoice(data: dict):
    _assert_common_core(data)
    assert is_valid_uuid(data.get("pool_id", "")), "pool_id must be a UUID"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in _INVOICE_STATUSES
