"""
PRD-specific entity assertions and domain invariant checkers.

Each ``assert_<entity>`` validates the response shape against PRD §2.4 (common
fields), the entity's enum constraints, and PRD-mandated field types.
"""

from decimal import Decimal
from typing import Any, Dict, Optional

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-field helpers (PRD §2.4)
# ---------------------------------------------------------------------------


def _assert_common_fields(data: Dict[str, Any]) -> None:
    """Assert id, created_at, updated_at, version are present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1 and increments"


def _assert_payment_event_common_fields(data: Dict[str, Any]) -> None:
    """PaymentEvent has id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "PaymentEvent has no updated_at (PRD §2.4)"
    assert "version" not in data, "PaymentEvent has no version (PRD §2.4)"


# ---------------------------------------------------------------------------
# Cabinet
# ---------------------------------------------------------------------------


def assert_cabinet(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["cabinet_code"], str) and data["cabinet_code"]
    assert data["city_code"] in {"BJ", "SH"}
    assert is_valid_uuid(data["location_partner_id"])
    assert data["model"] in {"SLOT_8", "SLOT_16", "SLOT_24"}
    assert isinstance(data["total_slots"], int) and data["total_slots"] in {
        8,
        16,
        24,
    }
    assert isinstance(data["firmware_version"], str)
    assert data["online_status"] in {"ONLINE", "OFFLINE"}
    assert is_iso8601_timestamp(data["last_heartbeat_at"])


# ---------------------------------------------------------------------------
# Slot
# ---------------------------------------------------------------------------


def assert_slot(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["cabinet_id"])
    assert isinstance(data["slot_index"], int) and data["slot_index"] >= 0
    assert data["slot_status"] in {
        "EMPTY",
        "OCCUPIED",
        "RESERVED",
        "FAULTY",
        "STUCK",
    }
    assert (data.get("device_id") is None) or is_valid_uuid(data["device_id"])


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------


def assert_device(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["device_code"], str) and data["device_code"]
    assert data["model"] in {"PB_5K", "PB_10K", "PB_20K"}
    assert (
        isinstance(data["battery_level"], int)
        and 0 <= data["battery_level"] <= 100
    )
    assert data["status"] in {
        "AVAILABLE",
        "BORROWED",
        "FAULTY",
        "STUCK_IN_SLOT",
        "LOST",
    }
    cab = data.get("current_cabinet_id")
    idx = data.get("current_slot_index")
    assert cab is None or is_valid_uuid(cab)
    assert idx is None or (isinstance(idx, int) and idx >= 0)


# ---------------------------------------------------------------------------
# PricingPlan
# ---------------------------------------------------------------------------


