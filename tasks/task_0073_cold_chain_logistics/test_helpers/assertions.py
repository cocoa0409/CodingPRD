"""Per-entity assertions and domain invariant checkers.

Every assertion uses PRD-exact field names. Where the PRD declares the
entity to be an immutable lifecycle artefact (PRD §2.4: HandoverRecord,
ResponseAction, TemperatureReading, AuditLogEntry), assertions do NOT
demand updated_at / version fields.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Set

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Enum sets — derived from PRD prose
# ---------------------------------------------------------------------------
VEHICLE_STATUS_SET = {"AVAILABLE", "IN_USE", "OUT_OF_SERVICE"}
DRIVER_STATUS_SET = {"OFF_DUTY", "ON_DUTY", "SUSPENDED"}
TRANSPORT_TASK_STATUS_SET = {
    "PLANNED", "DISPATCHED", "IN_TRANSIT", "AT_STOP",
    "DELIVERED", "CLOSED", "ABORTED",
}
TASK_STOP_STATUS_SET = {"PENDING", "ARRIVED", "HANDED_OVER", "SKIPPED"}
CARGO_TYPE_SET = {"FOOD", "PHARMACEUTICAL", "BIOLOGICAL"}
SENSOR_KIND_SET = {"COMPARTMENT", "CARGO_BOX"}
READING_VALIDITY_SET = {
    "VALID", "INVALID_OUT_OF_WINDOW", "INVALID_SCHEMA", "ARCHIVED",
}
VIOLATION_SET = {"WITHIN", "BELOW_MIN", "ABOVE_MAX"}
ALERT_LEVEL_SET = {"WARNING", "MAJOR", "CRITICAL"}
ALERT_STATUS_SET = {
    "OPEN", "ACKNOWLEDGED", "IN_RESPONSE", "ESCALATED",
    "RESOLVED", "CLOSED",
}
NOTIFY_CHANNEL_SET = {"DRIVER", "DISPATCH", "CUSTOMER"}
ACTION_KIND_SET = {
    "VENTILATION", "REFRIGERATION_ADJUSTMENT",
    "TRANSSHIPMENT", "INSPECTION",
}
DAMAGE_CLASS_SET = {"MINOR", "MODERATE", "TOTAL_LOSS"}
CAUSE_PRIMARY_SET = {
    "TEMPERATURE_DEVIATION", "DURATION", "CARGO_SENSITIVITY", "OTHER",
}
DAMAGE_VARIANT_SET = {"INSURED_VALUE", "INVOICE_VALUE"}
DAMAGE_ASSESSMENT_STATUS_SET = {"DRAFT", "FINALIZED"}
SPLIT_METHOD_SET = {"DURATION_WEIGHTED", "SEVERITY_WEIGHTED"}
RESP_DECISION_STATUS_SET = {
    "DRAFT", "UNDER_REVIEW", "DISPUTED",
    "MEDIATION", "ACCEPTED", "FINALIZED",
}
INSURANCE_CLAIM_STATUS_SET = {
    "REPORTED", "EVIDENCE_PREP", "ASSESSMENT", "NEGOTIATING",
    "REJECTED", "PAID_OUT", "SUBROGATION", "CLOSED",
}
COMPLIANCE_REPORT_STATUS_SET = {
    "DRAFT", "GENERATED", "SUBMITTED", "ACKNOWLEDGED",
}
AUDIT_SUBJECT_TYPE_SET = {"ALERT", "RESPONSIBILITY_DECISION"}
AUDIT_ACTION_SET = {
    "OPENED", "ACKNOWLEDGED", "RESPONSE_RECORDED", "ESCALATED",
    "RESOLVED", "CLOSED", "DRAFTED", "UNDER_REVIEW",
    "DISPUTED", "MEDIATED", "ACCEPTED", "FINALIZED",
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def _check_common_fields(data: dict, entity_name: str) -> None:
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, "
        f"got {data.get('created_at')!r}"
    )


def _check_common_versioned(data: dict, entity_name: str) -> None:
    _check_common_fields(data, entity_name)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity_name}.version must be int, "
        f"got {type(data.get('version')).__name__}"
    )
    assert data["version"] >= 1


# ---------------------------------------------------------------------------
# Versioned entities
# ---------------------------------------------------------------------------
def assert_vehicle(data: dict) -> None:
    _check_common_versioned(data, "Vehicle")
    assert isinstance(data.get("vehicle_no"), str) and len(data["vehicle_no"]) >= 1
    assert isinstance(data.get("compartment_count"), int)
    assert 1 <= data["compartment_count"] <= 6
    assert isinstance(data.get("insured_cap_cents"), int)
    assert data["insured_cap_cents"] > 0
    assert data.get("status") in VEHICLE_STATUS_SET


def assert_driver(data: dict) -> None:
    _check_common_versioned(data, "Driver")
    assert isinstance(data.get("license_no"), str) and len(data["license_no"]) >= 1
    assert isinstance(data.get("name"), str) and len(data["name"]) >= 1
    assert isinstance(data.get("max_daily_minutes"), int)
    assert 1 <= data["max_daily_minutes"] <= 1440
    assert data.get("status") in DRIVER_STATUS_SET


def assert_transport_task(data: dict) -> None:
    _check_common_versioned(data, "TransportTask")
    assert data.get("cargo_type") in CARGO_TYPE_SET
    assert isinstance(data.get("cargo_value_cents"), int)
    assert data["cargo_value_cents"] > 0
    assert isinstance(data.get("cargo_quantity"), int)
    assert data["cargo_quantity"] > 0
    assert isinstance(data.get("temp_min_celsius"), (int, float))
    assert isinstance(data.get("temp_max_celsius"), (int, float))
    assert data["temp_min_celsius"] < data["temp_max_celsius"]
    assert isinstance(data.get("shipper_id"), str)
    assert isinstance(data.get("carrier_id"), str)
    assert isinstance(data.get("consignee_id"), str)
    assert is_iso8601_timestamp(data["planned_start_at"])
    assert is_iso8601_timestamp(data["planned_end_at"])
    assert data["planned_end_at"] > data["planned_start_at"]
    assert isinstance(data.get("polling_interval_seconds"), int)
    assert 10 <= data["polling_interval_seconds"] <= 3600
    assert data.get("status") in TRANSPORT_TASK_STATUS_SET


def assert_task_stop(data: dict) -> None:
    _check_common_versioned(data, "TaskStop")
    assert isinstance(data.get("task_id"), str)
    assert isinstance(data.get("sequence"), int) and data["sequence"] >= 1
    assert isinstance(data.get("location_label"), str)
    assert is_iso8601_timestamp(data["planned_arrival_at"])
    assert data.get("status") in TASK_STOP_STATUS_SET
    assert isinstance(data.get("handover_required"), bool)
    actual = data.get("actual_arrival_at")
    if actual is not None:
        assert is_iso8601_timestamp(actual)


def assert_alert(data: dict) -> None:
    _check_common_versioned(data, "Alert")
    assert isinstance(data.get("task_id"), str)
    assert isinstance(data.get("opening_reading_id"), str)
    assert data.get("violation") in {"BELOW_MIN", "ABOVE_MAX"}
    assert data.get("level") in ALERT_LEVEL_SET
    assert isinstance(data.get("duration_seconds"), int)
    assert data["duration_seconds"] >= 0
    assert isinstance(data.get("peak_deviation_celsius"), (int, float))
    assert data["peak_deviation_celsius"] >= 0
    assert isinstance(data.get("notified_channels"), list)
    for ch in data["notified_channels"]:
        assert ch in NOTIFY_CHANNEL_SET
    assert data.get("status") in ALERT_STATUS_SET
    assert is_iso8601_timestamp(data["opened_at"])
    resolved = data.get("resolved_at")
    if resolved is not None:
        assert is_iso8601_timestamp(resolved)


def assert_damage_assessment(data: dict) -> None:
    _check_common_versioned(data, "DamageAssessment")
    assert isinstance(data.get("task_id"), str)
    assert isinstance(data.get("damaged_quantity"), int)
    assert data["damaged_quantity"] >= 1
    assert data.get("damage_class") in DAMAGE_CLASS_SET
    assert isinstance(data.get("salvage_pct"), (int, float))
    assert 0.00 <= float(data["salvage_pct"]) <= 0.99
    assert data.get("cause_primary") in CAUSE_PRIMARY_SET
    assert isinstance(data.get("evidence_alert_ids"), list)
    assert isinstance(data.get("damage_amount_cents"), int)
    assert data["damage_amount_cents"] >= 0
    assert data.get("variant") in DAMAGE_VARIANT_SET
    assert data.get("status") in DAMAGE_ASSESSMENT_STATUS_SET


def assert_responsibility_decision(data: dict) -> None:
    _check_common_versioned(data, "ResponsibilityDecision")
    assert isinstance(data.get("task_id"), str)
    assert isinstance(data.get("assessment_id"), str)
    for k in ("shipper_pct", "carrier_pct", "consignee_pct"):
        assert isinstance(data.get(k), (int, float)), (
            f"ResponsibilityDecision.{k} must be numeric"
        )
        assert 0.00 <= float(data[k]) <= 1.00
    assert data.get("split_method") in SPLIT_METHOD_SET
    assert data.get("status") in RESP_DECISION_STATUS_SET


def assert_insurance_claim(data: dict) -> None:
    _check_common_versioned(data, "InsuranceClaim")
    assert isinstance(data.get("task_id"), str)
    assert isinstance(data.get("decision_id"), str)
    assert isinstance(data.get("requested_amount_cents"), int)
    assert data["requested_amount_cents"] >= 0
    assert data.get("status") in INSURANCE_CLAIM_STATUS_SET


def assert_compliance_report(data: dict) -> None:
    _check_common_versioned(data, "ComplianceReport")
    assert data.get("regulatory_domain") in CARGO_TYPE_SET
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["period_end"] > data["period_start"]
    assert data.get("status") in COMPLIANCE_REPORT_STATUS_SET


# ---------------------------------------------------------------------------
# Append-only entities — PRD §2.4 says id + created_at ONLY
# ---------------------------------------------------------------------------
def assert_handover_record(data: dict) -> None:
    _check_common_fields(data, "HandoverRecord")
    assert isinstance(data.get("stop_id"), str)
    assert isinstance(data.get("task_id"), str)
    assert isinstance(data.get("from_party_id"), str)
    assert isinstance(data.get("to_party_id"), str)
    assert isinstance(data.get("temperature_at_handover_celsius"), (int, float))
    assert isinstance(data.get("quantity_attested"), int)
    assert data["quantity_attested"] >= 0
    assert isinstance(data.get("photo_evidence_ref"), str)
    assert is_iso8601_timestamp(data["handed_over_at"])


def assert_response_action(data: dict) -> None:
    _check_common_fields(data, "ResponseAction")
    assert isinstance(data.get("alert_id"), str)
    assert data.get("action_kind") in ACTION_KIND_SET
    assert data.get("executed_by_role") in {"DRIVER", "DISPATCHER"}
    notes = data.get("notes")
    if notes is not None:
        assert isinstance(notes, str)
        assert 0 <= len(notes) <= 500
    assert is_iso8601_timestamp(data["executed_at"])


def assert_temperature_reading(data: dict) -> None:
    _check_common_fields(data, "TemperatureReading")
    assert isinstance(data.get("task_id"), str)
    assert isinstance(data.get("sensor_id"), str)
    assert data.get("sensor_kind") in SENSOR_KIND_SET
    assert isinstance(data.get("temperature_celsius"), (int, float))
    assert isinstance(data.get("gps_lat"), (int, float))
    assert isinstance(data.get("gps_lng"), (int, float))
    assert is_iso8601_timestamp(data["captured_at"])
    assert isinstance(data.get("idempotency_key"), str)
    assert data.get("validity") in READING_VALIDITY_SET
    assert data.get("violation") in VIOLATION_SET


def assert_audit_log_entry(data: dict) -> None:
    _check_common_fields(data, "AuditLogEntry")
    assert data.get("subject_type") in AUDIT_SUBJECT_TYPE_SET
    assert isinstance(data.get("subject_id"), str)
    assert data.get("action") in AUDIT_ACTION_SET
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert is_iso8601_timestamp(data["occurred_at"])


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_alert_level_consistent(alert: dict) -> None:
    """PRD §3.6: 'if duration_seconds is at least 1800 seconds, or
    peak_deviation_celsius is at least 5.00 degrees Celsius, the level
    is CRITICAL; otherwise, if duration_seconds is at least 600 seconds,
    or peak_deviation_celsius is at least 2.00 degrees Celsius, the
    level is MAJOR; otherwise the level is WARNING.'"""
    dur = alert["duration_seconds"]
    peak = float(alert["peak_deviation_celsius"])
    if dur >= 1800 or peak >= 5.00:
        expected = "CRITICAL"
    elif dur >= 600 or peak >= 2.00:
        expected = "MAJOR"
    else:
        expected = "WARNING"
    assert alert["level"] == expected, (
        f"Alert level mismatch: expected {expected} for "
        f"duration={dur}, peak={peak}, got {alert['level']}"
    )


