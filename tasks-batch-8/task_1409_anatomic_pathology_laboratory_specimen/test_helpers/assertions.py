"""Entity assertions, timestamp comparison helpers, and domain invariants."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(ts, str), f"expected timestamp string, got {type(ts)}: {ts!r}"
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_instant_equal(actual, expected, context=""):
    """Two ISO timestamps denote the same instant (formatting may differ)."""
    actual_dt = parse_instant(actual)
    expected_dt = parse_instant(expected)
    assert actual_dt == expected_dt, (
        f"{context}: expected instant {expected}, got {actual}"
    )


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an int >= 1"
    )


def assert_patient(data: dict):
    _assert_common(data, "Patient")
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str)


def assert_pathologist(data: dict):
    _assert_common(data, "Pathologist")
    assert isinstance(data["full_name"], str)
    assert isinstance(data["subspecialties"], list) and len(data["subspecialties"]) > 0
    assert isinstance(data["active"], bool)


def assert_coverage_window(data: dict):
    _assert_common(data, "CoverageWindow")
    assert data["window_type"] in ("CONSULT_SERVICE", "UNAVAILABLE")
    assert data["status"] in ("ACTIVE", "CANCELLED")


def assert_case(data: dict):
    _assert_common(data, "Case")
    assert data["status"] in ("OPEN", "WORKUP", "PENDING_SIGNOUT", "FINAL", "AMENDING", "CANCELLED")
    assert data["complexity_class"] in ("SIMPLE", "MODERATE", "COMPLEX", "HIGH_COMPLEXITY")
    assert data["tat_mode"] in ("CALENDAR", "BUSINESS_HOURS")


def assert_specimen(data: dict):
    _assert_common(data, "Specimen")
    assert data["status"] in ("ACCESSIONED", "GROSSING", "PROCESSING", "COMPLETE", "REJECTED")
    assert data["specimen_type"] in ("BIOPSY", "EXCISION", "RESECTION", "CYTOLOGY")
    assert isinstance(data["accession_number"], str) and data["accession_number"].startswith("SP")


def assert_block(data: dict):
    _assert_common(data, "Block")
    assert data["status"] in ("CREATED", "EMBEDDED", "DEPLETED")
    assert isinstance(data["block_label"], str)


def assert_slide(data: dict):
    _assert_common(data, "Slide")
    assert data["status"] in ("ORDERED", "SECTIONED", "STAINED", "QC_PASSED", "QC_FAILED", "CANCELLED")
    assert isinstance(data["slide_label"], str)


def assert_stain_order(data: dict):
    _assert_common(data, "StainOrder")
    assert data["status"] in ("ORDERED", "IN_PROGRESS", "RESULTED", "CANCELLED")
    assert data["stain_type"] in ("HER2_IHC", "PD_L1", "KI67", "PAX5", "CD20", "MUCIN", "GRAM", "GMS")


def assert_reflex_rule(data: dict):
    _assert_common(data, "ReflexRule")
    assert isinstance(data["name"], str)
    assert isinstance(data["priority"], int)
    assert isinstance(data["active"], bool)
    assert data["trigger_stain_type"] != data["followup_stain_type"]


def assert_report(data: dict):
    _assert_common(data, "Report")
    assert data["report_class"] in ("FINAL", "AMENDED")
    assert data["status"] in ("DRAFT", "SIGNED", "SUPERSEDED", "CANCELLED")
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1


def assert_consultation(data: dict):
    _assert_common(data, "Consultation")
    assert data["status"] in (
        "REQUESTED", "ACCEPTED", "DECLINED", "ANSWERED", "INCORPORATED", "EXPIRED", "CANCELLED"
    )


def assert_discrepancy(data: dict):
    _assert_common(data, "Discrepancy")
    assert data["severity"] in ("LEVEL_1", "LEVEL_2", "LEVEL_3")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "RESOLVED")
    assert data["source"] in ("CONSULTATION", "INTERNAL_QA")


def assert_release_request(data: dict):
    _assert_common(data, "ReleaseRequest")
    assert data["material_type"] in ("BLOCK", "SLIDE")
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "SHIPPED", "OVERDUE", "RETURNED")


def assert_case_invariants(data: dict):
    """Domain invariants for a case payload."""
    assert_case(data)
    assert data["complexity_score"] >= 0
    assert data["breach_minutes"] >= 0
    assert data["open_critical_discrepancy_count"] >= 0
    if data["status"] in ("FINAL", "AMENDING"):
        assert data["finalized_at"] is not None
        assert data["current_signed_report_id"] is not None
    if data["status"] != "AMENDING":
        assert data["amender_pathologist_id"] is None
