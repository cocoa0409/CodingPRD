"""Entity assertions and domain invariant checkers (PRD §2.4 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_bus(data: dict):
    _assert_common(data)
    assert isinstance(data["fleet_number"], str) and data["fleet_number"]
    assert isinstance(data["vin"], str) and data["vin"]
    assert isinstance(data["model_year"], int)
    assert isinstance(data["odometer_miles"], int) and data["odometer_miles"] >= 0
    assert data["service_status"] in ("ACTIVE", "OVERHAUL_HOLD", "RETIRED")
    assert data["availability_status"] in (
        "AVAILABLE",
        "IN_SHOP",
        "HELD",
        "OUT_OF_SERVICE",
    )
    assert isinstance(data["hold_reasons"], list)
    assert data["pm_due_status"] in ("CURRENT", "DUE_SOON", "DUE", "OVERDUE")
    assert isinstance(data["total_maintenance_cost_cents"], int)


def assert_pm_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["level_a_interval_miles"], int)
    assert isinstance(data["level_b_interval_miles"], int)
    assert isinstance(data["level_c_interval_miles"], int)
    assert isinstance(data["tolerance_miles"], int)
    assert isinstance(data["calendar_interval_days"], int)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_mechanic(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["employee_ref"], str) and data["employee_ref"]
    assert data["employment_status"] in ("ACTIVE", "INACTIVE")


def assert_certification(data: dict):
    _assert_common(data)
    assert data["cert_type"] in (
        "ENGINE",
        "TRANSMISSION",
        "BRAKES",
        "ELECTRICAL",
        "HVAC",
        "EMISSIONS",
        "PM_INSPECTION",
        "QA_AUTHORITY",
    )
    assert data["status"] in ("VALID", "EXPIRING_SOON", "EXPIRED")


def assert_shift(data: dict):
    _assert_common(data)
    assert data["shift_type"] in ("AM", "PM", "NIGHT")
    assert data["status"] in ("DRAFT", "PUBLISHED", "LOCKED", "RECONCILED")
    assert data["coverage_status"] in ("FULL", "SHORT")
    assert isinstance(data["required_headcount"], dict)


def assert_shift_assignment(data: dict):
    _assert_common(data)
    assert data["role_in_shift"] in ("LEAD", "TECH", "QA")
    assert data["status"] in (
        "SCHEDULED",
        "CONFIRMED",
        "COMPLETED",
        "NO_SHOW",
        "REMOVED",
    )


def assert_part(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["part_class"] in ("CONSUMABLE", "REBUILDABLE_CORE", "EXPENDABLE")
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["quantity_on_hand"], int)
    assert isinstance(data["quantity_reserved"], int)
    assert data["stock_status"] in ("NORMAL", "LOW_STOCK", "BACKORDERED")


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["wo_type"] in (
        "PM_A",
        "PM_B",
        "PM_C",
        "CAMPAIGN",
        "CORRECTIVE",
        "EMISSIONS",
        "OVERHAUL",
    )
    assert data["priority"] in ("EMERGENCY", "URGENT", "ROUTINE", "ELECTIVE")
    assert data["status"] in (
        "DRAFT",
        "SCHEDULED",
        "IN_PROGRESS",
        "AWAITING_PARTS",
        "PENDING_QA",
        "REOPENED",
        "BLOCKED",
        "CLOSED",
        "CANCELLED",
    )
    assert isinstance(data["labor_entries"], list)
    for f in (
        "labor_total_cents",
        "parts_total_cents",
        "core_charges_accrued_cents",
        "core_credits_cents",
        "parts_net_cents",
        "total_cost_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be int cents, got {data.get(f)!r}"
    assert isinstance(data["qa_reject_count"], int)


def assert_part_line(data: dict):
    _assert_common(data)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["qty_issued"], int)
    assert data["issue_status"] in (
        "RESERVED",
        "ISSUED",
        "CONSUMED",
        "RETURNED",
        "RELEASED",
    )
    assert data["core_status"] in (
        "NONE",
        "CORE_PENDING",
        "CORE_LATE",
        "CORE_CREDITED",
        "CORE_REJECTED",
    )


def assert_defect_report(data: dict):
    _assert_common(data)
    assert data["severity"] in ("SAFETY_CRITICAL", "MAJOR", "MINOR")
    assert data["defect_code"] in (
        "ENGINE",
        "TRANSMISSION",
        "BRAKES",
        "ELECTRICAL",
        "HVAC",
        "FUEL_SYSTEM",
        "TIRE",
        "OTHER",
    )
    assert data["status"] in (
        "OPEN",
        "TRIAGED",
        "ROAD_CALL_DISPATCHED",
        "ON_SCENE",
        "SHOP_QUEUED",
        "WO_LINKED",
        "DEFERRED",
        "RESOLVED",
        "WITHDRAWN",
    )


def assert_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "COMPLETED", "CLOSED")
    assert isinstance(data["scope_bus_ids"], list)
    assert isinstance(data["buses_completed_count"], int)


def assert_mileage_fuel_log(data: dict):
    _assert_common(data)
    assert isinstance(data["odometer_end"], int)
    assert isinstance(data["fuel_gallons"], int)
    assert data["status"] in ("POSTED", "FLAGGED", "VOIDED")


def assert_emissions_inspection(data: dict):
    _assert_common(data)
    assert data["test_type"] in ("OPACITY", "OBD", "IDLE")
    assert data["result"] in ("PASS", "FAIL")
    assert data["status"] == "RECORDED"


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["claim_type"] in ("BASE_OEM", "EXTENDED", "PARTS_ONLY", "GOODWILL")
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "PARTIALLY_APPROVED",
        "DENIED",
        "RECOVERED",
        "WITHDRAWN",
    )
    assert isinstance(data["appeal_count"], int)
    assert isinstance(data["auto_created"], bool)


def assert_replacement_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_year"], int)
    assert data["status"] in ("DRAFT", "APPROVED", "EXECUTING", "CLOSED")
    assert isinstance(data["scores"], list)


def assert_posture_shape(data: dict):
    assert isinstance(data["active_buses"], int)
    assert isinstance(data["available_buses"], int)
    assert isinstance(data["spare_ratio"], (int, float))
    assert data["posture"] in ("GREEN", "YELLOW", "RED")
    assert isinstance(data["pull_out_minimum"], int)
    assert isinstance(data["pull_out_ready"], bool)


def assert_part_stock_invariants(part: dict):
    """quantity_available == on_hand - reserved (PRD §3.6)."""
    assert (
        part["quantity_available"]
        == part["quantity_on_hand"] - part["quantity_reserved"]
    ), (
        f"quantity_available {part['quantity_available']} != "
        f"{part['quantity_on_hand']} - {part['quantity_reserved']}"
    )
