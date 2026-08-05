"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_program(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["incentive_rate_cents_per_kwh"], int)
    assert isinstance(data["penalty_rate_cents_per_kwh"], int)
    assert isinstance(data["capacity_incentive_cents_per_kw"], int)
    assert data["baseline_method"] in ("TEN_OF_TEN", "WEATHER_REGRESSION")
    assert data["settlement_method"] in ("PAY_FOR_PERFORMANCE", "CAPACITY_PAYMENT")


def assert_aggregator(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["enrolled_committed_kw"], (int, float))
    assert isinstance(data["season_delivered_kwh"], (int, float))
    assert isinstance(data["paid_balance_cents"], int)


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["email"], str)


def assert_device(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "DECOMMISSIONED")
    assert data["device_type"] in ("BATTERY", "THERMOSTAT", "EV_CHARGER")
    assert is_valid_uuid(data.get("aggregator_id", "")), "device aggregator_id must be a UUID"


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "OPTED_OUT", "TERMINATED")
    assert isinstance(data["committed_kw"], (int, float))
    assert isinstance(data["season_delivered_kwh"], (int, float))


def assert_dispatch_event(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "NOTIFIED", "ACTIVE", "COMPLETED", "SETTLED", "CANCELLED")
    assert data["baseline_method_snapshot"] in ("TEN_OF_TEN", "WEATHER_REGRESSION")


def assert_dispatch(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACKNOWLEDGED", "CURTAILING", "OVERRIDDEN", "OPTED_OUT", "COMPLETED")


def assert_settlement(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PENDING_APPROVAL", "APPROVED", "PAID", "DISPUTED", "REVISED")
    assert data["method_snapshot"] in ("PAY_FOR_PERFORMANCE", "CAPACITY_PAYMENT")
    assert isinstance(data["net_payment_cents"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "CLEARED", "REVERSED")
    assert isinstance(data["amount_cents"], int)


def assert_meter_reading(data: dict):
    """MeterReading is append-only: id + created_at only, no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only MeterReading must not carry updated_at"
    assert "version" not in data, "append-only MeterReading must not carry version"
    assert data["reading_type"] in ("BASELINE_WINDOW", "EVENT_WINDOW")
