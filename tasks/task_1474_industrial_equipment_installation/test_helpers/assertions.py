"""Entity assertions and domain invariant checkers.

Field presence follows PRD section 2.4: primary resources carry id,
created_at, updated_at, and version; invoices are append-only and expose
neither updated_at nor version.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_project(data: dict):
    _assert_common_fields(data, "Project")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert isinstance(data["site_address"], str) and data["site_address"]
    assert data["billing_mode"] in ("TM", "LUMP_SUM")
    assert isinstance(data["contract_amount_cents"], int) and data["contract_amount_cents"] > 0
    assert isinstance(data["equipment_hourly_rate_cents"], int)
    assert 0 <= data["retainage_pct"] <= 0.20
    assert data["ot_basis"] in ("DAILY_OT", "WEEKLY_OT")
    assert data["work_status"] in (
        "AWARDED", "MOBILIZED", "INSTALLING", "COMMISSIONING", "COMPLETED"
    )
    assert data["hold_status"] in ("CLEAR", "SAFETY_HOLD")
    assert data["approved_rigging_plan_id"] is None or isinstance(
        data["approved_rigging_plan_id"], str
    )
    assert data["approved_rigging_plan_revision"] is None or isinstance(
        data["approved_rigging_plan_revision"], int
    )
    for field in ("approved_labor_cents", "approved_equipment_cents", "invoiced_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"Project.{field} must be a non-negative integer"
        )


def assert_site_survey(data: dict):
    _assert_common_fields(data, "SiteSurvey")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["survey_date"], str)
    assert isinstance(data["anchor_bolt_count"], int) and data["anchor_bolt_count"] > 0
    assert data["anchor_tolerance_mm"] > 0
    assert data["anchor_measured_max_deviation_mm"] >= 0
    assert data["overhead_clearance_mm"] > 0
    assert isinstance(data["foundation_pour_date"], str)
    assert isinstance(data["anchor_check_passed"], bool)
    assert isinstance(data["foundation_cured"], bool)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_safety_plan(data: dict):
    _assert_common_fields(data, "SafetyPlan")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["plan_document_ref"], str)
    assert isinstance(data["loto_procedure_ref"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "CLOSED")


def assert_lockout_window(data: dict):
    _assert_common_fields(data, "LockoutWindow")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["feeder_id"], str)
    assert isinstance(data["starts_at"], str)
    assert isinstance(data["ends_at"], str)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "RELEASED", "CANCELLED", "EXPIRED")


def assert_rigging_plan(data: dict):
    _assert_common_fields(data, "RiggingPlan")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["lift_weight_tons"] > 0
    assert isinstance(data["crane_model"], str)
    assert data["planned_crane_capacity_tons"] > 0
    assert data["rigging_config"] in ("SINGLE_CRANE", "TANDEM", "GANTRY")
    assert isinstance(data["weight_check_passed"], bool)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")


def assert_lift_permit(data: dict):
    _assert_common_fields(data, "LiftPermit")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["crane_ref"], str)
    assert isinstance(data["lift_starts_at"], str)
    assert isinstance(data["lift_ends_at"], str)
    assert isinstance(data["road_permit_required"], bool)
    assert data["duration_hours"] > 0
    assert data["equipment_charge_cents"] is None or isinstance(
        data["equipment_charge_cents"], int
    )
    assert data["status"] in ("ISSUED", "EXECUTED", "CANCELLED", "EXPIRED")


def assert_alignment_record(data: dict):
    _assert_common_fields(data, "AlignmentRecord")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["measurement_point"], str)
    assert data["tolerance_class"] in ("STANDARD", "PRECISION")
    assert data["measured_offset_mils"] >= 0
    assert data["measured_angular_mils_per_in"] >= 0
    assert isinstance(data["offset_passed"], bool)
    assert isinstance(data["angular_passed"], bool)
    assert data["verdict"] in ("PASS", "FAIL")
    assert data["status"] in ("RECORDED", "ACCEPTED", "REJECTED")


def assert_commissioning_checklist(data: dict):
    _assert_common_fields(data, "CommissioningChecklist")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["items"], list)
    for item in data["items"]:
        assert isinstance(item["item_key"], str)
        assert isinstance(item["description"], str)
        assert isinstance(item["required"], bool)
        assert isinstance(item["checked"], bool)
    assert isinstance(data["required_count"], int)
    assert isinstance(data["checked_required_count"], int)
    assert 0 <= data["checked_required_count"] <= data["required_count"]
    assert data["status"] in ("IN_PROGRESS", "SUBMITTED", "SIGNED_OFF")


def assert_labor_entry(data: dict):
    _assert_common_fields(data, "LaborEntry")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["worker_ref"], str)
    assert data["classification"] in (
        "MW_JOURNEYMAN", "MW_APPRENTICE", "MW_FOREMAN", "OPERATOR"
    )
    assert isinstance(data["work_date"], str)
    assert 0 < data["hours_worked"] <= 24
    assert data["shift"] in ("DAY", "NIGHT")
    assert data["regular_hours"] >= 0
    assert data["overtime_hours"] >= 0
    assert data["regular_hours"] + data["overtime_hours"] == data["hours_worked"], (
        "regular_hours + overtime_hours must equal hours_worked"
    )
    assert isinstance(data["base_rate_cents"], int) and data["base_rate_cents"] > 0
    assert isinstance(data["total_cost_cents"], int) and data["total_cost_cents"] > 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "INVOICED")


def assert_invoice(data: dict):
    """Invoices are append-only: id and created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "Invoice.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "Invoice.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "Invoice must not expose updated_at"
    assert "version" not in data, "Invoice must not expose version"
    assert isinstance(data["project_id"], str)
    assert data["kind"] in ("PROGRESS", "FINAL")
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["billing_mode_snapshot"] in ("TM", "LUMP_SUM")
    for field in ("gross_cents", "retainage_cents", "retainage_released_cents", "amount_cents"):
        assert isinstance(data[field], int), f"Invoice.{field} must be integer cents"
    assert isinstance(data["labor_entry_ids"], list)
    assert isinstance(data["lift_permit_ids"], list)


def assert_project_rollup_invariants(data: dict):
    """Project financial rollups are non-negative integer cents."""
    assert_project(data)
    assert data["approved_labor_cents"] >= 0
    assert data["approved_equipment_cents"] >= 0
    assert data["invoiced_cents"] >= 0
