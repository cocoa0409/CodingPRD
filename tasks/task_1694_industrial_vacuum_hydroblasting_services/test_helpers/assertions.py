"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssignmentStatus,
    ContainmentStatus,
    CreditStatus,
    DowntimeCause,
    DowntimeStatus,
    ExecutionStatus,
    FacilityPosture,
    Hazard,
    HazardClass,
    IncidentSeverity,
    IncidentStatus,
    InvoiceStatus,
    JhaStatus,
    JobType,
    ManifestStatus,
    PermitStatus,
    PermitType,
    PricingMode,
    ResourceKind,
    SafetyStatus,
    UnitType,
    VarianceBasis,
    WasteProfileStatus,
    WaterSource,
    RateScheduleStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_site(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["credit_status"] in {e.value for e in CreditStatus}
    assert "active_rate_schedule_id" in data


def assert_rate_schedule(data: dict):
    _assert_common(data)
    assert data["status"] in {e.value for e in RateScheduleStatus}
    for field in (
        "vacuum_per_gallon_cents",
        "hydroblast_per_foot_cents",
        "labor_rate_cents_per_hour",
        "equipment_rate_cents_per_hour",
        "standby_rate_cents_per_hour",
        "minimum_invoice_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be int"
    assert data["minimum_invoice_cents"] >= 0


def assert_job(data: dict):
    _assert_common(data)
    assert data["job_type"] in {e.value for e in JobType}
    assert data["pricing_mode"] in {e.value for e in PricingMode}
    assert data["execution_status"] in {e.value for e in ExecutionStatus}
    assert data["safety_status"] in {e.value for e in SafetyStatus}
    assert is_valid_uuid(data.get("pinned_rate_schedule_id", "")), (
        "pinned_rate_schedule_id must be a UUID"
    )


def assert_jha(data: dict):
    _assert_common(data)
    assert data["status"] in {e.value for e in JhaStatus}
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert isinstance(data["confined_space"], bool)
    assert isinstance(data["hazards"], list)
    for hazard in data["hazards"]:
        assert hazard in {e.value for e in Hazard}
    if data.get("water_source") is not None:
        assert data["water_source"] in {e.value for e in WaterSource}


def assert_permit(data: dict):
    _assert_common(data)
    assert data["permit_type"] in {e.value for e in PermitType}
    assert data["status"] in {e.value for e in PermitStatus}
    assert isinstance(data["space_id"], str) and data["space_id"]


def assert_equipment_unit(data: dict):
    _assert_common(data)
    assert data["unit_type"] in {e.value for e in UnitType}
    assert isinstance(data["max_pressure_psi"], int)
    assert isinstance(data["tank_capacity_gal"], int)


def assert_operator(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["hydroblast_certified"], bool)
    assert isinstance(data["hazwoper_expires_on"], str)


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["resource_kind"] in {e.value for e in ResourceKind}
    assert data["status"] in {e.value for e in AssignmentStatus}
    assert isinstance(data["window_hours"], (int, float))
    if data["resource_kind"] == ResourceKind.EQUIPMENT.value:
        assert data.get("equipment_unit_id"), "EQUIPMENT assignment needs equipment_unit_id"
    else:
        assert data.get("operator_id"), "OPERATOR assignment needs operator_id"


def assert_waste_profile(data: dict):
    _assert_common(data)
    assert data["hazard_class"] in {e.value for e in HazardClass}
    assert data["variance_basis"] in {e.value for e in VarianceBasis}
    assert data["status"] in {e.value for e in WasteProfileStatus}
    assert isinstance(data["disposal_rate_per_ton_cents"], int)


def assert_disposal_facility(data: dict):
    _assert_common(data)
    assert data["posture"] in {e.value for e in FacilityPosture}
    assert isinstance(data["reserved_tons"], (int, float))
    assert isinstance(data["total_capacity_tons"], (int, float))
    assert data["reserved_tons"] >= 0


def assert_manifest(data: dict):
    _assert_common(data)
    assert data["status"] in {e.value for e in ManifestStatus}
    assert isinstance(data["estimated_gallons"], int)


def assert_containment_record(data: dict):
    _assert_common(data)
    assert data["status"] in {e.value for e in ContainmentStatus}
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert data["water_used_gallons"] > 0
    assert data["water_captured_gallons"] >= 0
    assert isinstance(data["capture_ratio"], (int, float))


def assert_downtime_event(data: dict):
    _assert_common(data)
    assert data["cause"] in {e.value for e in DowntimeCause}
    assert data["status"] in {e.value for e in DowntimeStatus}
    assert isinstance(data["closure_day"], str) and len(data["closure_day"]) == 10


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in {e.value for e in InvoiceStatus}
    assert isinstance(data["invoice_number"], str) and data["invoice_number"]
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert isinstance(line["line_id"], str) and line["line_id"].startswith("L")
        assert isinstance(line["amount_cents"], int)
        assert isinstance(line["discountable"], bool)
        assert isinstance(line["voided"], bool)
    # Totals invariant: subtotal - discount + env fee == total
    assert (
        data["subtotal_cents"] - data["discount_cents"] + data["environmental_fee_cents"]
        == data["total_cents"]
    ), (
        f"Invoice totals invariant violated: {data['subtotal_cents']} - "
        f"{data['discount_cents']} + {data['environmental_fee_cents']} != "
        f"{data['total_cents']}"
    )


def assert_incident(data: dict):
    _assert_common(data)
    assert data["severity"] in {e.value for e in IncidentSeverity}
    assert data["status"] in {e.value for e in IncidentStatus}
    assert isinstance(data["title"], str) and data["title"]
