"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

VEHICLE_TYPES = ["PLOW", "SPREADER", "COMBO"]
VEHICLE_STATUSES = ["AVAILABLE", "ASSIGNED", "OUT_OF_SERVICE"]
OPERATIONAL_STATUSES = ["PLANNED", "ACTIVE", "CLOSED"]
BILLING_STATUSES = ["OPEN", "FINALIZED"]
ASSIGNMENT_STATUSES = ["PLANNED", "IN_PROGRESS", "COMPLETED", "SUPERSEDED", "CANCELLED"]
APPLICATION_STATUSES = ["RECORDED", "VOIDED"]
CALLOUT_STATUSES = ["ISSUED", "COMPLETED", "CANCELLED"]
COMPLAINT_STATUSES = ["OPEN", "INVESTIGATING", "RESOLVED", "REOPENED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_common_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_depot(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["name"], str)
    assert data["salt_tons_on_hand"] >= 0, "salt_tons_on_hand must be >= 0"
    assert data["brine_gallons_on_hand"] >= 0, "brine_gallons_on_hand must be >= 0"


def assert_vehicle(data: dict):
    _assert_common_versioned(data)
    assert data["vehicle_type"] in VEHICLE_TYPES
    assert data["status"] in VEHICLE_STATUSES
    assert isinstance(data["has_spreader"], bool)


def assert_operator(data: dict):
    _assert_common_versioned(data)
    assert data["hourly_rate_cents"] > 0
    assert data["cdl_class"] in ["A", "B", "C"]


def assert_route(data: dict):
    _assert_common_versioned(data)
    assert data["tier"] in ["ARTERIAL", "RESIDENTIAL"]
    assert data["lane_miles"] > 0


def assert_storm_event(data: dict):
    _assert_common_versioned(data)
    assert data["operational_status"] in OPERATIONAL_STATUSES
    assert data["billing_status"] in BILLING_STATUSES
    assert data["severity"] in ["LIGHT", "MODERATE", "SEVERE", "EMERGENCY"]


def assert_route_assignment(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ASSIGNMENT_STATUSES
    assert data["assignment_type"] in ["PRETREAT", "PLOWING"]


def assert_material_application(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in APPLICATION_STATUSES
    assert data["material_type"] in ["SALT", "BRINE"]


def assert_callout(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in CALLOUT_STATUSES


def assert_complaint(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in COMPLAINT_STATUSES
    assert isinstance(data["missed_street_confirmed"], bool)


def assert_cost_report(data: dict):
    """Cost report is an immutable snapshot: id + created_at only (no updated_at/version)."""
    _assert_common(data)
    assert "updated_at" not in data or data.get("updated_at") is None, \
        "CostReport must not carry updated_at"
    assert "version" not in data or data.get("version") is None, \
        "CostReport must not carry version"
    assert data["variant"] in ["ESTIMATE", "ACTUAL"]
    assert data["total_cost_cents"] == data["total_material_cost_cents"] + data["total_labor_cost_cents"], \
        "total_cost_cents must equal material + labor"