def assert_alert_channels_for_level(alert: dict) -> None:
    """PRD §3.6: 'When level is WARNING, the level's contributed channel
    set is DRIVER. When level is MAJOR, the contributed set is DRIVER
    together with DISPATCH. When level is CRITICAL, the contributed
    set is DRIVER, DISPATCH, and CUSTOMER. The alert's notified_channels
    is the union of its prior value with the new contribution.'"""
    level = alert["level"]
    required_subsets = {
        "WARNING": {"DRIVER"},
        "MAJOR": {"DRIVER", "DISPATCH"},
        "CRITICAL": {"DRIVER", "DISPATCH", "CUSTOMER"},
    }
    expected = required_subsets[level]
    actual: Set[str] = set(alert["notified_channels"])
    missing = expected - actual
    assert not missing, (
        f"Alert.notified_channels missing {missing} at level={level}; "
        f"actual={actual}"
    )


def assert_payout_invariant(claim: dict, expected_assessed: int,
                            expected_subrogation: int) -> None:
    """PRD §3.11: 'the net insurer outflow in cents equals the payout
    amount, which after subrogation equals assessed_amount_cents minus
    subrogation_recovered_cents.'"""
    payout = claim["payout_amount_cents"]
    expected_payout = max(0, expected_assessed - expected_subrogation)
    assert payout == expected_payout, (
        f"Payout invariant violated: expected "
        f"max(0, {expected_assessed} - {expected_subrogation}) "
        f"= {expected_payout}, got {payout}"
    )


