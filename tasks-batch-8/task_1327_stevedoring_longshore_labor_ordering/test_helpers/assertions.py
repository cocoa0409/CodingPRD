"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssignmentStatus,
    Classification,
    DamageClaimStatus,
    EquipmentAssignmentStatus,
    EquipmentType,
    EquipmentUnitStatus,
    GangOrderStatus,
    GangType,
    IncidentScope,
    IncidentSeverity,
    InvoiceStatus,
    MoveRecordStatus,
    RateVariant,
    SafetyIncidentStatus,
    ShiftPeriod,
    ShiftWindowStatus,
    TimesheetStatus,
    VesselCallStatus,
    WorkerStatus,
    WorkPosture,
)


def _assert_common(data: dict, what: str):
    assert is_valid_uuid(data.get("id", "")), f"{what}: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{what}: created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{what}: updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{what}: version must be a positive integer"
    )


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def assert_vessel_call(data: dict):
    _assert_common(data, "VesselCall")
    assert isinstance(data.get("vessel_name"), str) and data["vessel_name"]
    assert isinstance(data.get("voyage_number"), str)
    assert isinstance(data.get("shipping_line"), str)
    assert data.get("status") in {s.value for s in VesselCallStatus}
    assert data.get("work_posture") in {p.value for p in WorkPosture}
    assert isinstance(data.get("planned_moves"), int) and data["planned_moves"] >= 0
    assert _is_number(data.get("planned_tons")) and data["planned_tons"] >= 0
    assert _is_number(data.get("contracted_mph_target")) and data["contracted_mph_target"] > 0
    assert isinstance(data.get("credit_limit_cents"), int) and data["credit_limit_cents"] > 0
    assert isinstance(data.get("actual_moves"), int)
    assert _is_number(data.get("actual_tons"))


def assert_shift_window(data: dict):
    _assert_common(data, "ShiftWindow")
    assert is_valid_uuid(data.get("vessel_call_id", ""))
    assert data.get("period") in {p.value for p in ShiftPeriod}
    assert data.get("status") in {s.value for s in ShiftWindowStatus}
    assert is_iso8601_timestamp(data.get("start_utc", ""))
    assert is_iso8601_timestamp(data.get("end_utc", ""))


def assert_gang_order(data: dict):
    _assert_common(data, "GangOrder")
    assert is_valid_uuid(data.get("shift_window_id", ""))
    assert data.get("gang_type") in {t.value for t in GangType}
    assert data.get("required_classification") in {c.value for c in Classification}
    assert isinstance(data.get("required_headcount"), int) and data["required_headcount"] >= 1
    assert data.get("required_equipment_type") in {t.value for t in EquipmentType}
    assert isinstance(data.get("required_equipment_count"), int) and data["required_equipment_count"] >= 0
    assert data.get("status") in {s.value for s in GangOrderStatus}
    assert isinstance(data.get("filled_headcount"), int) and data["filled_headcount"] >= 0
    assert isinstance(data.get("offered_count"), int) and data["offered_count"] >= 0
    assert isinstance(data.get("assigned_equipment_ok"), bool)
    assert isinstance(data.get("suspension_count"), int) and data["suspension_count"] >= 0


def assert_worker(data: dict):
    _assert_common(data, "Worker")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("registration_number"), str) and data["registration_number"]
    assert data.get("classification") in {c.value for c in Classification}
    assert isinstance(data.get("registered_on"), str)
    assert isinstance(data.get("base_hourly_rate_cents"), int) and data["base_hourly_rate_cents"] > 0
    assert data.get("status") in {s.value for s in WorkerStatus}
    assert isinstance(data.get("seniority_rank"), int) and data["seniority_rank"] >= 1


def assert_dispatch_assignment(data: dict):
    _assert_common(data, "DispatchAssignment")
    assert is_valid_uuid(data.get("gang_order_id", ""))
    assert is_valid_uuid(data.get("worker_id", ""))
    assert data.get("status") in {s.value for s in AssignmentStatus}
    assert isinstance(data.get("seniority_rank_at_dispatch"), int)


def assert_equipment_unit(data: dict):
    _assert_common(data, "EquipmentUnit")
    assert isinstance(data.get("unit_code"), str) and data["unit_code"]
    assert data.get("equipment_type") in {t.value for t in EquipmentType}
    assert data.get("status") in {s.value for s in EquipmentUnitStatus}
    assert isinstance(data.get("total_breakdowns"), int) and data["total_breakdowns"] >= 0


