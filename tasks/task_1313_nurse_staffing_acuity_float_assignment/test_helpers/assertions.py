"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

UNIT_TYPES = ["ICU", "STEP_DOWN", "MED_SURG", "TELEMETRY", "EMERGENCY"]
ACUITY_LEVELS = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
SHIFT_CODES = ["DAY", "NIGHT"]


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_nursing_unit(data: dict):
    """Validate a NursingUnit response against the PRD contract."""
    _assert_common_fields(data, "NursingUnit")
    assert isinstance(data["name"], str) and data["name"]
    assert data["unit_type"] in UNIT_TYPES
    assert isinstance(data["bed_count"], int) and data["bed_count"] > 0
    assert isinstance(data["incentive_budget_cents"], int) \
        and data["incentive_budget_cents"] >= 0
    assert isinstance(data["incentive_reserved_cents"], int)
    assert isinstance(data["incentive_spent_cents"], int)


def assert_nurse(data: dict):
    """Validate a Nurse response against the PRD contract."""
    _assert_common_fields(data, "Nurse")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["employment_type"] in ["CORE", "FLOAT_POOL"]
    assert isinstance(data["competencies"], list) and len(data["competencies"]) > 0
    for comp in data["competencies"]:
        assert comp in UNIT_TYPES
    assert isinstance(data["charge_qualified"], bool)
    assert isinstance(data["base_hourly_rate_cents"], int) \
        and data["base_hourly_rate_cents"] > 0


def assert_staffing_matrix_rule(data: dict):
    """Validate a StaffingMatrixRule response against the PRD contract."""
    _assert_common_fields(data, "StaffingMatrixRule")
    assert data["unit_type"] in UNIT_TYPES
    assert data["acuity_level"] in ACUITY_LEVELS
    assert isinstance(data["patients_per_nurse"], int) \
        and data["patients_per_nurse"] >= 1


def assert_acuity_snapshot(data: dict):
    """Validate an AcuitySnapshot response against the PRD contract."""
    _assert_common_fields(data, "AcuitySnapshot")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["shift_date"], str)
    assert data["shift_code"] in SHIFT_CODES
    for field in ("census_low", "census_moderate", "census_high",
                  "census_critical"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["total_census"], int)
    assert isinstance(data["required_nurses"], int)
    assert data["status"] in ["SUBMITTED", "SUPERSEDED"]


def assert_shift(data: dict):
    """Validate a Shift response against the PRD contract."""
    _assert_common_fields(data, "Shift")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["shift_date"], str)
    assert data["shift_code"] in SHIFT_CODES
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data["required_nurses"], int)
    assert isinstance(data["counted_assignments"], int)
    assert isinstance(data["sitter_diversion_count"], int)
    assert isinstance(data["charge_covered"], bool)
    assert data["staffing_posture"] in ["ADEQUATE", "UNDERSTAFFED", "CRITICAL"]
    assert data["status"] in ["OPEN", "STAFFED", "LOCKED"]


def assert_shift_assignment(data: dict):
    """Validate a ShiftAssignment response against the PRD contract."""
    _assert_common_fields(data, "ShiftAssignment")
    assert is_valid_uuid(data.get("shift_id", ""))
    assert is_valid_uuid(data.get("nurse_id", ""))
    assert isinstance(data["is_charge"], bool)
    assert data["source"] in ["DIRECT", "FLOAT", "INCENTIVE"]
    assert data["status"] in [
        "PROPOSED", "ACCEPTED", "CONFIRMED", "COMPLETED", "DECLINED", "CANCELLED",
    ]
    assert data["scheduled_hours"] == 12.0
    assert isinstance(data["premium_multiplier"], (int, float))
    assert isinstance(data["flat_bonus_cents"], int)
    assert isinstance(data["provisional_cost_cents"], int)
    assert isinstance(data["projected_ot_hours"], (int, float))


def assert_float_request(data: dict):
    """Validate a FloatRequest response against the PRD contract."""
    _assert_common_fields(data, "FloatRequest")
    assert is_valid_uuid(data.get("shift_id", ""))
    assert data["origin"] in ["MANUAL", "AUTO_ACUITY"]
    assert data["status"] in ["DEPLOYED", "UNFULFILLED", "RELEASED"]


def assert_incentive_offer(data: dict):
    """Validate an IncentiveOffer response against the PRD contract."""
    _assert_common_fields(data, "IncentiveOffer")
    assert is_valid_uuid(data.get("shift_id", ""))
    assert isinstance(data["premium_multiplier"], (int, float))
    assert 1.0 < data["premium_multiplier"] <= 3.0
    assert isinstance(data["flat_bonus_cents"], int) \
        and data["flat_bonus_cents"] >= 0
    assert data["origin"] in ["MANUAL", "AUTO"]
    assert isinstance(data["premium_reserve_cents"], int)
    assert data["status"] in [
        "OFFERED", "CLAIMED", "SETTLED", "WITHDRAWN", "EXPIRED",
    ]


def assert_sitter_request(data: dict):
    """Validate a SitterRequest response against the PRD contract."""
    _assert_common_fields(data, "SitterRequest")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["patient_ref"], str) and data["patient_ref"]
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert data["status"] in ["PENDING", "FILLED", "RELEASED"]


def assert_compliance_report(data: dict):
    """Validate a ComplianceReport response against the PRD contract."""
    _assert_common_fields(data, "ComplianceReport")
    assert isinstance(data["report_date"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "RETURNED", "ACCEPTED"]


def assert_unit_budget_invariants(data: dict):
    """Unit incentive ledger invariants that must hold after any operation."""
    assert data["incentive_reserved_cents"] >= 0
    assert data["incentive_spent_cents"] >= 0
    assert (data["incentive_reserved_cents"] + data["incentive_spent_cents"]
            <= data["incentive_budget_cents"])
