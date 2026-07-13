"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_lightweight(data: dict):
    """id + created_at only (append-only records: VehicleClassPolicy, FuelLog)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_vehicle(data: dict):
    _assert_common(data)
    assert data["operational_status"] in ("IN_SERVICE", "IN_SHOP", "OUT_OF_SERVICE")
    assert data["lifecycle_status"] in (
        "ACTIVE", "FLAGGED_FOR_REPLACEMENT", "PENDING_DISPOSAL", "DISPOSED")
    assert data["assignment_type"] in ("POOL", "DEPARTMENT_ASSIGNED")
    assert isinstance(data["odometer_miles"], int) and data["odometer_miles"] >= 0
    assert isinstance(data["lifetime_maintenance_cents"], int)
    assert isinstance(data["lifetime_fuel_cents"], int)
    assert isinstance(data["open_accident_count"], int)


def assert_department(data: dict):
    _assert_common(data)
    assert isinstance(data["monthly_budget_cents"], int)
    assert isinstance(data["committed_budget_cents"], int)
    assert isinstance(data["billed_ytd_cents"], int)


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "CHECKED_OUT", "RETURNED", "CANCELLED")


def assert_shop_bay(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "CLOSED")
    assert data["bay_type"] in ("GENERAL", "HEAVY", "BODY")


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "AWAITING_PARTS", "COMPLETED", "CANCELLED")
    assert data["wo_type"] in ("PM", "REPAIR", "ACCIDENT_REPAIR")


def assert_accident_claim(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REPORTED", "UNDER_INVESTIGATION", "SUBROGATION_PENDING",
        "RECOVERED", "CLOSED_NO_FAULT", "WRITTEN_OFF")
    assert isinstance(data["at_fault"], bool)


def assert_disposal_record(data: dict):
    _assert_common(data)
    assert data["status"] in ("LISTED", "BIDDING", "SOLD", "NO_SALE")


def assert_chargeback_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "ADJUSTED", "PAID")
    assert data["basis"] in ("PROVISIONAL", "FINAL")


def assert_vehicle_class_policy(data: dict):
    _assert_lightweight(data)


def assert_fuel_log(data: dict):
    _assert_lightweight(data)
