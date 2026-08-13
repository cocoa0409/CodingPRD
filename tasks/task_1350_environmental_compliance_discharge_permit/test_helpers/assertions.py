"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def round_half_up(value, places: int) -> Decimal:
    """Round-half-up to the given decimal places (PRD §2.6 rounding convention)."""
    quant = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional digits.

    PRD §2.4 requires ISO 8601 UTC timestamps; instants are compared at
    one-second granularity (§2.6), so equality between an API-rendered
    timestamp and an expected instant is always computed on parsed values.
    """
    assert isinstance(value, str), f"Expected ISO timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant") -> None:
    """Assert two ISO instants denote the same second (§2.6 granularity rule)."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict, entity_label: str) -> None:
    """Primary-resource common fields (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be an integer"


def _assert_append_only_fields(data: dict, entity_label: str) -> None:
    """Append-only records carry id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{entity_label} must not carry updated_at"
    assert "version" not in data, f"{entity_label} must not carry version"


def assert_permit(data: dict) -> None:
    _assert_common_fields(data, "Permit")
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    assert isinstance(data["facility_name"], str)
    assert isinstance(data["receiving_water_body"], str)
    assert_instant_equals(data["effective_date"], data["effective_date"], "effective_date")
    assert data["status"] in ["DRAFT", "ACTIVE", "EXPIRED", "SUPERSEDED", "TERMINATED"]
    assert data["compliance_posture"] in [
        "GOOD_STANDING", "UNDER_CORRECTIVE_ACTION", "ENFORCEMENT",
    ]
    assert isinstance(data["open_corrective_action_count"], int)
    assert isinstance(data["open_exceedance_count"], int)
    assert data["open_corrective_action_count"] >= 0
    assert data["open_exceedance_count"] >= 0


def assert_outfall(data: dict) -> None:
    _assert_common_fields(data, "Outfall")
    assert is_valid_uuid(data.get("permit_id", "")), "Outfall.permit_id must be a UUID"
    assert isinstance(data["outfall_number"], str) and data["outfall_number"]
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_effluent_limit(data: dict) -> None:
    _assert_common_fields(data, "EffluentLimit")
    assert is_valid_uuid(data.get("outfall_id", "")), "EffluentLimit.outfall_id must be a UUID"
    assert data["parameter_code"] in [
        "BOD5", "TSS", "PH", "AMMONIA_N", "COPPER", "FECAL_COLIFORM",
    ]
    assert data["limit_type"] in ["DAILY_MAX", "MONTHLY_AVG"]
    assert data["limit_value"] > 0
    assert data["unit"] in ["MG_L", "SU", "MPN_100ML"]
    assert data["monitoring_frequency"] in ["WEEKLY", "MONTHLY"]
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "RESCINDED"]


def assert_sampling_event(data: dict) -> None:
    _assert_common_fields(data, "SamplingEvent")
    assert is_valid_uuid(data.get("outfall_id", "")), "SamplingEvent.outfall_id must be a UUID"
    assert data["schedule_status"] in ["SCHEDULED", "COLLECTED", "CLOSED", "MISSED", "CANCELLED"]
    assert data["custody_status"] in [
        "NOT_SEALED", "SEALED", "IN_TRANSIT", "LAB_RECEIVED", "ANALYZED",
    ]
    assert isinstance(data["collection_window_hours"], int)
    assert 1 <= data["collection_window_hours"] <= 168


def assert_custody_record(data: dict) -> None:
    _assert_append_only_fields(data, "ChainOfCustodyRecord")
    assert data["event_type"] in ["SEAL", "TRANSFER", "RECEIVE_LAB", "ANALYSIS_START"]
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_lab_result(data: dict) -> None:
    _assert_common_fields(data, "LabResult")
    assert is_valid_uuid(data.get("sampling_event_id", "")), (
        "LabResult.sampling_event_id must be a UUID"
    )
    assert data["validation_status"] in ["SUBMITTED", "VALIDATED", "REJECTED"]
    assert data["reported_value"] >= 0
    assert data["method_detection_limit"] > 0
    assert data["flow_mgd"] > 0
    assert data["qualifier"] in ["NONE", "BELOW_MDL", "ESTIMATED"]
    assert isinstance(data["analyzed_by_user_id"], str) and data["analyzed_by_user_id"]


