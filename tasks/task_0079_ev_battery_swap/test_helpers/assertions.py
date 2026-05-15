"""Entity assertions and domain invariants for the EV Battery Swap API.

Uses the framework's generic helpers (is_valid_uuid, is_iso8601_timestamp)
under the hood. Each asserter accepts the dict shape returned by the
respective endpoint and verifies all PRD-required fields.
"""
from __future__ import annotations
from typing import Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-field helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_common_mutable(data: dict, entity_name: str) -> None:
    """PRD §2.4: mutable entities carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601 UTC with ms, got "
        f"{data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601 UTC with ms, got "
        f"{data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be a positive int, got "
        f"{data.get('version')!r}"
    )


def _assert_common_appendonly(data: dict, entity_name: str) -> None:
    """PRD §2.4: reference / append-only entities carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Station
# ---------------------------------------------------------------------------
def assert_station(data: dict) -> None:
    _assert_common_mutable(data, "Station")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("latitude"), (int, float))
    assert -90.0 <= float(data["latitude"]) <= 90.0
    assert isinstance(data.get("longitude"), (int, float))
    assert -180.0 <= float(data["longitude"]) <= 180.0
    assert isinstance(data.get("total_slots"), int)
    assert 1 <= data["total_slots"] <= 64
    assert data.get("status") in {"OPEN", "RESTRICTED", "OFFLINE"}
    assert isinstance(data.get("idle_battery_count"), int)
    assert data["idle_battery_count"] >= 0
    assert isinstance(data.get("charging_battery_count"), int)
    assert data["charging_battery_count"] >= 0


# ---------------------------------------------------------------------------
# ChargingSlot
# ---------------------------------------------------------------------------
def assert_charging_slot(data: dict) -> None:
    _assert_common_mutable(data, "ChargingSlot")
    assert is_valid_uuid(data.get("station_id", ""))
    assert isinstance(data.get("slot_number"), int)
    assert data["slot_number"] >= 1
    assert data.get("status") in {"EMPTY", "OCCUPIED", "OUT_OF_SERVICE"}
    if data["status"] == "EMPTY":
        assert data.get("battery_id") in (None, ""), (
            "PRD §3.1: 'the slot's battery_id is null whenever it is EMPTY'"
        )
    else:
        if data["status"] == "OCCUPIED":
            assert is_valid_uuid(data.get("battery_id", "")), (
                "PRD §3.1: an OCCUPIED slot references the parked battery"
            )
    assert data.get("tou_zone") in {"PEAK", "SHOULDER", "OFF_PEAK"}


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------
def assert_battery(data: dict) -> None:
    _assert_common_mutable(data, "Battery")
    assert isinstance(data.get("serial_number"), str)
    assert 6 <= len(data["serial_number"]) <= 64
    assert isinstance(data.get("battery_model_code"), str)
    assert data.get("status") in {
        "IDLE", "CHARGING", "IN_USE", "FAULT",
        "RETIRED", "RECYCLED", "IN_TRANSIT",
    }
    assert isinstance(data.get("soc_pct"), (int, float))
    assert 0.0 <= float(data["soc_pct"]) <= 100.0
    assert isinstance(data.get("soh_pct"), (int, float))
    assert 0.0 <= float(data["soh_pct"]) <= 100.0
    assert data.get("soh_grade") in {"A", "B", "C", "RETIRED_EV"}
    assert isinstance(data.get("cycle_count"), int)
    assert data["cycle_count"] >= 0
    assert data.get("cascade_stage") in {
        "NONE", "ENERGY_STORAGE", "LOW_SPEED_VEHICLE", "END_OF_LIFE",
    }
    assert isinstance(data.get("recall_flag"), bool)


# ---------------------------------------------------------------------------
# Vehicle
# ---------------------------------------------------------------------------
def assert_vehicle(data: dict) -> None:
    _assert_common_mutable(data, "Vehicle")
    assert isinstance(data.get("vin"), str)
    assert 11 <= len(data["vin"]) <= 17, (
        "PRD §3.1: vin between eleven and seventeen characters"
    )
    assert isinstance(data.get("vehicle_model_code"), str)
    assert is_valid_uuid(data.get("owner_member_id", ""))


# ---------------------------------------------------------------------------
# Member
# ---------------------------------------------------------------------------
def assert_member(data: dict) -> None:
    _assert_common_mutable(data, "Member")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("phone"), str) and len(data["phone"]) > 0
    assert data.get("subscription_tier") in {"NONE", "BASIC", "PREMIUM"}
    assert isinstance(data.get("subscription_swaps_remaining"), int)
    assert data["subscription_swaps_remaining"] >= 0
    assert isinstance(data.get("no_show_count_30d"), int)
    assert data["no_show_count_30d"] >= 0


# ---------------------------------------------------------------------------
# Reservation
# ---------------------------------------------------------------------------
def assert_reservation(data: dict) -> None:
    _assert_common_mutable(data, "Reservation")
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("vehicle_id", ""))
    assert is_valid_uuid(data.get("station_id", ""))
    assert is_iso8601_timestamp(data.get("slot_start_at", ""))
    assert is_iso8601_timestamp(data.get("slot_end_at", ""))
    assert data.get("status") in {
        "BOOKED", "CHECKED_IN", "FULFILLED", "CANCELLED", "NO_SHOW",
    }


