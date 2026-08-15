"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Inspection and DisposalRecord are
append-only and must NOT expose updated_at/version (PRD common-resource-
properties section).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_CUISINES = ("LOW_GREASE", "MEDIUM_GREASE", "HIGH_GREASE")
_RISK_CLASSES = ("HIGH", "MEDIUM", "LOW")
_POSTURES = ("COMPLIANT", "WATCH", "DELINQUENT", "SUSPENDED")
_INTERCEPTOR_STATUSES = ("PROPOSED", "APPROVED", "ACTIVE")
_SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
_VIOLATION_STATUSES = ("NOTICED", "CITATION", "RESOLVED", "DISMISSED")
_MANIFEST_STATUSES = ("SUBMITTED", "VERIFIED", "REJECTED")
_REJECT_REASONS = ("DISPOSAL_MISMATCH", "MISSING_DISPOSAL_RECORD",
                   "HAULER_SUSPENDED", "OTHER")
_HAULER_STATUSES = ("APPLIED", "PERMITTED", "SUSPENDED", "REVOKED")
_BLOCKAGE_STATUSES = ("REPORTED", "ASSESSED", "CLOSED")
_VARIANCE_SCOPES = ("PUMPING_FREQUENCY", "INTERCEPTOR_SIZE")
_VARIANCE_STATUSES = ("UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DENIED")
_EVENT_STATUSES = ("RECORDED", "VOIDED")
_INSPECTION_CATEGORIES = ("GREASE_TRAP_MAINTENANCE", "RECORD_KEEPING",
                          "STRUCTURAL", "BMP_PRACTICES")


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict):
    """Append-only records carry only id + created_at among system fields."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "append-only record must omit updated_at"
    assert "version" not in data, "append-only record must omit version"


def assert_establishment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["street_address"], str)
    assert isinstance(data["seating_capacity"], int) and data["seating_capacity"] >= 0
    assert isinstance(data["fryer_count"], int) and data["fryer_count"] >= 0
    assert isinstance(data["has_charbroiler"], bool)
    assert data["cuisine_profile"] in _CUISINES
    assert isinstance(data["risk_score"], (int, float))
    assert data["risk_class"] in _RISK_CLASSES
    assert data["compliance_status"] in _POSTURES
    assert isinstance(data["open_violation_count"], int)
    assert isinstance(data["pumping_frequency_days"], int)
    assert isinstance(data["pumping_overdue"], bool)
    assert isinstance(data["missed_pump_windows"], int)


def assert_interceptor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["establishment_id"], str)
    assert isinstance(data["nominal_capacity_gal"], int)
    assert data["nominal_capacity_gal"] > 0
    assert data["status"] in _INTERCEPTOR_STATUSES
    if data.get("required_min_capacity_gal") is not None:
        assert isinstance(data["required_min_capacity_gal"], int)
    if data.get("sizing_method") is not None:
        assert data["sizing_method"] in ("PROVISIONAL", "MEASURED")


def assert_inspection(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["establishment_id"], str)
    assert isinstance(data["items"], list)
    for item in data["items"]:
        assert item["category"] in _INSPECTION_CATEGORIES
        assert item["severity"] in _SEVERITIES
    assert isinstance(data["inspector_user_id"], str)
    assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    assert isinstance(data["passed"], bool)
    assert (data["score"] >= 70) == data["passed"], (
        "passed must agree with the score >= 70 threshold"
    )


def assert_violation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["establishment_id"], str)
    assert isinstance(data["inspection_id"], str)
    assert data["severity"] in _SEVERITIES
    assert data["status"] in _VIOLATION_STATUSES
    assert is_iso8601_timestamp(data["cure_deadline"])
    assert isinstance(data["fine_cents"], int) and data["fine_cents"] >= 0
    assert isinstance(data["recorded_by_user_id"], str)


def assert_pump_manifest(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["establishment_id"], str)
    assert isinstance(data["interceptor_id"], str)
    assert isinstance(data["hauler_id"], str)
    assert is_iso8601_timestamp(data["pump_date"])
    assert data["pumped_volume_gal"] > 0
    assert data["status"] in _MANIFEST_STATUSES
    assert isinstance(data["submitted_by_user_id"], str)
    if data.get("reject_reason") is not None:
        assert data["reject_reason"] in _REJECT_REASONS


def assert_hauler(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    assert is_iso8601_timestamp(data["insurance_expires_on"])
    assert data["status"] in _HAULER_STATUSES
    assert isinstance(data["mismatch_count"], int) and data["mismatch_count"] >= 0


def assert_disposal_record(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["hauler_id"], str)
    assert isinstance(data["manifest_id"], str)
    assert data["disposed_volume_gal"] > 0
    assert isinstance(data["disposal_site_name"], str)
    assert is_iso8601_timestamp(data["disposed_at"])


def assert_blockage_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["location_description"], str)
    assert data["status"] in _BLOCKAGE_STATUSES
    assert isinstance(data["reported_by_user_id"], str)
    if data.get("total_cleanup_cost_cents") is not None:
        assert isinstance(data["total_cleanup_cost_cents"], int)
    if data.get("contributions") is not None:
        for contrib in data["contributions"]:
            assert isinstance(contrib["establishment_id"], str)
            assert isinstance(contrib["weight_percent"], int)


def assert_variance_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["establishment_id"], str)
    assert data["scope"] in _VARIANCE_SCOPES
    assert isinstance(data["justification"], str)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in _VARIANCE_STATUSES


def assert_campaign(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["outreach_zone"], str)
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] >= 0
    assert isinstance(data["remaining_budget_cents"], int)


def assert_outreach_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["campaign_id"], str)
    assert is_iso8601_timestamp(data["event_date"])
    assert isinstance(data["venue_name"], str)
    assert isinstance(data["attendance_count"], int) and data["attendance_count"] >= 0
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0
    assert data["status"] in _EVENT_STATUSES


def assert_campaign_budget_invariant(campaign: dict, recorded_events: list):
    """remaining_budget_cents == budget_cents minus the summed costs of the
    campaign's RECORDED events."""
    spent = sum(e["cost_cents"] for e in recorded_events
                if e["status"] == "RECORDED")
    assert campaign["remaining_budget_cents"] == campaign["budget_cents"] - spent, (
        f"remaining_budget_cents {campaign['remaining_budget_cents']} != "
        f"budget {campaign['budget_cents']} - recorded spend {spent}"
    )