def assert_split_sums_to_one(decision: dict) -> None:
    """PRD §3.10: 'The three percentages must sum to 1.00 exactly when
    rounded half up to two decimals.'"""
    from decimal import Decimal, ROUND_HALF_UP
    parts = [decision[k] for k in ("shipper_pct", "carrier_pct", "consignee_pct")]
    total = sum(Decimal(str(p)) for p in parts)
    rounded = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert rounded == Decimal("1.00"), (
        f"Split sum != 1.00: shipper+carrier+consignee = {total} "
        f"(rounded {rounded})"
    )


def assert_version_changed(before: dict, after: dict,
                           min_increment: int = 1) -> None:
    """PRD §2.4: 'a monotonic integer version that increments by one on
    every mutation.'"""
    assert after["version"] >= before["version"] + min_increment, (
        f"version did not advance: before={before.get('version')} "
        f"after={after.get('version')} expected_min_delta={min_increment}"
    )


def assert_error_envelope(data: dict, expected_error_id: str) -> None:
    assert data.get("error_id") == expected_error_id, (
        f"error_id mismatch: expected {expected_error_id}, "
        f"got {data.get('error_id')}"
    )
    assert isinstance(data.get("message"), str) and data["message"]


def find_by_id(items: Iterable[dict], target_id: str) -> Optional[dict]:
    for it in items:
        if it.get("id") == target_id:
            return it
    return None


