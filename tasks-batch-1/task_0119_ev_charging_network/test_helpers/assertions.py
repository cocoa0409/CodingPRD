"""Entity assertions and domain invariant checkers.

Each assert_{entity}() verifies the shape of a resource as the PRD describes it.
MeterEvent is immutable (PRD §2.4): it carries only id + created_at, never
updated_at or version, so its assertion forbids those fields.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

CONNECTOR_TYPES = ["CCS", "CHADEMO", "J1772", "NACS"]
OCPP_STATUSES = ["AVAILABLE", "OCCUPIED", "FAULTED", "UNAVAILABLE"]
ALLOCATION_POLICIES = ["PROPORTIONAL", "PRIORITY"]
PRICING_MODES = ["ENERGY_BASED", "TIME_BASED"]
RESERVATION_STATUSES = [
    "REQUESTED", "CONFIRMED", "CHECKED_IN", "CONSUMED", "NO_SHOW", "CANCELLED", "EXPIRED",
]
CHARGING_STATUSES = [
    "PREPARING", "CHARGING", "SUSPENDED", "FINISHING", "COMPLETED", "ABORTED",
]
BILLING_STATUSES = ["UNBILLED", "RATED", "SETTLED", "REVERSED"]
BATCH_STATUSES = ["OPEN", "LOCKED", "SETTLED", "DISPUTED"]
LINE_ITEM_STATUSES = ["PENDING", "SETTLED", "REVERSED"]
TRIGGER_REASONS = ["SESSION_START", "SESSION_STOP", "SESSION_SUSPEND", "MANUAL_REBALANCE"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_site(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["circuit_limit_kw"] > 0
    assert data["allocation_policy"] in ALLOCATION_POLICIES
    assert data["demand_charge_threshold_kw"] > 0
    assert data["demand_charge_threshold_kw"] <= data["circuit_limit_kw"]
    assert isinstance(data["demand_avoidance_armed"], bool)
    assert data["allocated_total_kw"] >= 0
    assert isinstance(data["active_session_count"], int) and data["active_session_count"] >= 0


def assert_stall(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be valid UUID"
    assert data["connector_type"] in CONNECTOR_TYPES
    assert data["max_power_kw"] > 0
    assert data["ocpp_status"] in OCPP_STATUSES
    assert isinstance(data["reservation_priority"], int) and data["reservation_priority"] >= 1


def assert_driver(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert is_valid_uuid(data.get("home_emsp_id", "")), "home_emsp_id must be valid UUID"
    assert isinstance(data["wallet_balance_cents"], int)


def assert_emsp(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert 0 <= data["commission_pct"] < 1
    assert isinstance(data["receivable_balance_cents"], int)


def assert_tariff(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be valid UUID"
    assert data["connector_type"] in CONNECTOR_TYPES
    assert data["pricing_mode"] in PRICING_MODES
    assert isinstance(data["session_fee_cents"], int) and data["session_fee_cents"] >= 0
    assert data["energy_tier_2_max_kwh"] > data["energy_tier_1_max_kwh"]


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("stall_id", "")), "stall_id must be valid UUID"
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be valid UUID"
    assert data["status"] in RESERVATION_STATUSES
    assert isinstance(data["hold_fee_cents"], int) and data["hold_fee_cents"] >= 0


def assert_charging_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("stall_id", "")), "stall_id must be valid UUID"
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be valid UUID"
    assert data["charging_status"] in CHARGING_STATUSES
    assert data["billing_status"] in BILLING_STATUSES
    assert isinstance(data["is_roaming"], bool)
    assert data["energy_delivered_kwh"] >= 0
    assert isinstance(data["charging_minutes"], int) and data["charging_minutes"] >= 0
    assert isinstance(data["idle_minutes"], int) and data["idle_minutes"] >= 0
    assert data["allocated_power_kw"] >= 0
    assert isinstance(data["total_cost_cents"], int)
    assert isinstance(data["idle_fee_cents"], int)


def assert_meter_event(data: dict):
    """MeterEvent is immutable (PRD §2.4): id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "MeterEvent must not carry a version field"
    assert "updated_at" not in data, "MeterEvent must not carry an updated_at field"
    assert data["meter_kwh"] >= 0
    assert data["reading_context"] in [
        "TRANSACTION_BEGIN", "SAMPLE_PERIODIC", "TRANSACTION_END",
    ]


def assert_settlement_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("emsp_id", "")), "emsp_id must be valid UUID"
    assert data["status"] in BATCH_STATUSES
    assert isinstance(data["line_item_count"], int) and data["line_item_count"] >= 0
    assert isinstance(data["total_amount_cents"], int)


def assert_settlement_line_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("batch_id", "")), "batch_id must be valid UUID"
    assert is_valid_uuid(data.get("session_id", "")), "session_id must be valid UUID"
    assert data["status"] in LINE_ITEM_STATUSES
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["commission_cents"], int)
    assert isinstance(data["net_amount_cents"], int)
    # net = gross - commission (PRD §3.7)
    assert data["net_amount_cents"] == data["gross_amount_cents"] - data["commission_cents"]


def assert_load_allocation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be valid UUID"
    assert data["trigger_reason"] in TRIGGER_REASONS
    assert data["policy_used"] in ALLOCATION_POLICIES
    assert data["cap_kw"] >= 0
    assert data["allocated_total_kw"] >= 0
    assert data["allocated_total_kw"] <= data["cap_kw"] + 1e-9, "allocated_total_kw must not exceed cap_kw"
    assert isinstance(data["session_count"], int) and data["session_count"] >= 0
