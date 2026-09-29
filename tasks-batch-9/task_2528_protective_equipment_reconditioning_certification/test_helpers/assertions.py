"""Entity shape assertions and PRD invariant checkers."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CertificationLabelStatus,
    ComponentCode,
    ComponentVerdict,
    CondemnReason,
    ConditionGrade,
    Conditioning,
    CustodyStatus,
    CustomerAccountStatus,
    DestructionMethod,
    DestructionRecordStatus,
    DiscrepancyResolution,
    InspectionVerdictSummary,
    IntakeShipmentStatus,
    LiabilityWaiverStatus,
    LoanerAssignmentStatus,
    LoanerSelectedBy,
    LoanerUnitStatus,
    OrgType,
    PartLineStatus,
    ReconStatus,
    RepairOrderStatus,
    ServiceTier,
    ShellMaterial,
    ShellTestResult,
    ShellTestStatus,
    Sport,
    TestType,
    WarrantyCoverage,
)

LABEL_CODE_PATTERN = re.compile(r"^RCP-[^-]+-\d{8}-\d{3}$")


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_system_fields(data: dict):
    """id / created_at / updated_at / version, as the PRD gives most entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_customer_account(data: dict):
    assert_common_system_fields(data)
    assert isinstance(data["org_name"], str) and data["org_name"]
    assert data["org_type"] in _values(OrgType)
    assert data["sport"] in _values(Sport)
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in _values(CustomerAccountStatus)
    assert data["liability_waiver_status"] in _values(LiabilityWaiverStatus)
    assert isinstance(data["open_shipment_count"], int) and data["open_shipment_count"] >= 0


def assert_model_spec(data: dict):
    assert_common_system_fields(data)
    assert isinstance(data["manufacturer"], str) and data["manufacturer"]
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["standard_code"], str) and data["standard_code"]
    assert data["shell_material"] in _values(ShellMaterial)
    assert isinstance(data["max_service_life_years"], int)
    assert isinstance(data["warranty_years"], int)
    assert isinstance(data["record_retention_years"], int)
    assert isinstance(data["pass_si_max"], (int, float))
    assert isinstance(data["repair_si_max"], (int, float))
    assert isinstance(data["max_retest_count"], int)
    assert isinstance(data["reconditionable"], bool)
    assert isinstance(data["required_component_codes"], list)
    assert isinstance(data["component_criteria"], list)


def assert_approved_part(data: dict):
    assert_common_system_fields(data)
    assert is_valid_uuid(data["model_spec_id"])
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert data["component_code"] in _values(ComponentCode)
    assert isinstance(data["oem_approved"], bool)
    assert isinstance(data["unit_price_cents"], int)
    assert_part_stock_conserved(data)


def assert_test_bench(data: dict):
    assert_common_system_fields(data)
    assert isinstance(data["bench_code"], str) and data["bench_code"]
    assert data["test_type"] in _values(TestType)
    assert isinstance(data["cooldown_minutes"], int)
    assert isinstance(data["daily_session_quota"], int)
    if data["calibration_valid_until"] is not None:
        assert is_iso8601_timestamp(data["calibration_valid_until"])


def assert_loaner_unit(data: dict):
    assert_common_system_fields(data)
    assert is_valid_uuid(data["model_spec_id"])
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert data["condition_grade"] in _values(ConditionGrade)
    assert is_iso8601_timestamp(data["certification_valid_until"])
    assert isinstance(data["assignment_count"], int) and data["assignment_count"] >= 0
    assert data["status"] in _values(LoanerUnitStatus)


