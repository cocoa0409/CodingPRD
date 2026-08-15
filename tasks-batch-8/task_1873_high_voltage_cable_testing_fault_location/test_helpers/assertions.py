"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_same_instant(actual, expected_iso: str):
    """The stored timestamp must denote the supplied instant. PRD pins the
    three-fractional-digit format only for server-generated timestamps
    (`api_request_timestamp` §2.2, `created_at` §2.5); the serialization of
    client-supplied bounds is unstated, so compare instants, not strings."""
    assert isinstance(actual, str) and is_iso8601_timestamp(actual), (
        f"expected an ISO 8601 timestamp, got {actual!r}"
    )
    a = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    e = datetime.fromisoformat(expected_iso.replace("Z", "+00:00"))
    assert a == e, f"{actual!r} does not denote the same instant as {expected_iso!r}"


def _assert_common_fields(data: dict, entity: str):
    """Every persisted resource except test readings carries id, created_at,
    updated_at and version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_circuit(data: dict):
    _assert_common_fields(data, "CableCircuit")
    assert isinstance(data["circuit_ref"], str) and len(data["circuit_ref"]) > 0
    assert data["voltage_class"] in ["KV_15", "KV_25", "KV_35", "KV_69"]
    assert isinstance(data["length_m"], int) and data["length_m"] > 0
    assert 1950 <= data["installation_year"] <= 2026
    assert data["status"] in [
        "IN_SERVICE", "OUTAGE_PENDING", "DE_ENERGIZED", "GROUNDED",
        "UNDER_TEST", "TEST_COMPLETE", "RESTORING",
    ]
    assert isinstance(data["unresolved_fault_count"], int)
    assert isinstance(data["resolved_fault_count_24m"], int)
    assert isinstance(data["approved_outage_minutes_total"], int)
    assert isinstance(data["splice_count"], int)
    assert isinstance(data["replacement_recommended"], bool)


def assert_outage_window(data: dict):
    _assert_common_fields(data, "OutageWindow")
    assert data["kind"] in ["PLANNED_DIAGNOSTIC", "EMERGENCY_FAULT", "REPAIR_RESTORE"]
    assert data["status"] in ["REQUESTED", "APPROVED", "ACTIVE", "CLOSED", "CANCELLED"]
    assert isinstance(data["duration_minutes"], int)
    assert isinstance(data["overrun_minutes"], int)
    assert isinstance(data["overrun_charge_cents"], int)
    assert isinstance(data["estimated_charge_cents"], int)


def assert_test_job(data: dict):
    _assert_common_fields(data, "TestJob")
    assert isinstance(data["requested_methods"], list) and len(data["requested_methods"]) > 0
    for m in data["requested_methods"]:
        assert m in ["VLF_TAN_DELTA", "VLF_WITH_PD", "PD_MAPPING"]
    assert isinstance(data["approved_budget_cents"], int) and data["approved_budget_cents"] > 0
    assert isinstance(data["committed_cost_cents"], int)
    assert data["status"] in [
        "DRAFT", "PLANNED", "IN_PROGRESS", "SUSPENDED",
        "EVALUATION", "COMPLETED", "ABORTED",
    ]


def assert_isolation_permit(data: dict):
    _assert_common_fields(data, "IsolationPermit")
    assert isinstance(data["isolation_points"], list) and len(data["isolation_points"]) >= 1
    assert isinstance(data["ground_count"], int) and data["ground_count"] >= 1
    assert data["status"] in ["DRAFT", "ISSUED", "GROUNDING_VERIFIED", "RELEASED"]


def assert_test_series(data: dict):
    _assert_common_fields(data, "TestSeries")
    assert data["method"] in ["VLF_TAN_DELTA", "VLF_WITH_PD", "PD_MAPPING"]
    assert isinstance(data["step_count"], int)
    assert data["status"] in ["SETUP", "ENERGIZING", "LOGGING", "EVALUATED", "ACCEPTED", "INVALID"]


def assert_test_reading(data: dict):
    """Test readings are the append-only exception (PRD §2.5): they carry only
    id and created_at — version and updated_at must be absent."""
    assert is_valid_uuid(data.get("id", "")), "TestReading.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "TestReading.created_at must be ISO 8601"
    assert "version" not in data, "TestReading must not carry a version field"
    assert "updated_at" not in data, "TestReading must not carry an updated_at field"
    assert isinstance(data["step_index"], int)
    assert isinstance(data["ambient_temp_c"], (int, float))


def assert_fault_record(data: dict):
    _assert_common_fields(data, "FaultRecord")
    assert data["status"] in [
        "SUSPECTED", "PINPOINTED", "EXCAVATING", "REPAIRING",
        "REPAIRED", "RETESTING", "CLOSED_VERIFIED", "REOPENED",
    ]


def assert_excavation_order(data: dict):
    _assert_common_fields(data, "ExcavationOrder")
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] > 0
    assert data["status"] in ["DRAFT", "PERMITTED", "IN_PROGRESS", "BACKFILLED", "CANCELLED"]


def assert_repair_splice(data: dict):
    _assert_common_fields(data, "RepairSplice")
    assert data["splice_type"] in ["HEAT_SHRINK", "COLD_SHRINK", "PREMOLDED"]
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] > 0
    assert data["status"] in ["PLANNED", "SPLICING", "CURING", "COMPLETED", "ACCEPTED", "REJECTED"]


def assert_mobile_unit(data: dict):
    _assert_common_fields(data, "MobileUnit")
    assert isinstance(data["unit_code"], str) and len(data["unit_code"]) > 0
    assert isinstance(data["capabilities"], list) and len(data["capabilities"]) > 0
    for c in data["capabilities"]:
        assert c in ["VLF", "PD", "TDR"]
    assert data["status"] in ["AVAILABLE", "ASSIGNED", "MAINTENANCE"]
    assert isinstance(data["committed_hours"], (int, float))


def assert_equipment_assignment(data: dict):
    _assert_common_fields(data, "EquipmentAssignment")
    assert data["status"] in ["RESERVED", "CONFIRMED", "ACTIVE", "RELEASED", "CANCELLED"]
    assert isinstance(data["duration_hours"], (int, float))


def assert_health_assessment(data: dict):
    _assert_common_fields(data, "HealthAssessment")
    assert data["basis"] in ["FORMAL", "PROVISIONAL"]
    assert data["status"] in ["COMPUTED", "REVIEWED", "ADOPTED", "SUPERSEDED"]
    assert isinstance(data["health_index_score"], (int, float))
    assert 0.0 <= data["health_index_score"] <= 100.0
    assert data["band"] in ["GOOD", "FAIR", "POOR", "CRITICAL"]
    assert data["recommended_action"] in [
        "NONE", "MONITOR", "PLAN_REPLACEMENT", "URGENT_REPLACEMENT",
    ]


def assert_circuit_counters_invariant(data: dict):
    """Circuit counters are non-negative (PRD §3.1: counters start at zero and
    move only through fault/window/splice lifecycle events)."""
    assert data["unresolved_fault_count"] >= 0
    assert data["resolved_fault_count_24m"] >= 0
    assert data["approved_outage_minutes_total"] >= 0
    assert data["splice_count"] >= 0
