"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

EQUIPMENT_CODES = [
    "BIPLANE_ANGIOGRAPHY", "IVUS", "OCT", "FFR",
    "ROTATIONAL_ATHERECTOMY", "IABP", "MECHANICAL_SUPPORT",
]


def _parse_instant(value):
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def assert_instant_equals(actual, expected_iso):
    """Assert two ISO 8601 values denote the same instant at second resolution.

    PRD §2.6 pins datetimes to second resolution; the exact wire spelling
    (trailing fractional digits) is not pinned, so instants are compared, not
    raw strings.
    """
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_cath_lab_room(data: dict):
    """Validate a CathLabRoom payload against the PRD contract (§3.1)."""
    _assert_common_fields(data)
    assert isinstance(data["room_name"], str) and len(data["room_name"]) > 0
    assert isinstance(data["equipment_profile"], list)
    for code in data["equipment_profile"]:
        assert code in EQUIPMENT_CODES, f"unknown equipment code {code!r}"
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")


def assert_staff_member(data: dict):
    """Validate a StaffMember payload against the PRD contract (§3.1)."""
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["staff_role"] in (
        "INTERVENTIONAL_CARDIOLOGIST", "SCRUB_TECHNOLOGIST", "CIRCULATING_NURSE")
    assert isinstance(data["credentials"], list)
    assert isinstance(data["is_active"], bool)


def assert_cath_case(data: dict):
    """Validate a CathCase payload against the PRD contract (§3.2)."""
    _assert_common_fields(data)
    assert isinstance(data["patient_mrn"], str) and len(data["patient_mrn"]) > 0
    assert data["procedure_type"] in (
        "DIAGNOSTIC_CATHETERIZATION", "PCI", "STEMI_PCI", "DEVICE_IMPLANT", "EP_STUDY")
    assert data["priority"] in ("ELECTIVE", "URGENT", "STEMI")
    assert isinstance(data["performing_physician_id"], str)
    assert data["weight_kg"] > 0
    assert data["serum_creatinine"] > 0
    assert isinstance(data["equipment_needs"], list)
    for code in data["equipment_needs"]:
        assert code in EQUIPMENT_CODES, f"unknown equipment code {code!r}"
    assert data["status"] in (
        "POSTED", "SCHEDULED", "BUMPED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    # Nullable scheduling fields — null while POSTED/BUMPED/CANCELLED (§3.2).
    for field in ("lab_id", "scheduled_start", "scheduled_end",
                  "actual_start", "actual_end"):
        assert field in data, f"missing field {field}"
    assert data["contrast_limit_ml"] > 0
    assert data["cumulative_contrast_ml"] >= 0
    assert data["cumulative_radiation_mgy"] >= 0
    assert isinstance(data["radiation_alert"], bool)
    assert isinstance(data["bump_count"], int) and data["bump_count"] >= 0
    assert data["auc_status"] in ("NOT_DOCUMENTED", "DOCUMENTED")
    for field in ("auc_score", "auc_criterion_code", "ordering_physician_id"):
        assert field in data, f"missing field {field}"


def assert_staff_assignment(data: dict):
    """Validate a StaffAssignment payload against the PRD contract (§3.4)."""
    _assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["staff_id"], str)
    assert data["role_in_case"] in ("PRIMARY_OPERATOR", "SCRUB", "CIRCULATOR")
    assert data["status"] in ("ASSIGNED", "RELEASED")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])


def assert_device_lot(data: dict):
    """Validate a DeviceLot payload against the PRD contract (§3.5)."""
    _assert_common_fields(data)
    assert data["device_type"] in (
        "STENT_DES", "STENT_BMS", "PACEMAKER_LEAD", "ICD_LEAD", "CLOSURE_DEVICE")
    assert isinstance(data["manufacturer"], str)
    assert isinstance(data["model_number"], str)
    assert isinstance(data["lot_number"], str)
    assert data["ownership"] in ("OWNED", "CONSIGNMENT")
    assert isinstance(data["quantity_on_hand"], int) and data["quantity_on_hand"] >= 0
    assert isinstance(data["allocated_units"], int) and data["allocated_units"] >= 0
    assert isinstance(data["available_units"], int)
    assert isinstance(data["reorder_threshold"], int) and data["reorder_threshold"] >= 0
    assert data["status"] in ("ACTIVE", "LOW_STOCK", "DEPLETED")


def assert_device_lot_invariants(data: dict):
    """PRD §3.5 invariants that must hold after any lot mutation."""
    assert data["available_units"] == data["quantity_on_hand"] - data["allocated_units"], (
        "available_units must equal quantity_on_hand minus allocated_units"
    )
    avail, threshold = data["available_units"], data["reorder_threshold"]
    if avail == 0:
        expected = "DEPLETED"
    elif avail < threshold:
        expected = "LOW_STOCK"
    else:
        expected = "ACTIVE"
    assert data["status"] == expected, (
        f"status must be {expected} for available={avail}, threshold={threshold}; "
        f"got {data['status']}"
    )


def assert_device_usage(data: dict):
    """Validate a DeviceUsage payload against the PRD contract (§3.5)."""
    _assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ("RESERVED", "IMPLANTED", "RELEASED")


def assert_dose_record(data: dict):
    """Validate a DoseRecord payload against the PRD contract (§3.6)."""
    _assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["record_type"] in ("CONTRAST", "RADIATION")
    assert data["status"] in ("ACTIVE", "VOIDED")
    assert isinstance(data["record_total_mgy"], (int, float))
    if data["record_type"] == "CONTRAST":
        assert data["contrast_ml"] is not None and data["contrast_ml"] >= 0
        assert data["record_total_mgy"] == pytest.approx(0, abs=1e-9), (
            "a contrast entry's record_total_mgy is always 0")
    else:
        assert data["fluoroscopy_mgy"] is not None and data["fluoroscopy_mgy"] >= 0
        assert data["cine_mgy"] is not None and data["cine_mgy"] >= 0
        expected = data["fluoroscopy_mgy"] + data["cine_mgy"]
        assert data["record_total_mgy"] == pytest.approx(expected, abs=0.011), (
            "record_total_mgy is the components summed and rounded half-up to 2 dp")


def assert_recovery_bed(data: dict):
    """Validate a RecoveryBed payload against the PRD contract (§3.1, §3.7)."""
    _assert_common_fields(data)
    assert isinstance(data["bed_label"], str) and len(data["bed_label"]) > 0
    assert data["status"] in ("AVAILABLE", "RESERVED", "OCCUPIED", "OUT_OF_SERVICE")
    for field in ("held_case_id", "window_start", "window_end"):
        assert field in data, f"missing field {field}"
    if data["status"] in ("AVAILABLE", "OUT_OF_SERVICE"):
        assert data["held_case_id"] is None, "a free bed's held_case_id is null"


def assert_registry_submission(data: dict):
    """Validate a RegistrySubmission payload against the PRD contract (§3.9)."""
    _assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["registry_name"] in ("NCDR_CATHPCI", "NCDR_ICD", "NCDR_EP")
    assert isinstance(data["completeness_pct"], (int, float))
    assert 0 <= data["completeness_pct"] <= 100.0
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")
    for field in ("submitted_at", "decided_at", "rejection_reason", "correction_note"):
        assert field in data, f"missing field {field}"