def assert_exceedance(data: dict) -> None:
    _assert_common_fields(data, "Exceedance")
    assert is_valid_uuid(data.get("lab_result_id", "")), "Exceedance.lab_result_id must be a UUID"
    assert is_valid_uuid(data.get("effluent_limit_id", "")), (
        "Exceedance.effluent_limit_id must be a UUID"
    )
    assert data["notification_status"] in [
        "PENDING_ORAL", "ORAL_OVERDUE", "ORAL_NOTIFIED",
        "WRITTEN_OVERDUE", "WRITTEN_FILED", "CLOSED",
    ]
    assert data["enforcement_status"] in ["NONE", "ORDER_ISSUED", "RESOLVED"]
    expected_pct = round_half_up(
        (Decimal(str(data["reported_value"])) - Decimal(str(data["limit_value"])))
        / Decimal(str(data["limit_value"])) * 100,
        2,
    )
    assert data["percent_over"] == pytest.approx(float(expected_pct), abs=0.001), (
        "percent_over must be the round-half-up 2dp magnitude of the breach"
    )


def assert_dmr(data: dict) -> None:
    _assert_common_fields(data, "DischargeMonitoringReport")
    assert is_valid_uuid(data.get("outfall_id", "")), "DMR.outfall_id must be a UUID"
    assert data["status"] in ["DRAFT", "CERTIFIED", "SUBMITTED", "ACCEPTED", "REJECTED"]
    assert isinstance(data["required_sample_count"], int)
    assert isinstance(data["total_validated_results"], int)
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["summary_lines"], list)
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]


def assert_swppp_plan(data: dict) -> None:
    _assert_common_fields(data, "StormwaterPlan")
    assert is_valid_uuid(data.get("permit_id", "")), "StormwaterPlan.permit_id must be a UUID"
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED"]
    assert isinstance(data["inspection_frequency_days"], int)
    assert 1 <= data["inspection_frequency_days"] <= 365


def assert_inspection(data: dict) -> None:
    _assert_common_fields(data, "Inspection")
    assert is_valid_uuid(data.get("plan_id", "")), "Inspection.plan_id must be a UUID"
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["inspector_user_id"], str) and data["inspector_user_id"]


def assert_corrective_action(data: dict) -> None:
    _assert_common_fields(data, "CorrectiveAction")
    assert data["source_type"] in ["INSPECTION", "EXCEEDANCE"]
    assert data["severity"] in ["CRITICAL", "MAJOR", "MINOR"]
    assert data["status"] in [
        "OPEN", "IN_PROGRESS", "COMPLETED", "VERIFIED", "REOPENED", "CLOSED",
    ]
    assert isinstance(data["is_overdue"], bool)
    assert is_iso8601_timestamp(data.get("deadline_at", "")), (
        "CorrectiveAction.deadline_at must be ISO 8601"
    )


def assert_renewal_application(data: dict) -> None:
    _assert_common_fields(data, "RenewalApplication")
    assert is_valid_uuid(data.get("permit_id", "")), "RenewalApplication.permit_id must be a UUID"
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DENIED",
    ]
    assert is_iso8601_timestamp(data.get("submitted_at", "")), (
        "RenewalApplication.submitted_at must be ISO 8601"
    )


def assert_consent_order(data: dict) -> None:
    _assert_common_fields(data, "ConsentOrder")
    assert is_valid_uuid(data.get("exceedance_id", "")), (
        "ConsentOrder.exceedance_id must be a UUID"
    )
    assert data["assessment_variant"] in ["PER_DAY", "ECONOMIC_BENEFIT"]
    assert data["status"] in ["PROPOSED", "ISSUED", "UNDER_APPEAL", "FINAL", "SATISFIED"]
    assert data["base_penalty_cents"] > 0
    assert data["statutory_cap_cents"] > 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert isinstance(data["refunded_cents"], int) and data["refunded_cents"] >= 0
    assert isinstance(data["outstanding_cents"], int) and data["outstanding_cents"] >= 0


def assert_penalty_payment(data: dict) -> None:
    _assert_append_only_fields(data, "PenaltyPayment")
    assert is_valid_uuid(data.get("consent_order_id", "")), (
        "PenaltyPayment.consent_order_id must be a UUID"
    )
    assert data["direction"] in ["PAYMENT", "REFUND"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] == "POSTED"
    assert is_iso8601_timestamp(data.get("posted_at", "")), (
        "PenaltyPayment.posted_at must be ISO 8601"
    )


def assert_audit_entry(data: dict) -> None:
    _assert_append_only_fields(data, "AuditLogEntry")
    assert isinstance(data["entity_type"], str) and data["entity_type"]
    assert isinstance(data["entity_id"], str) and data["entity_id"]
    assert isinstance(data["action"], str) and data["action"]
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert is_iso8601_timestamp(data.get("occurred_at", "")), (
        "AuditLogEntry.occurred_at must be ISO 8601"
    )
    assert re.fullmatch(r"[0-9a-f]{64}", data.get("prev_entry_hash", "")), (
        "prev_entry_hash must be 64-char lowercase hex"
    )
    assert re.fullmatch(r"[0-9a-f]{64}", data.get("entry_hash", "")), (
        "entry_hash must be 64-char lowercase hex"
    )
