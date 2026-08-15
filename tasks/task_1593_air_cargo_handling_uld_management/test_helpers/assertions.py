"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9, §3)."""
from datetime import datetime, timezone

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _parse_instant(value: str) -> datetime:
    assert isinstance(value, str), f"Expected ISO timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_timestamp_instant(actual: str, expected_iso: str) -> None:
    """Assert two ISO 8601 instants denote the same moment (format-tolerant)."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}"
    )


def assert_money(actual, expected: float) -> None:
    """Assert a 2dp monetary/weight figure equals the expected literal."""
    assert isinstance(actual, (int, float)), f"Expected numeric amount, got {actual!r}"
    assert float(actual) == pytest.approx(float(expected), abs=1e-4), (
        f"Expected {expected}, got {actual}"
    )
    assert_cost_precision(float(actual))


def assert_common_fields(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_flight(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["flight_number"], str) and data["flight_number"]
    assert isinstance(data["origin"], str) and data["origin"]
    assert isinstance(data["destination"], str) and data["destination"]
    assert is_iso8601_timestamp(data["scheduled_departure"])
    assert is_iso8601_timestamp(data["scheduled_arrival"])
    assert isinstance(data["max_payload_kg"], (int, float))
    assert isinstance(data["max_volume_m3"], (int, float))
    assert isinstance(data["uld_position_count"], int)
    assert isinstance(data["dg_certified"], bool)
    assert isinstance(data["allocated_weight_kg"], (int, float))
    assert isinstance(data["allocated_volume_m3"], (int, float))
    assert isinstance(data["reserved_positions"], int)
    assert data.get("weight_restriction_kg") is None or isinstance(
        data["weight_restriction_kg"], (int, float)
    )
    assert data["status"] in ("SCHEDULED", "OPEN_FOR_BOOKING", "CLOSED", "DEPARTED")


def assert_booking(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["flight_id"], str) and data["flight_id"]
    assert isinstance(data["shipper_ref"], str) and data["shipper_ref"]
    assert isinstance(data["commodity_code"], str) and data["commodity_code"]
    assert isinstance(data["pieces"], int) and data["pieces"] >= 1
    assert isinstance(data["gross_weight_kg"], (int, float))
    assert data["gross_weight_kg"] > 0
    assert isinstance(data["volume_m3"], (int, float)) and data["volume_m3"] > 0
    assert isinstance(data["chargeable_weight_kg"], (int, float))
    assert isinstance(data["temp_excursion_count"], int)
    assert data["temp_status"] in ("NOT_MONITORED", "IN_RANGE", "EXCURSION")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data["status"] in (
        "REQUESTED",
        "ACCEPTED",
        "BUILT_UP",
        "OFFLOADED",
        "LOADED",
        "REJECTED",
        "CANCELLED",
    )


def assert_uld_type(data: dict) -> None:
    """ULDType is lightweight: only id and created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "ULDType must not carry updated_at"
    assert "version" not in data, "ULDType must not carry version"
    assert isinstance(data["type_code"], str) and data["type_code"]
    assert isinstance(data["tare_weight_kg"], (int, float))
    assert isinstance(data["max_gross_weight_kg"], (int, float))
    assert isinstance(data["internal_volume_m3"], (int, float))


def assert_uld(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["uld_code"], str) and data["uld_code"]
    assert isinstance(data["uld_type_id"], str) and data["uld_type_id"]
    assert data["status"] in (
        "SERVICEABLE",
        "ASSIGNED",
        "DISPATCHED",
        "RETURNED",
        "DAMAGE_REPORTED",
    )
    assert data.get("dispatched_at") is None or isinstance(data["dispatched_at"], str)
    assert data.get("returned_at") is None or isinstance(data["returned_at"], str)


def assert_build_up_plan(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["flight_id"], str) and data["flight_id"]
    assert isinstance(data["uld_id"], str) and data["uld_id"]
    assert isinstance(data["build_start"], str)
    assert isinstance(data["build_end"], str)
    assert isinstance(data["total_weight_kg"], (int, float))
    assert data["status"] in ("DRAFT", "SEALED", "DEPARTED", "CANCELLED")


def assert_dg_declaration(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["booking_id"], str) and data["booking_id"]
    assert isinstance(data["un_number"], str) and data["un_number"]
    assert isinstance(data["dg_class"], str) and data["dg_class"]
    assert data["packing_group"] in ("I", "II", "III")
    assert isinstance(data["declaration_doc_ref"], str)
    assert data["status"] in ("PENDING_CHECK", "ACCEPTED", "REJECTED")


def assert_temperature_log(data: dict) -> None:
    """TemperatureLog is lightweight: only id and created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "TemperatureLog must not carry updated_at"
    assert "version" not in data, "TemperatureLog must not carry version"
    assert isinstance(data["booking_id"], str) and data["booking_id"]
    assert isinstance(data["recorded_at"], str)
    assert isinstance(data["temperature_c"], (int, float))
    assert isinstance(data["in_range"], bool)


def assert_customs_hold(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["booking_id"], str) and data["booking_id"]
    assert isinstance(data["reason_code"], str) and data["reason_code"]
    assert isinstance(data["placed_at"], str)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_claim(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["booking_id"], str) and data["booking_id"]
    assert data["claim_type"] in ("DAMAGE", "LOSS")
    assert isinstance(data["claimed_amount"], (int, float))
    assert data["claimed_amount"] > 0
    assert isinstance(data["items"], list) and len(data["items"]) >= 1
    assert data["status"] in ("SUBMITTED", "APPROVED", "SETTLED", "REJECTED")


def assert_uld_charge(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["uld_id"], str) and data["uld_id"]
    assert data["charge_type"] in ("DEMURRAGE", "REPAIR")
    assert isinstance(data["amount"], (int, float))
    assert data["status"] in ("PROVISIONAL", "FINALIZED")
