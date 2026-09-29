"""Entity assertions and domain invariant checkers for the EAS Compliance API."""

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import COMPLIANT_MIN_SCORE, WATCH_MIN_SCORE


# ---------------------------------------------------------------------------
# Shared audit-field helpers (PRD §2.5)
# ---------------------------------------------------------------------------
def assert_audit_fields(data: dict) -> None:
    """Every stored row carries a UUID id and an ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_versioned_audit_fields(data: dict) -> None:
    """Resources that are not append-only also carry updated_at and version."""
    assert_audit_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_immutable_audit_fields(data: dict) -> None:
    """Immutable resources expose only id and created_at among audit fields."""
    assert_audit_fields(data)
    assert "updated_at" not in data, "immutable resources carry no updated_at"
    assert "version" not in data, "immutable resources carry no version"


def assert_two_decimals(value) -> None:
    """Scores, points and hours are decimals rounded to exactly 2 places."""
    assert isinstance(value, (int, float)), f"expected a JSON number, got {value!r}"
    assert not isinstance(value, str), "numeric figures are returned as numbers"
    assert_cost_precision(float(value))


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_state_plan(data: dict) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["plan_version_label"], str)
    assert isinstance(data["required_source_types"], list)
    assert data["required_source_count"] == len(data["required_source_types"])
    assert isinstance(data["mandatory_relay_event_codes"], list)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")


def assert_station(data: dict) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["call_sign"], str)
    assert data["service_type"] in ("TV", "FM", "AM", "CABLE")
    assert isinstance(data["engineer_user_ids"], list) and data["engineer_user_ids"]
    assert isinstance(data["certification_officer_user_id"], str)
    assert data["compliance_posture"] in (
        "PROVISIONING",
        "COMPLIANT",
        "WATCH",
        "SUSPENDED_FILINGS",
    )
    if data["compliance_score"] is not None:
        assert_two_decimals(data["compliance_score"])
    assert data["compliance_variant_applied"] in (None, "PROVISIONAL", "CERTIFIED")
    assert isinstance(data["accessible_source_count"], int)
    assert isinstance(data["silent_assignment_count"], int)
    assert_two_decimals(data["penalty_points_total"])
    assert isinstance(data["plan_revalidation_required"], bool)
    assert isinstance(data["public_file_document_count"], int)


def assert_relay_rule(data: dict) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["event_code"], str)
    assert isinstance(data["fips_codes"], list)
    assert data["relay_class"] in ("MANDATORY", "OPTIONAL")
    assert 1 <= data["priority"] <= 100
    assert 0 <= data["forward_delay_seconds"] <= 600
    assert data["specificity"] == (2 if data["fips_codes"] else 1)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_device(data: dict) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["station_id"], str)
    assert data["device_role"] in ("DECODER", "ENCODER", "MONITOR")
    assert data["status"] in ("REGISTERED", "READY", "FAILED", "DECOMMISSIONED")
    assert isinstance(data["readiness_check_passed"], bool)


def assert_monitoring_assignment(data: dict) -> None:
    assert_versioned_audit_fields(data)
    assert data["source_type"] in ("PEP", "NWS", "LP1", "LP2", "SATELLITE", "IPAWS")
    assert isinstance(data["source_call_sign"], str)
    assert data["status"] in ("ACTIVE", "SILENT", "SUSPENDED", "DECOMMISSIONED")
    assert isinstance(data["counts_toward_required_sources"], bool)


def assert_equipment_outage(data: dict) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["device_id"], str)
    assert is_iso8601_timestamp(data["detected_at"])
    assert is_iso8601_timestamp(data["notified_at"])
    assert data["status"] in (
        "OPEN",
        "REPAIR_IN_PROGRESS",
        "RESTORED",
        "VERIFICATION_FAILED",
        "CLOSED",
    )
    assert isinstance(data["repair_cycle_count"], int)
    assert isinstance(data["continuous_clock_breached"], bool)
    assert isinstance(data["obligation_breached"], bool)
    for field in ("continuous_downtime_hours", "obligation_downtime_hours"):
        if data[field] is not None:
            assert_two_decimals(data[field])


def assert_alert_event(data: dict) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["fips_codes"], list) and data["fips_codes"]
    assert data["relay_state"] in (
        "RECEIVED",
        "RELAY_PENDING",
        "RELAYED",
        "UNMATCHED_OPTIONAL",
        "SUPPRESSED_DUPLICATE",
    )
    assert data["relay_class_applied"] in ("NONE", "MANDATORY", "OPTIONAL")
    assert isinstance(data["forward_delay_seconds_applied"], int)
    assert data["suppression_source"] in ("NONE", "STATION_REPEAT", "WIRELESS_NOTICE")
    assert data["accessibility_state"] in (
        "ACCESSIBILITY_UNVERIFIED",
        "ACCESSIBILITY_PASSED",
        "ACCESSIBILITY_FAILED",
    )
    if data.get("accessibility_deficiency_points") is not None:
        assert_two_decimals(data["accessibility_deficiency_points"])


def assert_wireless_alert_notice(data: dict) -> None:
    assert_immutable_audit_fields(data)
    assert isinstance(data["originator_sequence"], str)
    assert isinstance(data["fips_codes"], list) and data["fips_codes"]
    assert is_iso8601_timestamp(data["wea_sent_at"])


def assert_test_event(data: dict) -> None:
    assert_versioned_audit_fields(data)
    assert data["test_type"] in ("WEEKLY", "MONTHLY", "NATIONAL")
    assert data["window_start_at"] < data["window_end_at"]
    assert is_iso8601_timestamp(data["filing_deadline_at"])
    assert data["status"] in (
        "SCHEDULED",
        "READINESS_PENDING",
        "READY",
        "LOGGED",
        "FILED",
        "FAILED_UNFILED",
    )
    if data["readiness_score"] is not None:
        assert_two_decimals(data["readiness_score"])
    assert isinstance(data["logged_entry_count"], int)


def assert_test_log_entry(data: dict) -> None:
    assert_immutable_audit_fields(data)
    assert data["entry_kind"] in ("TRANSMISSION", "RECEIPT")
    assert isinstance(data["logged_by_user_id"], str)
    assert is_iso8601_timestamp(data["logged_at"])
    assert isinstance(data["retention_days_applied"], int)
    assert is_iso8601_timestamp(data["retention_until"])
    if data["entry_kind"] == "RECEIPT":
        assert data.get("source_call_sign"), "a RECEIPT line names its source"


def assert_filing_record(data: dict) -> None:
    assert_versioned_audit_fields(data)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REVERSED")
    assert isinstance(data["late_days"], int)
    for field in (
        "entry_subtotal_points",
        "lateness_points",
        "unconfirmed_relay_points",
        "penalty_points",
    ):
        assert_two_decimals(data[field])
    assert is_iso8601_timestamp(data["filed_at"])
    assert isinstance(data["filed_by_user_id"], str)


def assert_inspection_request(data: dict) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["requested_document_kinds"], list)
    assert data["requested_document_kinds"], "requested kinds are non-empty"
    assert isinstance(data["provided_document_kinds"], list)
    assert data["status"] in (
        "OPEN",
        "RESPONSE_DRAFTED",
        "RESPONDED",
        "CLOSED_SATISFIED",
        "CLOSED_DEFICIENT",
    )
    if data["completeness_score"] is not None:
        assert_two_decimals(data["completeness_score"])


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def posture_for_score(score: float) -> str:
    """The band mapping of PRD §2.10, both thresholds inclusive at their lower bound."""
    if score >= COMPLIANT_MIN_SCORE:
        return "COMPLIANT"
    if score >= WATCH_MIN_SCORE:
        return "WATCH"
    return "SUSPENDED_FILINGS"


def assert_score_and_posture(data: dict, expected_score: float, expected_posture=None) -> None:
    """A station (or its compliance summary) scored exactly `expected_score`, with
    the posture the band mapping implies unless one is given explicitly."""
    assert data["compliance_score"] == pytest.approx(expected_score, abs=0.01), (
        f"expected compliance_score {expected_score}, got {data['compliance_score']}"
    )
    expected_posture = expected_posture or posture_for_score(expected_score)
    assert data["compliance_posture"] == expected_posture, (
        f"expected posture {expected_posture}, got {data['compliance_posture']}"
    )


def assert_summary_inputs(summary: dict, **expected) -> None:
    """Assert named compliance-summary inputs, comparing points figures at 2dp."""
    for field, value in expected.items():
        actual = summary[field]
        if isinstance(value, float):
            assert actual == pytest.approx(value, abs=0.01), (
                f"expected {field} == {value}, got {actual}"
            )
        else:
            assert actual == value, f"expected {field} == {value}, got {actual}"


def assert_missing_source_count(summary: dict) -> None:
    """missing_source_count is the floored difference between required and accessible."""
    expected = max(0, summary["required_source_count"] - summary["accessible_source_count"])
    assert summary["missing_source_count"] == expected


def assert_suppressed(data: dict, expected_source: str, expected_reference=None) -> None:
    """A suppressed alert keeps matched_relay_rule_id null and relay_class_applied NONE."""
    assert data["relay_state"] == "SUPPRESSED_DUPLICATE"
    assert data["suppression_source"] == expected_source
    assert data["suppression_reference_alert_id"] == expected_reference
    assert data["matched_relay_rule_id"] is None
    assert data["relay_class_applied"] == "NONE"
    assert data["forward_delay_seconds_applied"] == 0


def assert_not_suppressed(data: dict) -> None:
    assert data["suppression_source"] == "NONE"
    assert data["suppression_reference_alert_id"] is None
    assert data["relay_state"] != "SUPPRESSED_DUPLICATE"


def assert_matched_rule(data: dict, rule_id: str, relay_class: str, delay_seconds: int) -> None:
    assert data["relay_state"] == "RELAY_PENDING"
    assert data["matched_relay_rule_id"] == rule_id
    assert data["relay_class_applied"] == relay_class
    assert data["forward_delay_seconds_applied"] == delay_seconds


def assert_unmatched(data: dict) -> None:
    assert data["relay_state"] == "UNMATCHED_OPTIONAL"
    assert data["matched_relay_rule_id"] is None
    assert data["relay_class_applied"] == "NONE"
    assert data["forward_delay_seconds_applied"] == 0