# ---------------------------------------------------------------------------
# SwapEvent
# ---------------------------------------------------------------------------
def assert_swap_event(data: dict) -> None:
    _assert_common_mutable(data, "SwapEvent")
    assert is_valid_uuid(data.get("reservation_id", ""))
    assert is_valid_uuid(data.get("vehicle_id", ""))
    assert is_valid_uuid(data.get("station_id", ""))
    assert data.get("phase") in {
        "CHECKED_IN", "INSPECTED", "UNINSTALLED",
        "INSTALLED", "COMPLETED", "ABORTED",
    }


# ---------------------------------------------------------------------------
# BillingRecord
# ---------------------------------------------------------------------------
def assert_billing_record(data: dict) -> None:
    _assert_common_mutable(data, "BillingRecord")
    assert is_valid_uuid(data.get("swap_event_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    for f in ("per_swap_base_cents", "soc_diff_cents",
              "tou_pass_through_cents", "subscription_deduction_cents",
              "amount_due_cents", "refund_cents"):
        assert isinstance(data.get(f), int), f"{f} must be int (cents)"
        assert data[f] >= 0, (
            f"PRD §2.7: no amount stored on a BillingRecord is ever "
            f"negative; got {f}={data[f]}"
        )
    assert data["refund_cents"] <= data["amount_due_cents"], (
        "PRD §2.7: refund_cents cannot exceed amount_due_cents"
    )
    assert data.get("payment_status") in {
        "PENDING", "PAID", "REFUNDED", "FAILED",
    }


# ---------------------------------------------------------------------------
# DispatchOrder
# ---------------------------------------------------------------------------
def assert_dispatch_order(data: dict) -> None:
    _assert_common_mutable(data, "DispatchOrder")
    assert is_valid_uuid(data.get("source_station_id", ""))
    assert is_valid_uuid(data.get("dest_station_id", ""))
    assert is_valid_uuid(data.get("battery_id", ""))
    assert data["source_station_id"] != data["dest_station_id"], (
        "PRD §3.6: source and destination must differ"
    )
    assert data.get("status") in {
        "REQUESTED", "IN_TRANSIT", "DELIVERED", "CANCELLED",
    }


# ---------------------------------------------------------------------------
# Reference / append-only entities — id + created_at only (PRD §2.4)
# ---------------------------------------------------------------------------
def assert_battery_model(data: dict) -> None:
    _assert_common_appendonly(data, "BatteryModel")
    assert isinstance(data.get("code"), str)
    assert 2 <= len(data["code"]) <= 32
    assert isinstance(data.get("rated_capacity_kwh"), (int, float))
    assert float(data["rated_capacity_kwh"]) > 0
    assert isinstance(data.get("nominal_voltage"), (int, float))
    assert float(data["nominal_voltage"]) > 0
    assert isinstance(data.get("ev_soh_floor_pct"), (int, float))
    assert 0.0 < float(data["ev_soh_floor_pct"]) < 100.0
    assert isinstance(data.get("manufacturer"), str)


def assert_vehicle_model(data: dict) -> None:
    _assert_common_appendonly(data, "VehicleModel")
    assert isinstance(data.get("code"), str)
    assert 2 <= len(data["code"]) <= 32
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("pack_voltage_min"), (int, float))
    assert isinstance(data.get("pack_voltage_max"), (int, float))
    assert float(data["pack_voltage_max"]) > float(data["pack_voltage_min"])


def assert_compatibility_rule(data: dict) -> None:
    _assert_common_appendonly(data, "CompatibilityRule")
    assert isinstance(data.get("vehicle_model_code"), str)
    assert isinstance(data.get("battery_model_code"), str)
    assert isinstance(data.get("connector_match"), bool)
    assert isinstance(data.get("bms_handshake_supported"), bool)


def assert_soh_assessment(data: dict) -> None:
    _assert_common_appendonly(data, "SOHAssessment")
    assert is_valid_uuid(data.get("battery_id", ""))
    assert isinstance(data.get("capacity_test_kwh"), (int, float))
    assert isinstance(data.get("internal_resistance_mohm"), (int, float))
    assert isinstance(data.get("avg_temperature_c"), (int, float))
    assert isinstance(data.get("cycle_count_at_assessment"), int)
    assert isinstance(data.get("soh_pct_out"), (int, float))
    assert 0.0 <= float(data["soh_pct_out"]) <= 100.0
    assert data.get("soh_grade_out") in {"A", "B", "C", "RETIRED_EV"}


def assert_audit_log(data: dict) -> None:
    _assert_common_appendonly(data, "AuditLog")
    assert data.get("event_type") in {
        "BATTERY_STATUS_CHANGE", "SWAP_PHASE_CHANGE", "DISPATCH_CHANGE",
        "RECALL_APPLIED", "RESERVATION_CHANGE",
    }
    assert isinstance(data.get("entity_type"), str)
    assert isinstance(data.get("entity_id"), str)
    assert isinstance(data.get("to_value"), str)
    assert isinstance(data.get("actor_role"), str)


__all__ = [
    "assert_station",
    "assert_charging_slot",
    "assert_battery",
    "assert_vehicle",
    "assert_member",
    "assert_reservation",
    "assert_swap_event",
    "assert_billing_record",
    "assert_dispatch_order",
    "assert_battery_model",
    "assert_vehicle_model",
    "assert_compatibility_rule",
    "assert_soh_assessment",
    "assert_audit_log",
]
