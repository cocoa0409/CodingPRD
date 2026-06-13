"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates that a response object carries the fields and
value ranges the PRD promises. The MonitoringPlan assertion deliberately does
NOT require version/updated_at, since a plan is an immutable price-book row.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


CONTRACT_STATUSES = {"PENDING", "ACTIVE", "CANCELLATION_REQUESTED", "CANCELLED"}
MONITORING_STATUSES = {"ACTIVE", "SUSPENDED", "TERMINATED"}
ARMING_STATES = {"DISARMED", "ARMED_STAY", "ARMED_AWAY"}
COMMUNICATOR_HEALTHS = {"HEALTHY", "DEGRADED", "OFFLINE"}
SENSOR_STATUSES = {"ENROLLED", "BYPASSED", "REMOVED"}
SENSOR_TYPES = {"DOOR", "MOTION", "GLASS_BREAK", "SMOKE", "CO", "PANIC"}
ALARM_STATUSES = {"RECEIVED", "ROUTED", "DISPATCHED", "RESOLVED_REAL", "RESOLVED_FALSE", "SUPPRESSED"}
SIGNAL_TYPES = {"BURGLARY", "FIRE", "MEDICAL", "PANIC"}
ROUTED_SERVICES = {"POLICE", "FIRE", "MEDICAL"}
DISPATCH_STATUSES = {"ORDERED", "CONFIRMED", "CANCELLED"}
PERMIT_STATUSES = {"ACTIVE", "EXPIRED", "REVOKED"}
SETTLEMENT_STATUSES = {"ASSESSED", "PAID", "WAIVED"}
PLAN_TIERS = {"BASIC", "PLUS", "PRO"}
PREMISES_TYPES = {"RESIDENTIAL", "COMMERCIAL"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_monitoring_plan(data: dict):
    """A plan is immutable: id + created_at only as system fields; no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["tier"] in PLAN_TIERS, f"unexpected tier {data.get('tier')}"
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["police_dispatch_included"], bool)
    assert isinstance(data["max_sensors"], int) and data["max_sensors"] >= 1
    assert isinstance(data["cellular_backup_included"], bool)


def assert_account(data: dict):
    _assert_common(data)
    assert data["premises_type"] in PREMISES_TYPES
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a valid UUID"
    assert data["contract_status"] in CONTRACT_STATUSES
    assert data["monitoring_status"] in MONITORING_STATUSES
    assert isinstance(data["contract_term_months"], int) and data["contract_term_months"] >= 1
    assert isinstance(data["monitoring_balance_cents"], int)
    assert data["monitoring_balance_cents"] >= 0, "monitoring_balance_cents is never negative"
    assert isinstance(data["false_alarm_count_cycle"], int) and data["false_alarm_count_cycle"] >= 0
    assert isinstance(data["early_termination_fee_cents"], int) and data["early_termination_fee_cents"] >= 0


def assert_system(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a valid UUID"
    assert data["arming_state"] in ARMING_STATES
    assert isinstance(data["test_mode"], bool)
    assert data["primary_path"] in {"BROADBAND", "CELLULAR"}
    assert isinstance(data["cellular_signal_dbm"], int)
    assert isinstance(data["backup_battery_pct"], int) and 0 <= data["backup_battery_pct"] <= 100
    assert isinstance(data["last_checkin_minutes_ago"], int) and data["last_checkin_minutes_ago"] >= 0
    assert data["communicator_health"] in COMMUNICATOR_HEALTHS
    assert isinstance(data["sensor_count"], int) and data["sensor_count"] >= 0


def assert_sensor(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("system_id", "")), "system_id must be a valid UUID"
    assert isinstance(data["zone_number"], int) and data["zone_number"] >= 1
    assert data["sensor_type"] in SENSOR_TYPES
    assert data["status"] in SENSOR_STATUSES


def assert_alarm_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("system_id", "")), "system_id must be a valid UUID"
    assert is_valid_uuid(data.get("sensor_id", "")), "sensor_id must be a valid UUID"
    assert data["signal_type"] in SIGNAL_TYPES
    assert data["status"] in ALARM_STATUSES
    assert is_iso8601_timestamp(data.get("raised_utc", "")), "raised_utc must be ISO 8601"
    if data.get("routed_service") is not None:
        assert data["routed_service"] in ROUTED_SERVICES
    if data.get("resolution") is not None:
        assert data["resolution"] in {"REAL", "FALSE_ALARM"}


def assert_dispatch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("alarm_event_id", "")), "alarm_event_id must be a valid UUID"
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a valid UUID"
    assert data["service"] in ROUTED_SERVICES
    assert data["status"] in DISPATCH_STATUSES
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a valid UUID"
    assert isinstance(data["permit_number"], str) and len(data["permit_number"]) > 0
    assert data["status"] in PERMIT_STATUSES
    assert isinstance(data["filed_days_late"], int) and data["filed_days_late"] >= 0
    assert isinstance(data["fee_total_cents"], int) and data["fee_total_cents"] >= 0


def assert_fine(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a valid UUID"
    assert is_valid_uuid(data.get("alarm_event_id", "")), "alarm_event_id must be a valid UUID"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["settlement_status"] in SETTLEMENT_STATUSES


def assert_account_invariants(data: dict):
    """Invariants that must hold on any account read."""
    assert data["monitoring_balance_cents"] >= 0, "balance floored at zero, never negative"
    assert data["early_termination_fee_cents"] >= 0
    assert data["false_alarm_count_cycle"] >= 0