def assert_pricing_plan(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["city_code"] in {"BJ", "SH"}
    assert_cost_precision(data["hourly_rate"])
    assert_cost_precision(data["daily_cap"])
    assert_cost_precision(data["cross_city_surcharge"])
    assert data["daily_cap"] > data["hourly_rate"]
    assert isinstance(data["free_minutes"], int) and data["free_minutes"] >= 0
    assert data["cross_city_surcharge"] >= 0


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


def assert_user(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["phone"], str) and data["phone"]
    assert_cost_precision(data["wallet_balance"])
    assert_cost_precision(data["deposit_balance"])
    assert 0.00 <= data["deposit_balance"] <= 99.00
    assert isinstance(data["refund_count_30d"], int) and data["refund_count_30d"] >= 0
    assert isinstance(data["borrow_count_24h"], int) and data["borrow_count_24h"] >= 0


# ---------------------------------------------------------------------------
# Rental
# ---------------------------------------------------------------------------


def assert_rental(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["user_id"])
    assert is_valid_uuid(data["start_cabinet_id"])
    assert isinstance(data["start_slot_index"], int)
    assert is_valid_uuid(data["device_id"])
    assert is_iso8601_timestamp(data["rented_at"])
    assert data["rental_status"] in {
        "ACTIVE",
        "OVERDUE",
        "STUCK",
        "RETURNED",
        "LOST",
    }
    assert data["payment_status"] in {
        "PENDING",
        "BILLED",
        "REFUNDED",
        "DEPOSIT_DEDUCTED",
    }
    if data.get("return_cabinet_id") is not None:
        assert is_valid_uuid(data["return_cabinet_id"])
    if data.get("returned_at") is not None:
        assert is_iso8601_timestamp(data["returned_at"])
    if data.get("charged_amount") is not None:
        assert_cost_precision(data["charged_amount"])
    if data.get("refund_amount") is not None:
        assert_cost_precision(data["refund_amount"])


# ---------------------------------------------------------------------------
# RepairTicket
# ---------------------------------------------------------------------------


def assert_repair_ticket(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["target_type"] in {"DEVICE", "CABINET"}
    assert is_valid_uuid(data["target_id"])
    assert data["source"] in {"USER_REPORTED", "AUTO_ANOMALY", "OPERATOR_REPORTED"}
    assert data["issue_code"] in {
        "ABNORMAL_BATTERY",
        "CHARGING_FAILURE",
        "PHYSICAL_DAMAGE",
        "STUCK_DEVICE",
        "OFFLINE_CABINET",
    }
    assert data["status"] in {
        "OPEN",
        "ASSIGNED",
        "IN_PROGRESS",
        "ON_HOLD",
        "RESOLVED",
        "CANCELLED",
    }
    op = data.get("assigned_operator_id")
    assert op is None or isinstance(op, str)


# ---------------------------------------------------------------------------
# OperatorTask
# ---------------------------------------------------------------------------


def assert_operator_task(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["cabinet_id"])
    assert data["task_type"] in {
        "REPLENISHMENT",
        "MAINTENANCE_SWAP",
        "REPAIR_DISPATCH",
    }
    assert isinstance(data["priority_score"], int)
    assert data["status"] in {
        "PENDING",
        "ASSIGNED",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
    }
    op = data.get("assigned_operator_id")
    assert op is None or isinstance(op, str)
    linked = data.get("linked_repair_ticket_id")
    assert linked is None or is_valid_uuid(linked)


# ---------------------------------------------------------------------------
# LocationPartner
# ---------------------------------------------------------------------------


def assert_location_partner(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["partner_code"], str) and data["partner_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert 0.0 <= data["revenue_share_pct"] <= 1.0


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


def assert_settlement(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["location_partner_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert_cost_precision(data["gross_revenue"])
    assert_cost_precision(data["partner_amount"])
    assert_cost_precision(data["refund_adjustment"])
    assert data["status"] in {"DRAFT", "APPROVED", "INVOICED", "CANCELLED"}
    inv = data.get("invoice_number")
    assert inv is None or isinstance(inv, str)


# ---------------------------------------------------------------------------
# PaymentEvent (no updated_at, no version)
# ---------------------------------------------------------------------------


def assert_payment_event(data: Dict[str, Any]) -> None:
    _assert_payment_event_common_fields(data)
    assert isinstance(data["idempotency_key"], str) and data["idempotency_key"]
    assert data["event_type"] in {
        "PAYMENT_CONFIRMED",
        "PAYMENT_FAILED",
        "REFUND_CONFIRMED",
    }
    assert is_valid_uuid(data["rental_id"])
    assert_cost_precision(data["amount"])
    assert is_iso8601_timestamp(data["occurred_at"])


# ---------------------------------------------------------------------------
# MaintenanceWindow
# ---------------------------------------------------------------------------


def assert_maintenance_window(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["cabinet_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in {"SCHEDULED", "CANCELLED"}


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------


def assert_money_equal(actual: float, expected: float) -> None:
    """Assert two monetary values match at 2dp tolerance (PRD §2.6)."""
    assert actual == pytest.approx(expected, abs=0.005), (
        f"Expected {expected!r}, got {actual!r}"
    )
    assert_cost_precision(actual)