def assert_equipment_assignment(data: dict):
    _assert_common(data, "EquipmentAssignment")
    assert is_valid_uuid(data.get("gang_order_id", ""))
    assert is_valid_uuid(data.get("equipment_unit_id", ""))
    assert is_iso8601_timestamp(data.get("window_start_utc", ""))
    assert is_iso8601_timestamp(data.get("window_end_utc", ""))
    assert data.get("status") in {s.value for s in EquipmentAssignmentStatus}


def assert_move_record(data: dict):
    _assert_common(data, "MoveRecord")
    assert is_valid_uuid(data.get("gang_order_id", ""))
    assert is_iso8601_timestamp(data.get("period_start_utc", ""))
    assert is_iso8601_timestamp(data.get("period_end_utc", ""))
    assert isinstance(data.get("moves_count"), int) and data["moves_count"] >= 0
    assert _is_number(data.get("tons_lifted")) and data["tons_lifted"] >= 0
    assert isinstance(data.get("stoppage_minutes"), int) and data["stoppage_minutes"] >= 0
    assert data.get("status") in {s.value for s in MoveRecordStatus}


def assert_damage_claim(data: dict):
    _assert_common(data, "DamageClaim")
    assert is_valid_uuid(data.get("gang_order_id", ""))
    assert isinstance(data.get("cargo_ref"), str)
    assert isinstance(data.get("damage_description"), str)
    assert isinstance(data.get("estimated_amount_cents"), int) and data["estimated_amount_cents"] > 0
    assert data.get("status") in {s.value for s in DamageClaimStatus}
    assert isinstance(data.get("provisional_stevedore_share_cents"), int)


def assert_safety_incident(data: dict):
    _assert_common(data, "SafetyIncident")
    assert is_valid_uuid(data.get("vessel_call_id", ""))
    assert data.get("scope") in {s.value for s in IncidentScope}
    assert data.get("severity") in {s.value for s in IncidentSeverity}
    assert data.get("status") in {s.value for s in SafetyIncidentStatus}


def assert_timesheet_entry(data: dict):
    _assert_common(data, "TimesheetEntry")
    assert is_valid_uuid(data.get("gang_order_id", ""))
    assert is_valid_uuid(data.get("worker_id", ""))
    assert isinstance(data.get("work_minutes"), int) and data["work_minutes"] >= 0
    assert isinstance(data.get("meal_break_taken"), bool)
    assert data.get("status") in {s.value for s in TimesheetStatus}
    assert isinstance(data.get("rate_cents_snapshot"), int) and data["rate_cents_snapshot"] > 0


def assert_approved_timesheet_breakdown(data: dict):
    """Pay fields that PRD §3.8 pins as computed-and-frozen at approval."""
    assert data.get("status") == TimesheetStatus.APPROVED.value
    for field in ("straight_minutes", "ot_minutes", "dt_minutes",
                  "meal_penalty_minutes", "gross_pay_cents", "bonus_cents"):
        assert isinstance(data.get(field), int), f"{field} must be an integer"
    assert data["straight_minutes"] == min(data["work_minutes"], 480)
    assert data["ot_minutes"] == min(max(data["work_minutes"] - 480, 0), 240)
    assert data["dt_minutes"] == max(data["work_minutes"] - 720, 0)


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert is_valid_uuid(data.get("vessel_call_id", ""))
    assert data.get("status") in {s.value for s in InvoiceStatus}
    assert data.get("rate_variant") in {v.value for v in RateVariant}
    for field in ("container_line_cents", "tonnage_line_cents", "manhour_line_cents",
                  "equipment_line_cents", "stoppage_credit_cents", "subtotal_cents",
                  "discount_cents", "adjustment_total_cents", "total_cents",
                  "amount_paid_cents", "remaining_balance_cents"):
        assert isinstance(data.get(field), int), f"{field} must be integer cents"
    assert data["total_cents"] == (
        data["subtotal_cents"] - data["discount_cents"] + data["adjustment_total_cents"]
    ), "total must equal subtotal - discount + adjustments (PRD §3.9)"
    assert data["remaining_balance_cents"] == data["total_cents"] - data["amount_paid_cents"], (
        "remaining balance must equal total minus amount paid (PRD §3.9)"
    )