__all__ = [
    "VEHICLE_STATUS_SET", "DRIVER_STATUS_SET",
    "TRANSPORT_TASK_STATUS_SET", "TASK_STOP_STATUS_SET",
    "CARGO_TYPE_SET", "SENSOR_KIND_SET", "READING_VALIDITY_SET",
    "VIOLATION_SET", "ALERT_LEVEL_SET", "ALERT_STATUS_SET",
    "NOTIFY_CHANNEL_SET", "ACTION_KIND_SET",
    "DAMAGE_CLASS_SET", "CAUSE_PRIMARY_SET",
    "DAMAGE_VARIANT_SET", "DAMAGE_ASSESSMENT_STATUS_SET",
    "SPLIT_METHOD_SET", "RESP_DECISION_STATUS_SET",
    "INSURANCE_CLAIM_STATUS_SET", "COMPLIANCE_REPORT_STATUS_SET",
    "AUDIT_SUBJECT_TYPE_SET", "AUDIT_ACTION_SET",
    "assert_vehicle", "assert_driver",
    "assert_transport_task", "assert_task_stop", "assert_alert",
    "assert_damage_assessment", "assert_responsibility_decision",
    "assert_insurance_claim", "assert_compliance_report",
    "assert_handover_record", "assert_response_action",
    "assert_temperature_reading", "assert_audit_log_entry",
    "assert_alert_level_consistent", "assert_alert_channels_for_level",
    "assert_payout_invariant", "assert_split_sums_to_one",
    "assert_version_changed", "assert_error_envelope", "find_by_id",
]
