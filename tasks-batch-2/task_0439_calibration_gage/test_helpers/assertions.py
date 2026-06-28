"""Entity assertions and domain invariant checkers (PRD §3, §2.4)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """The four system-managed fields present on every entity except the clock."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_calibration_standard(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["traceability_depth"], int) and data["traceability_depth"] >= 0
    assert isinstance(data["is_traceable"], bool)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_calibration_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["accreditation_body"] in ("A2LA", "NVLAP", "UKAS", "NONE")
    assert isinstance(data["is_accreditation_current"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_instrument(data: dict):
    _assert_common(data)
    assert isinstance(data["asset_tag"], str) and len(data["asset_tag"]) > 0
    assert data["lifecycle_status"] in ("ACTIVE", "QUARANTINED", "RETIRED")
    assert data["calibration_status"] in (
        "UNCALIBRATED", "IN_TOLERANCE", "OUT_OF_TOLERANCE", "OVERDUE",
    )
    assert data["criticality"] in ("CRITICAL", "MAJOR", "MINOR")
    assert isinstance(data["open_oot_count"], int) and data["open_oot_count"] >= 0


def assert_calibration_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("instrument_id", "")), "instrument_id must be a UUID"
    assert data["status"] in (
        "DRAFT", "IN_PROGRESS", "PASSED", "CONDITIONAL_PASS", "FAILED", "CANCELLED",
    )
    if data.get("result") is not None:
        assert data["result"] in ("PASS", "CONDITIONAL", "FAIL")


def assert_measurement_point(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("calibration_event_id", "")), "calibration_event_id must be a UUID"
    assert isinstance(data["as_found_pass"], bool)
    assert isinstance(data["as_left_pass"], bool)


def assert_calibration_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("calibration_event_id", "")), "calibration_event_id must be a UUID"
    assert data["status"] in ("ISSUED", "VERIFIED", "REJECTED")


def assert_out_of_tolerance_impact(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("instrument_id", "")), "instrument_id must be a UUID"
    assert is_valid_uuid(data.get("triggering_event_id", "")), "triggering_event_id must be a UUID"
    assert data["status"] in (
        "OPEN", "INVESTIGATING", "DISPOSITIONED", "ESCALATED", "CANCELLED",
    )
    assert isinstance(data["affected_product_count"], int) and data["affected_product_count"] >= 0
    assert isinstance(data["recalled_product_count"], int) and data["recalled_product_count"] >= 0


def assert_affected_product(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("impact_id", "")), "impact_id must be a UUID"
    assert isinstance(data["in_suspect_window"], bool)
    assert data["status"] in ("FLAGGED", "RECALLED", "CLEARED")


def assert_gage_rr_study(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("instrument_id", "")), "instrument_id must be a UUID"
    assert data["status"] in (
        "DRAFT", "COLLECTING", "ANALYZED", "ACCEPTED", "REJECTED", "CANCELLED",
    )
    if data.get("acceptability") is not None:
        assert data["acceptability"] in ("ACCEPTABLE", "MARGINAL", "UNACCEPTABLE")


def assert_gage_rr_trial(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", "")), "study_id must be a UUID"


def assert_clock_state(data: dict):
    """ClockState carries ONLY id + created_at + current_epoch (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["current_epoch"], int)
