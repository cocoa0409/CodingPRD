"""Entity assertions and domain invariant checkers.

Every primary resource carries the common fields of PRD §2.5 (`id`,
`created_at`, `updated_at`, `version`); each assert_* helper checks those plus
the entity's PRD-named fields and enum domains.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer")


def assert_terminal(data: dict):
    _assert_common_fields(data, "Terminal")
    assert isinstance(data["terminal_code"], str) and data["terminal_code"]
    for field in ("rail_cutoff_minutes_before_departure", "gate_free_hours",
                  "per_diem_rate_cents", "storage_rate_cents", "flip_fee_cents",
                  "max_stack_height", "yard_slot_count", "yard_slots_in_use",
                  "yard_slots_free", "ops_run_index"):
        assert isinstance(data[field], int), f"Terminal.{field} must be an integer"
    assert data["posture"] in ("OPEN", "CONGESTED", "CLOSED")
    assert_terminal_capacity_invariant(data)


def assert_terminal_capacity_invariant(data: dict):
    """PRD §2.7: yard_slots_free is always yard_slot_count - yard_slots_in_use."""
    assert data["yard_slots_free"] == data["yard_slot_count"] - data["yard_slots_in_use"], (
        "yard_slots_free must always equal yard_slot_count - yard_slots_in_use: "
        f"got free={data['yard_slots_free']}, count={data['yard_slot_count']}, "
        f"in_use={data['yard_slots_in_use']}")


def assert_chassis_pool(data: dict):
    _assert_common_fields(data, "ChassisPool")
    assert isinstance(data["terminal_id"], str)
    assert isinstance(data["pool_code"], str) and data["pool_code"]
    for field in ("total_chassis_count", "available_chassis_count",
                  "reserved_chassis_count", "out_chassis_count",
                  "maintenance_chassis_count", "flip_fee_balance_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"ChassisPool.{field} must be a non-negative integer")


def assert_chassis(data: dict):
    _assert_common_fields(data, "Chassis")
    assert isinstance(data["pool_id"], str)
    assert isinstance(data["chassis_number"], str) and data["chassis_number"]
    assert data["status"] in ("AVAILABLE", "RESERVED", "OUT", "MAINTENANCE", "RETIRED")
    assert data["roadability_status"] in ("ROADABLE", "UNROADABLE")


def assert_membership(data: dict):
    _assert_common_fields(data, "ChassisMembership")
    assert isinstance(data["pool_id"], str)
    assert isinstance(data["carrier_id"], str)
    assert data["membership_status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["flip_fee_credit_cents"], int) and data["flip_fee_credit_cents"] >= 0


def assert_carrier(data: dict):
    _assert_common_fields(data, "Carrier")
    assert isinstance(data["scac_code"], str) and data["scac_code"]
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["billing_credit_limit_cents"], int)
    assert isinstance(data["outstanding_billing_cents"], int) and (
        data["outstanding_billing_cents"] >= 0)


def assert_container(data: dict):
    _assert_common_fields(data, "Container")
    assert isinstance(data["terminal_id"], str)
    assert isinstance(data["container_number"], str) and data["container_number"]
    assert data["iso_type"] in ("20FT", "40FT", "40HC", "45FT")
    assert data["status"] in ("INBOUND_TRAIN", "ON_GROUND", "MOUNTED",
                              "OUTBOUND_TRUCK", "DEPARTED", "VOIDED")


def assert_yard_slot(data: dict):
    _assert_common_fields(data, "YardSlot")
    assert isinstance(data["terminal_id"], str)
    assert isinstance(data["slot_code"], str) and data["slot_code"]
    assert isinstance(data["row"], str) and data["row"]
    assert isinstance(data["tier_max"], int)
    assert data["status"] in ("EMPTY", "OCCUPIED", "BLOCKED", "RESERVED")
    assert isinstance(data["current_height"], int) and data["current_height"] >= 0


def assert_train(data: dict):
    _assert_common_fields(data, "Train")
    assert isinstance(data["terminal_id"], str)
    assert isinstance(data["train_symbol"], str) and data["train_symbol"]
    assert is_iso8601_timestamp(data["scheduled_departure_utc"])
    assert data["status"] in ("SCHEDULED", "ARRIVED", "LOADING", "DEPARTED", "CANCELLED")
    assert is_iso8601_timestamp(data["rail_cutoff_at"]), (
        "Train.rail_cutoff_at must be an ISO 8601 timestamp")


def assert_appointment(data: dict):
    _assert_common_fields(data, "GateAppointment")
    assert isinstance(data["terminal_id"], str)
    assert isinstance(data["carrier_id"], str)
    assert isinstance(data["container_id"], str)
    assert data["direction"] in ("IN", "OUT")
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert data["status"] in ("BOOKED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_transaction(data: dict):
    _assert_common_fields(data, "GateTransaction")
    assert isinstance(data["terminal_id"], str)
    assert isinstance(data["appointment_id"], str)
    assert isinstance(data["container_id"], str)
    assert isinstance(data["carrier_id"], str)
    assert data["direction"] in ("IN", "OUT")
    assert isinstance(data["driver_id"], str) and data["driver_id"]
    assert isinstance(data["gate_lane"], str) and data["gate_lane"]
    assert data["status"] in ("PENDING", "COMPLETED", "REJECTED")


def assert_damage_inspection(data: dict):
    _assert_common_fields(data, "DamageInspection")
    assert isinstance(data["terminal_id"], str)
    assert isinstance(data["gate_transaction_id"], str)
    assert data["damage_kind"] in ("TIRE", "BRAKE", "LIGHTS", "FRAME",
                                   "CONTAINER_DENT", "CONTAINER_PUNCTURE")
    assert data["severity"] in ("MINOR", "MAJOR", "SAFETY_CRITICAL")
    assert isinstance(data["repair_cost_cents"], int) and data["repair_cost_cents"] >= 0
    assert data["status"] in ("OPEN", "REPAIR_SCHEDULED", "REPAIRED", "WAIVED")
    # PRD §3.7: exactly one of chassis_id / container_id is set.
    set_count = int(data.get("chassis_id") is not None) + int(
        data.get("container_id") is not None)
    assert set_count == 1, (
        "DamageInspection must reference exactly one of chassis_id/container_id")


def assert_ledger_entry(data: dict):
    _assert_common_fields(data, "BillingLedgerEntry")
    assert isinstance(data["terminal_id"], str)
    assert isinstance(data["carrier_id"], str)
    assert data["entry_kind"] in ("PER_DIEM", "STORAGE", "FLIP_FEE", "DAMAGE_REPAIR")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["applied_cents"], int) and data["applied_cents"] >= 0
    assert data["applied_cents"] <= data["amount_cents"], (
        "applied_cents may not exceed amount_cents")
    assert data["status"] in ("OPEN", "PARTIALLY_APPLIED", "APPLIED", "WAIVED")