def assert_intake_shipment(data: dict):
    assert_common_system_fields(data)
    assert is_valid_uuid(data["customer_account_id"])
    assert data["sport"] in _values(Sport)
    assert data["service_tier"] in _values(ServiceTier)
    assert isinstance(data["declared_unit_count"], int)
    assert is_iso8601_timestamp(data["season_start_date"])
    assert is_iso8601_timestamp(data["season_end_date"])
    assert data["status"] in _values(IntakeShipmentStatus)
    if data["discrepancy_resolution"] is not None:
        assert data["discrepancy_resolution"] in _values(DiscrepancyResolution)
    for counter in (
        "units_registered",
        "units_in_process",
        "units_certified",
        "units_condemned",
        "units_released",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert isinstance(data["loaner_required"], bool)
    assert isinstance(data["settlement_locked"], bool)


def assert_equipment_unit(data: dict):
    assert_common_system_fields(data)
    assert is_valid_uuid(data["intake_shipment_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["recon_status"] in _values(ReconStatus)
    assert data["custody_status"] in _values(CustodyStatus)
    assert data["inspection_verdict_summary"] in _values(InspectionVerdictSummary)
    assert data["warranty_coverage"] in _values(WarrantyCoverage)
    assert isinstance(data["life_expired"], bool)
    assert isinstance(data["condemn_required"], bool)
    assert isinstance(data["retest_count"], int) and data["retest_count"] >= 0
    if data["condemn_reason"] is not None:
        assert data["condemn_reason"] in _values(CondemnReason)


def assert_component_inspection(data: dict):
    """Append-only record: no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "inspections carry no updated_at"
    assert "version" not in data, "inspections carry no version"
    assert is_valid_uuid(data["equipment_unit_id"])
    assert data["component_code"] in _values(ComponentCode)
    assert isinstance(data["measurement_value"], (int, float))
    assert isinstance(data["measurement_unit"], str)
    assert data["verdict"] in _values(ComponentVerdict)
    assert isinstance(data["replace_threshold_applied"], (int, float))
    assert isinstance(data["fail_threshold_applied"], (int, float))
    assert isinstance(data["metric_direction_applied"], str)
    assert isinstance(data["inspector_user_id"], str) and data["inspector_user_id"]


def assert_shell_test(data: dict):
    assert_common_system_fields(data)
    assert is_valid_uuid(data["equipment_unit_id"])
    assert is_valid_uuid(data["test_bench_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["conditioning"] in _values(Conditioning)
    assert isinstance(data["attempt_index"], int) and data["attempt_index"] >= 1
    assert data["status"] in _values(ShellTestStatus)
    if data["computed_result"] is not None:
        assert data["computed_result"] in _values(ShellTestResult)
    if data["determination"] is not None:
        assert data["determination"] in _values(ShellTestResult)


def assert_repair_order(data: dict):
    assert_common_system_fields(data)
    assert is_valid_uuid(data["equipment_unit_id"])
    assert isinstance(data["part_lines"], list)
    for line in data["part_lines"]:
        assert isinstance(line["line_index"], int) and line["line_index"] >= 1
        assert is_valid_uuid(line["approved_part_id"])
        assert isinstance(line["quantity"], int) and line["quantity"] >= 1
        assert isinstance(line["unit_price_cents_snapshot"], int)
        assert line["line_total_cents"] == line["quantity"] * line["unit_price_cents_snapshot"]
        assert line["status"] in _values(PartLineStatus)
    for money in ("reserved_parts_cents", "installed_parts_cents", "labor_cents"):
        assert isinstance(data[money], int) and data[money] >= 0
    assert isinstance(data["verification_failure_count"], int)
    assert data["status"] in _values(RepairOrderStatus)
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]


def assert_certification_label(data: dict):
    assert_common_system_fields(data)
    assert is_valid_uuid(data["equipment_unit_id"])
    assert LABEL_CODE_PATTERN.match(data["label_code"]), (
        f"label_code must read RCP-<standard>-YYYYMMDD-NNN, got {data['label_code']!r}"
    )
    assert isinstance(data["standard_code_snapshot"], str) and data["standard_code_snapshot"]
    assert is_iso8601_timestamp(data["certified_on"])
    assert isinstance(data["daily_sequence"], int) and data["daily_sequence"] >= 1
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]
    assert data["status"] in _values(CertificationLabelStatus)


def assert_destruction_record(data: dict):
    assert_common_system_fields(data)
    assert is_valid_uuid(data["equipment_unit_id"])
    assert data["condemn_reason_snapshot"] in _values(CondemnReason)
    assert data["status"] in _values(DestructionRecordStatus)
    if data["method"] is not None:
        assert data["method"] in _values(DestructionMethod)


def assert_loaner_assignment(data: dict):
    assert_common_system_fields(data)
    assert is_valid_uuid(data["customer_account_id"])
    assert is_valid_uuid(data["requested_model_spec_id"])
    assert is_valid_uuid(data["loaner_unit_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["selected_by"] in _values(LoanerSelectedBy)
    assert data["status"] in _values(LoanerAssignmentStatus)


# --------------------------------------------------------------------------
# Invariant checkers
# --------------------------------------------------------------------------
def assert_part_stock_conserved(part: dict):
    """PRD: received_qty == on_hand_qty + reserved_qty + consumed_qty."""
    total = part["on_hand_qty"] + part["reserved_qty"] + part["consumed_qty"]
    assert total == part["received_qty"], (
        f"stock buckets must sum to received_qty {part['received_qty']}, "
        f"got on_hand {part['on_hand_qty']} + reserved {part['reserved_qty']} "
        f"+ consumed {part['consumed_qty']} = {total}"
    )
    for bucket in ("on_hand_qty", "reserved_qty", "consumed_qty"):
        assert part[bucket] >= 0, f"{bucket} must never go negative, got {part[bucket]}"


def assert_disposition_ledger_conserved(shipment: dict):
    """PRD: counted_unit_count == in_process + certified + condemned + released."""
    if shipment["counted_unit_count"] is None:
        return
    total = (
        shipment["units_in_process"]
        + shipment["units_certified"]
        + shipment["units_condemned"]
        + shipment["units_released"]
    )
    assert total == shipment["counted_unit_count"], (
        f"disposition counters must sum to counted_unit_count "
        f"{shipment['counted_unit_count']}, got {total}"
    )


def assert_label_code(label: dict, standard_code: str, date_yyyymmdd: str, sequence: int):
    """PRD label code shape RCP-<standard_code_snapshot>-YYYYMMDD-NNN."""
    expected = f"RCP-{standard_code}-{date_yyyymmdd}-{sequence:03d}"
    assert label["label_code"] == expected, (
        f"expected label_code {expected}, got {label['label_code']}"
    )
    assert label["daily_sequence"] == sequence


def assert_no_common_version_field(data: dict):
    """For the append-only inspection record."""
    assert "version" not in data and "updated_at" not in data
