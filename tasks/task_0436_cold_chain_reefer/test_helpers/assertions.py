"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

REEFER_UNIT_STATUSES = ["AVAILABLE", "ASSIGNED", "IN_TRANSIT", "RETIRED"]
SHIPMENT_STATUSES = ["TENDERED", "ACCEPTED", "PRECOOLED", "IN_TRANSIT",
                     "DELIVERED", "REJECTED", "CANCELLED"]
CARGO_CLASSES = ["FOOD", "PHARMA", "GENERAL"]
POSTURES = ["INTACT", "AT_RISK", "COMPROMISED"]
IMPAIRMENTS = ["NONE", "PARTIAL", "TOTAL_LOSS"]
SPOILAGE_STATUSES = ["SOUND", "IMPAIRED", "SPOILED"]
READING_KINDS = ["TEMP", "DOOR_OPEN", "PRECOOL"]
CLAIM_STATUSES = ["FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "WITHDRAWN"]
STOP_KINDS = ["PICKUP", "DELIVERY"]
STOP_STATUSES = ["SCHEDULED", "ARRIVED", "CLOSED"]


def _assert_common_mutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID with no prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an int >= 1"


def assert_carrier(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["fsma_registered"], bool)
    assert isinstance(data["sanitary_training_current"], bool)
    assert isinstance(data["liability_cap_cents"], int) and data["liability_cap_cents"] >= 0


def assert_reefer_unit(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["carrier_id"]), "carrier_id must be a UUID"
    assert isinstance(data["asset_tag"], str) and len(data["asset_tag"]) > 0
    assert isinstance(data["compartment_count"], int) and 1 <= data["compartment_count"] <= 4
    assert data["status"] in REEFER_UNIT_STATUSES


def assert_temp_lane(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["setpoint_min_c"], (int, float))
    assert isinstance(data["setpoint_max_c"], (int, float))
    assert data["setpoint_max_c"] >= data["setpoint_min_c"]
    assert isinstance(data["regulated"], bool)
    assert isinstance(data["tolerance_degree_minutes"], int)


def assert_shipment(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["shipper_user_id"], str) and len(data["shipper_user_id"]) > 0
    assert is_valid_uuid(data["carrier_id"]), "carrier_id must be a UUID"
    assert data["reefer_unit_id"] is None or is_valid_uuid(data["reefer_unit_id"])
    assert data["cargo_class"] in CARGO_CLASSES
    assert data["status"] in SHIPMENT_STATUSES
    assert data["load_integrity_posture"] in POSTURES
    assert isinstance(data["precool_verified"], bool)
    assert isinstance(data["total_detention_fee_cents"], int) and data["total_detention_fee_cents"] >= 0
    assert isinstance(data["total_lumper_fee_cents"], int) and data["total_lumper_fee_cents"] >= 0


def assert_compartment(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["shipment_id"]), "shipment_id must be a UUID"
    assert is_valid_uuid(data["temp_lane_id"]), "temp_lane_id must be a UUID"
    assert isinstance(data["ordinal"], int) and data["ordinal"] >= 1
    assert isinstance(data["door_open_events"], int) and data["door_open_events"] >= 0
    assert isinstance(data["degree_minutes_out"], (int, float)) and data["degree_minutes_out"] >= 0
    assert data["impairment"] in IMPAIRMENTS


def assert_product_lot(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["compartment_id"]), "compartment_id must be a UUID"
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["pallet_count"], int) and data["pallet_count"] >= 0
    assert isinstance(data["declared_value_cents"], int) and data["declared_value_cents"] >= 0
    assert data["spoilage_status"] in SPOILAGE_STATUSES


def assert_spoilage_claim(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["shipment_id"]), "shipment_id must be a UUID"
    assert isinstance(data["filed_by_user_id"], str) and len(data["filed_by_user_id"]) > 0
    assert data["status"] in CLAIM_STATUSES
    assert isinstance(data["claimed_value_cents"], int) and data["claimed_value_cents"] >= 0
    assert isinstance(data["approved_payout_cents"], int) and data["approved_payout_cents"] >= 0


def assert_stop_event(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["shipment_id"]), "shipment_id must be a UUID"
    assert data["kind"] in STOP_KINDS
    assert isinstance(data["appointment_min"], int) and data["appointment_min"] >= 0
    assert data["status"] in STOP_STATUSES
    assert isinstance(data["detention_fee_cents"], int) and data["detention_fee_cents"] >= 0
    assert isinstance(data["lumper_fee_cents"], int) and data["lumper_fee_cents"] >= 0


def assert_sensor_reading(data: dict):
    """Append-only telemetry event: ONLY id + created_at among the common fields."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID with no prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in READING_KINDS
    assert is_valid_uuid(data["compartment_id"]), "compartment_id must be a UUID"
    assert isinstance(data["offset_min"], int) and data["offset_min"] >= 0
    assert isinstance(data["excursion_flagged"], bool)
    # Append-only — no updated_at / version surfaced.
    assert "updated_at" not in data, "SensorReading must not carry updated_at"
    assert "version" not in data, "SensorReading must not carry version"
