"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape of a returned resource against the
PRD's field contract. Money fields are whole-cent integers (PRD §2.7).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_station(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"], "name must be non-empty string"
    assert isinstance(data["state_code"], str), "state_code must be string"
    assert isinstance(data["certificate_serial_prefix"], str)
    assert isinstance(data["next_certificate_seq"], int)
    assert isinstance(data["repair_cost_limit_cents"], int)
    assert isinstance(data["analyzer_count"], int) and data["analyzer_count"] >= 1


def assert_vehicle_class_profile(data: dict):
    _assert_common(data)
    assert isinstance(data["station_id"], str)
    assert data["vehicle_class"] in ("PASSENGER", "LIGHT_TRUCK", "HEAVY_DUTY", "MOTORCYCLE")
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["obd_required"], bool)
    assert isinstance(data["checklist_item_count"], int) and data["checklist_item_count"] >= 1
    assert isinstance(data["reinspection_window_days"], int) and data["reinspection_window_days"] >= 0


def assert_lane(data: dict):
    _assert_common(data)
    assert isinstance(data["station_id"], str)
    assert isinstance(data["lane_number"], int) and data["lane_number"] >= 1
    assert isinstance(data["supports_obd"], bool)
    assert isinstance(data["turnaround_buffer_minutes"], int) and data["turnaround_buffer_minutes"] >= 0


def assert_analyzer_reservation(data: dict):
    _assert_common(data)
    assert isinstance(data["station_id"], str)
    assert isinstance(data["vehicle_vin"], str)
    assert data["status"] in ("HELD", "RELEASED")


def assert_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["lane_id"], str)
    assert isinstance(data["vehicle_vin"], str)
    assert data["vehicle_class"] in ("PASSENGER", "LIGHT_TRUCK", "HEAVY_DUTY", "MOTORCYCLE")
    assert data["kind"] in ("APPOINTMENT", "WALK_IN")
    assert data["status"] in ("BOOKED", "CHECKED_IN", "CONSUMED", "CANCELLED", "NO_SHOW")


def assert_inspection_record(data: dict):
    _assert_common(data)
    assert isinstance(data["vehicle_vin"], str)
    assert data["vehicle_class"] in ("PASSENGER", "LIGHT_TRUCK", "HEAVY_DUTY", "MOTORCYCLE")
    assert isinstance(data["reinspection_index"], int) and data["reinspection_index"] >= 0
    assert data["status"] in ("IN_PROGRESS", "PASSED", "FAILED", "ABORTED")
    assert data["safety_result"] in ("PENDING", "PASS", "FAIL")
    assert data["emissions_result"] in ("PENDING", "PASS", "FAIL", "NOT_APPLICABLE")
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["waiver_applied"], bool)


def assert_checklist_result(data: dict):
    _assert_common(data)
    assert isinstance(data["record_id"], str)
    assert isinstance(data["item_code"], str)
    assert data["outcome"] in ("PASS", "FAIL", "NA")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")


def assert_emissions_test(data: dict):
    _assert_common(data)
    assert isinstance(data["record_id"], str)
    assert data["protocol"] in ("OBD2_CAN", "OBD2_ISO", "OBD2_J1850")
    assert isinstance(data["dtc_count"], int) and data["dtc_count"] >= 0
    assert isinstance(data["readiness_monitors_incomplete"], int)
    assert isinstance(data["mil_on"], bool)
    assert data["result"] in ("PENDING", "PASS", "FAIL")


def assert_repair_order(data: dict):
    _assert_common(data)
    assert isinstance(data["record_id"], str)
    assert isinstance(data["shop_name"], str)
    assert isinstance(data["documented_cost_cents"], int) and data["documented_cost_cents"] >= 0
    assert isinstance(data["estimated_cost_cents"], int) and data["estimated_cost_cents"] >= 0
    assert isinstance(data["emissions_related"], bool)
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED")


def assert_waiver_request(data: dict):
    _assert_common(data)
    assert isinstance(data["record_id"], str)
    assert data["cost_basis"] in ("DOCUMENTED_ONLY", "DOCUMENTED_PLUS_ESTIMATED")
    assert isinstance(data["qualifying_spend_cents"], int)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED")


def assert_certificate(data: dict):
    _assert_common(data)
    assert isinstance(data["record_id"], str)
    assert isinstance(data["serial"], str) and data["serial"]
    assert isinstance(data["sticker_number"], str)
    assert data["status"] in ("ACTIVE", "VOID")


def assert_state_report_batch(data: dict):
    _assert_common(data)
    assert isinstance(data["station_id"], str)
    assert isinstance(data["period_label"], str)
    assert data["status"] in ("OPEN", "SUBMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    assert isinstance(data["total_reported_fee_cents"], int)


def assert_state_report_line(data: dict):
    """StateReportLine is immutable (PRD §2.4): id + created_at only,
    no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["batch_id"], str)
    assert isinstance(data["record_id"], str)
    assert data["reported_result"] in ("PASS", "FAIL")
    assert isinstance(data["fee_cents"], int)
