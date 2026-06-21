"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_log_common(data: dict):
    """Append-only logs carry only id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_festival(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["total_days"], int) and data["total_days"] >= 1
    assert data["operational_posture"] in (
        "PLANNING", "ON_SALE", "LIVE", "SUSPENDED", "CLOSED", "CANCELLED"
    )
    assert isinstance(data["current_festival_day"], int)
    assert isinstance(data["max_reentries"], int)
    assert data["total_wallet_liability"] >= 0
    assert_cost_precision(data["total_wallet_liability"])
    assert data["total_refund_liability"] >= 0
    assert_cost_precision(data["total_refund_liability"])


def assert_zone(data: dict):
    _assert_common(data)
    assert data["code"] in ("A", "B", "C")
    assert isinstance(data["slot_capacity"], int) and data["slot_capacity"] >= 1
    assert isinstance(data["allocated_count"], int) and data["allocated_count"] >= 0


def assert_stage(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["changeover_minutes"], int) and data["changeover_minutes"] >= 0


def assert_parking_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["sold_count"], int) and data["sold_count"] >= 0
    assert_cost_precision(data["price_per_pass"])


def assert_camping_area(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["sold_count"], int) and data["sold_count"] >= 0
    assert_cost_precision(data["price_per_night"])


def assert_ticket(data: dict):
    _assert_common(data)
    assert data["ticket_type"] in ("GA", "VIP")
    assert isinstance(data["day_count"], int) and data["day_count"] >= 1
    assert_cost_precision(data["face_value"])
    assert data["status"] in ("SOLD", "ACTIVATED", "REFUNDED", "VOID")


def assert_wristband(data: dict):
    _assert_common(data)
    assert isinstance(data["rfid_uid"], str) and len(data["rfid_uid"]) > 0
    assert data["lifecycle_status"] in ("ISSUED", "ACTIVE", "FROZEN", "CLOSED", "VOID")
    assert data["presence_status"] in ("OUTSIDE", "INSIDE")
    assert data["balance"] >= 0
    assert_cost_precision(data["balance"])
    assert isinstance(data["entry_count"], int) and data["entry_count"] >= 0
    assert isinstance(data["reentry_used"], int) and data["reentry_used"] >= 0


def assert_vendor_application(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "CONFIRMED", "REJECTED", "WITHDRAWN"
    )
    assert data["booth_tier"] in ("STANDARD", "PREMIUM", "FOOD")
    assert isinstance(data["day_count"], int) and data["day_count"] >= 1
    if data.get("booth_fee") is not None:
        assert_cost_precision(data["booth_fee"])
    assert data["fee_paid"] >= 0


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert data["payout_total"] >= 0 or data["payout_total"] is not None
    assert_cost_precision(data["payout_total"])


def assert_performance(data: dict):
    _assert_common(data)
    assert isinstance(data["artist_name"], str) and len(data["artist_name"]) > 0
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_addon(data: dict):
    _assert_common(data)
    assert data["kind"] in ("PARKING", "CAMPING")
    assert_cost_precision(data["price"])
    assert data["status"] in ("SOLD", "REFUNDED")


def assert_refund(data: dict):
    _assert_common(data)
    assert data["refund_kind"] in ("WEATHER_PRORATA", "VOLUNTARY_TIERED")
    assert_cost_precision(data["amount"])
    assert_cost_precision(data["fee_withheld"])
    assert data["status"] == "ISSUED"


def assert_incident(data: dict):
    _assert_common(data)
    assert data["incident_type"] in ("LOST_CHILD", "MEDICAL")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["status"] in ("OPEN", "ESCALATED", "RESOLVED")


def assert_wallet_txn(data: dict):
    _assert_log_common(data)
    assert data["kind"] in ("TOPUP", "SPEND", "CASHOUT", "CASHOUT_FEE")
    assert_cost_precision(data["amount"])
    # Append-only log: no updated_at, no version expected.


def assert_gate_event(data: dict):
    _assert_log_common(data)
    assert data["direction"] in ("ENTER", "EXIT")
    assert data["outcome"] in ("ADMITTED", "EXITED", "DENIED")
