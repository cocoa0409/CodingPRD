"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def validate_instant_equal(actual, expected_iso: str):
    """Assert two ISO-8601 values denote the same UTC instant.

    PRD §2.5 pins the three-fractional-digit rendering only for the
    system-managed `created_at`/`updated_at` (and §2.2 for
    `api_request_timestamp`); domain instants such as `projected_harvest_at`,
    `harvested_at`, `last_passed_at`, and `next_sanitation_due_at` have no
    mandated string rendering, so equality is judged on the instant, not the
    wire format ("…T06:00:00Z" and "…T06:00:00.000Z" are the same instant).
    """
    def _parse(v):
        assert isinstance(v, str), f"expected ISO-8601 string, got {v!r}"
        s = v.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    assert _parse(actual) == _parse(expected_iso), \
        f"instant mismatch: {actual!r} denotes a different instant than {expected_iso!r}"


def _assert_common(data: dict, entity: str):
    assert isinstance(data, dict), f"{entity} payload must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_crop(data: dict):
    _assert_common(data, "Crop")
    assert data["crop_status"] in ("ACTIVE", "RETIRED")
    assert data["category"] in ("LEAFY_GREEN", "HERB", "FRUITING")


def assert_recipe(data: dict):
    _assert_common(data, "GrowRecipe")
    assert data["recipe_status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_water_loop(data: dict):
    _assert_common(data, "WaterLoop")
    assert data["posture"] in ("IN_SERVICE", "SANITATION_DUE", "SANITATION_IN_PROGRESS", "SANITATION_HOLD")


def assert_rack(data: dict):
    _assert_common(data, "Rack")
    assert data["rack_posture"] in ("OPERATING", "SANITATION_HOLD", "OUT_OF_SERVICE")
    assert isinstance(data["occupied_towers"], int)


def assert_tower(data: dict):
    _assert_common(data, "Tower")
    assert data["tower_status"] in ("IDLE", "ALLOCATED")
    assert isinstance(data["tower_index"], int)


def assert_batch(data: dict):
    _assert_common(data, "GrowBatch")
    assert data["production_status"] in (
        "PLANNED", "SEEDED", "GROWING", "AT_RISK", "HARVEST_READY",
        "HARVESTED", "PACKED", "FAILED", "CULLED",
    )
    assert data["safety_status"] in ("PENDING", "RELEASED", "CONDEMNED", "QUARANTINED")


def assert_tower_allocation(data: dict):
    _assert_common(data, "TowerAllocation")
    assert data["allocation_status"] in ("ACTIVE", "RELEASED")


def assert_sanitation_cycle(data: dict):
    _assert_common(data, "SanitationCycle")
    assert data["cycle_status"] in ("SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED", "CANCELED")


def assert_contract(data: dict):
    _assert_common(data, "RetailContract")
    assert data["contract_status"] in ("ACTIVE", "SUSPENDED", "TERMINATED", "COMPLETED")


def assert_shipment(data: dict):
    _assert_common(data, "Shipment")
    assert data["shipment_status"] in ("RESERVED", "PACKED", "SHIPPED", "CANCELED", "EXPIRED")


def assert_shipment_line(data: dict):
    _assert_common(data, "ShipmentLine")
    assert data["line_status"] in ("RESERVED", "PACKED", "SHORTED", "SHIPPED", "RELEASED")


def assert_worker(data: dict):
    _assert_common(data, "Worker")
    assert isinstance(data["certifications"], list)


def assert_labor_shift(data: dict):
    _assert_common(data, "LaborShift")
    assert data["shift_status"] in ("DRAFT", "PUBLISHED", "COMPLETED", "CANCELED")
    assert data["role_type"] in ("HARVEST_CREW", "PACK_CREW", "SANITATION_CREW")


def assert_shift_assignment(data: dict):
    _assert_common(data, "ShiftAssignment")
    assert data["assignment_status"] in ("ASSIGNED", "CONFIRMED", "RELEASED")


def assert_energy_reading(data: dict):
    """Append-only reading (PRD §2.5): id + created_at only; no updated_at/version."""
    assert isinstance(data, dict), "EnergyMeterReading payload must be an object"
    assert is_valid_uuid(data.get("id", "")), "EnergyMeterReading.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "EnergyMeterReading.created_at must be ISO 8601"
    assert "version" not in data, "EnergyMeterReading must not carry version"
    assert "updated_at" not in data, "EnergyMeterReading must not carry updated_at"


def assert_failure_report(data: dict):
    _assert_common(data, "FailureReport")
    assert data["report_status"] in ("REPORTED", "TRIAGED", "REPLANT_REQUESTED", "CLOSED")


def assert_replant_request(data: dict):
    _assert_common(data, "ReplantRequest")
    assert data["replant_status"] in ("QUEUED", "CONVERTED", "DROPPED")


def assert_rack_occupancy_invariant(rack: dict, active_allocation_count: int):
    """Rack.occupied_towers equals the live count of ACTIVE allocations (PRD §3.2)."""
    assert rack["occupied_towers"] == active_allocation_count, (
        f"occupied_towers {rack['occupied_towers']} != active allocations {active_allocation_count}"
    )
