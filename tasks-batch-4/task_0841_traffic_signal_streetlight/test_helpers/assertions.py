"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_intersection(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["district"], str)
    assert data["operational_posture"] in ["NORMAL", "DEGRADED", "EMERGENCY"]
    assert isinstance(data["active_plan_revision"], int)
    assert isinstance(data["active_cycle_length_sec"], int)
    assert isinstance(data["active_offset_sec"], int)


def assert_pole(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str)
    assert data["status"] in ["STANDING", "DOWN"]
    assert isinstance(data["load_capacity_units"], int)
    assert isinstance(data["committed_load_units"], int)
    assert isinstance(data["available_load_units"], int)
    assert data["committed_load_units"] + data["available_load_units"] == data["load_capacity_units"], \
        "committed + available must equal capacity"


def assert_device(data: dict):
    _assert_common(data)
    assert data["device_type"] in [
        "SIGNAL_CONTROLLER", "SIGNAL_HEAD", "PED_SIGNAL", "DETECTOR", "STREETLIGHT"]
    assert data["criticality"] in ["CRITICAL", "STANDARD", "LOW"]
    assert data["status"] in [
        "IN_SERVICE", "OUT_OF_SERVICE", "UNDER_MAINTENANCE", "KNOCKED_DOWN", "DECOMMISSIONED"]
    assert isinstance(data["replacement_cost"], (int, float))


def assert_crew(data: dict):
    _assert_common(data)
    assert data["specialty"] in ["SIGNAL", "LIGHTING", "LOCATE", "GENERAL"]
    assert isinstance(data["labor_capacity_hours"], (int, float))
    assert isinstance(data["committed_labor_hours"], (int, float))
    assert isinstance(data["available_labor_hours"], (int, float))
    assert abs((data["committed_labor_hours"] + data["available_labor_hours"])
               - data["labor_capacity_hours"]) < 1e-9, \
        "committed + available must equal capacity"


def assert_pole_attachment(data: dict):
    _assert_common(data)
    assert data["mount_zone"] in ["LOW", "MID", "HIGH"]
    assert data["status"] in ["REQUESTED", "APPROVED", "DENIED", "REVOKED"]
    assert isinstance(data["load_units"], int)


def assert_ticket(data: dict):
    _assert_common(data)
    assert data["source"] in ["SRC_311", "DETECTOR", "KNOCKDOWN"]
    assert 1 <= data["reported_severity"] <= 5
    assert data["status"] in ["OPEN", "TRIAGED", "IN_PROGRESS", "RESOLVED", "CLOSED"]
    assert data["sla_response_status"] in ["PENDING", "ON_TRACK", "BREACHED"]
    assert isinstance(data["reopen_count"], int)


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["work_type"] in [
        "REPAIR", "PM_LAMP", "LED_REPLACEMENT", "EXCAVATION", "EMERGENCY"]
    assert data["status"] in ["DRAFT", "SCHEDULED", "DISPATCHED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["estimated_labor_hours"], (int, float))


def assert_timing_change_request(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED", "APPROVED", "REJECTED", "SUSPENDED"]
    assert isinstance(data["revision_count"], int)


def assert_locate_request(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "MARKED", "CLEARED"]


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED"]
    if data.get("coverage_variant") is not None:
        assert data["coverage_variant"] in ["FULL", "PRORATED"]
    if data.get("payout_amount") is not None:
        assert_cost_precision(data["payout_amount"])
