"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §3)."""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp, tolerating optional fractional digits."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_instant_equals(actual: str, expected: str):
    """Two renderings of the same instant compare equal (PRD §2.4 pins the
    three-fractional-digit ISO 8601 form, so '...T00:00:00Z' and
    '...T00:00:00.000Z' denote the same instant)."""
    assert is_iso8601_timestamp(actual), f"not an ISO-8601 UTC timestamp: {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"expected instant {expected}, got {actual}"
    )


def assert_decimal(actual, expected: float):
    """Computed values are stored with decimal round-half-up (PRD §2.6); the
    tolerance only absorbs binary float noise, never a rounding difference."""
    assert actual == pytest.approx(expected, abs=1e-9), (
        f"expected {expected}, got {actual}"
    )


def assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_site(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["industry_code"], str) and data["industry_code"]
    assert isinstance(data["retention_years"], int) and data["retention_years"] >= 1


def assert_employee(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert isinstance(data["job_title"], str)


def assert_exposure_limit(data: dict):
    assert_common_fields(data)
    assert isinstance(data["analyte_code"], str) and data["analyte_code"]
    assert data["basis"] in ("OSHA_PEL", "ACGIH_TLV")
    assert data["limit_type"] in ("TWA8", "CEILING")
    assert data["limit_mg_m3"] > 0
    assert 0 < data["action_fraction"] < 1


def assert_seg(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["exposure_limit_id"])
    assert isinstance(data["headcount"], int) and data["headcount"] >= 0
    assert data["current_class"] in (
        "NONE",
        "BELOW_ACTION",
        "BELOW_PEL_MONITOR",
        "UNCERTAIN",
        "ABOVE_PEL",
    )
    assert data.get("next_sample_due_date") is None or isinstance(
        data["next_sample_due_date"], str
    )


def assert_membership(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["seg_id"])
    assert is_valid_uuid(data["employee_id"])
    assert isinstance(data["is_primary"], bool)


def assert_plan(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["seg_id"])
    assert data["purpose"] in ("INITIAL", "FOLLOWUP", "VERIFICATION")
    assert data["status"] in (
        "DRAFT",
        "PENDING_APPROVAL",
        "APPROVED",
        "FIELD_COMPLETE",
        "LAB_COMPLETE",
    )
    assert isinstance(data["required_sample_count"], int)
    assert data["required_sample_count"] >= 3
    assert isinstance(data["active_sample_count"], int)
    assert data["active_sample_count"] >= 0
    assert isinstance(data["analyzed_valid_count"], int)
    assert data["analyzed_valid_count"] >= 0
    assert isinstance(data["created_by_user_id"], str)


def assert_pump(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"]


def assert_calibration(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["pump_id"])
    assert data["pre_flow_lpm"] > 0
    assert data["result"] in ("PENDING", "VALID", "INVALID")
    if data["result"] == "PENDING":
        assert data.get("post_flow_lpm") is None
        assert data.get("drift_pct") is None
    else:
        assert data["post_flow_lpm"] is not None
        assert data["drift_pct"] is not None
    assert isinstance(data["performed_by_user_id"], str)


def assert_sample(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["sampling_plan_id"])
    assert data["sample_type"] in ("PERSONAL", "FIELD_BLANK")
    assert data["status"] in ("COLLECTED", "SEALED", "ANALYZED", "INVALIDATED")
    assert 0 <= data["start_minute"] <= 1439
    assert 1 <= data["duration_minutes"] <= 960
    if data["sample_type"] == "PERSONAL":
        assert is_valid_uuid(data["employee_id"])
        assert is_valid_uuid(data["pump_id"])
        assert is_valid_uuid(data["pre_calibration_id"])
    if data["status"] != "INVALIDATED":
        assert data.get("invalidate_reason") is None
    if data["status"] != "ANALYZED":
        assert data.get("concentration_mg_m3") is None


def assert_batch(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert data["lod_ug"] > 0
    assert data["loq_ug"] >= data["lod_ug"]
    assert data["window_end_date"] >= data["window_start_date"]
    assert isinstance(data["max_capacity"], int) and data["max_capacity"] >= 1
    assert isinstance(data["intake_count"], int) and data["intake_count"] >= 0
    assert isinstance(data["contaminated"], bool)


def assert_lab_result(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["field_sample_id"])
    assert is_valid_uuid(data["lab_batch_id"])
    assert data["mass_ug"] >= 0
    assert isinstance(data["is_detect"], bool)
    assert isinstance(data["is_quantifiable"], bool)
    assert isinstance(data["entered_by_user_id"], str)
    assert is_iso8601_timestamp(data["reported_at"])


def assert_assessment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["seg_id"])
    assert is_valid_uuid(data["sampling_plan_id"])
    assert data["review_status"] in (
        "DRAFT",
        "UNDER_REVIEW",
        "SIGNED",
        "SUPERSEDED",
        "VOID",
        "ARCHIVED",
    )
    assert data["exposure_class"] in (
        "BELOW_ACTION",
        "BELOW_PEL_MONITOR",
        "UNCERTAIN",
        "ABOVE_PEL",
    )
    assert data["substitution_rule"] in ("SQRT2", "HALF")
    assert isinstance(data["n_valid"], int) and data["n_valid"] >= 1
    assert isinstance(data["is_current"], bool)
    assert isinstance(data["prepared_by_user_id"], str)


def assert_control(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["exposure_assessment_id"])
    assert data["control_type"] in ("ENGINEERING", "ADMINISTRATIVE", "PPE_RESPIRATOR")
    assert data["priority"] in ("HIGH", "MEDIUM", "LOW")
    assert data["status"] in (
        "PROPOSED",
        "ACCEPTED",
        "REJECTED",
        "IMPLEMENTED",
        "VERIFIED",
    )
    assert isinstance(data["auto_created"], bool)
    if data["control_type"] == "PPE_RESPIRATOR":
        assert data["assigned_protection_factor"] is not None
        assert data["assigned_protection_factor"] > 1


def assert_notification(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["exposure_assessment_id"])
    assert data["status"] in ("PENDING", "SENT", "OVERDUE", "ACKNOWLEDGED")
    assert isinstance(data["due_date"], str) and data["due_date"]


def assert_clearance(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["employee_id"])
    assert data["status"] in ("REQUESTED", "CLEARED", "DENIED", "EXPIRED")
    if data["status"] == "REQUESTED":
        assert data.get("decided_at") is None


def assert_fit_test(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["medical_clearance_id"])
    assert isinstance(data["respirator_model"], str) and data["respirator_model"]
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED", "EXPIRED")
    assert isinstance(data["test_date"], str)
    assert isinstance(data["expiry_date"], str)
