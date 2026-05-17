"""Entity assertions and domain invariant checkers.

Each per-entity assert_<entity>() verifies the PRD-declared shape of a
single response payload. Field names mirror PRD prose exactly.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Status value sets — verbatim from PRD entity descriptions.
# ---------------------------------------------------------------------------
NOTIFICATION_CONSENTS = {"SMS_AND_VOICE", "VOICE_ONLY", "NONE"}
CLINICIAN_ROLE_KINDS = {"ORDERING_PROVIDER", "LAB_TECH", "LAB_DIRECTOR"}
CLIA_COMPLEXITIES = {"WAIVED", "MODERATE", "HIGH"}
SPECIMEN_TYPES = {"BLOOD", "URINE", "CSF", "SWAB"}
LAB_ORDER_PRIORITIES = {"ROUTINE", "STAT"}
LAB_ORDER_STATUSES = {
    "ORDERED", "COLLECTED", "IN_TRANSIT", "RECEIVED",
    "RESULTED", "RELEASED", "CANCELED", "REJECTED",
}
SPECIMEN_STATUSES = {"COLLECTED", "IN_TRANSIT", "RECEIVED", "REJECTED"}
SPECIMEN_REJECTED_REASONS = {
    "STABILITY_EXCEEDED", "CHAIN_BROKEN",
    "CONTAMINATED", "INSUFFICIENT_VOLUME",
}
TRANSPORT_LEG_STATUSES = {"DEPARTED", "ARRIVED", "BROKEN"}
LAB_RESULT_STATUSES = {"DRAFT", "RELEASED", "AMENDED", "RETRACTED"}
NOTIFICATION_CHANNELS = {"SMS", "VOICE"}
NOTIFICATION_STATUSES = {
    "PENDING", "ACKNOWLEDGED", "ESCALATED", "FAILED",
}
RETEST_REASONS = {
    "SPECIMEN_REJECTED", "CRITICAL_UNACKNOWLEDGED", "RESULT_AMENDED",
}
RETEST_STATUSES = {"ISSUED", "FULFILLED", "CANCELED"}
AUDIT_EVENT_TYPES = {
    "ORDER_PLACED", "SPECIMEN_REJECTED", "RESULT_RELEASED",
    "CRITICAL_NOTIFIED", "CRITICAL_ACKED", "CRITICAL_ESCALATED",
    "RETEST_ISSUED", "AMENDMENT_RECORDED",
}


# ---------------------------------------------------------------------------
# Common-field helpers.
# ---------------------------------------------------------------------------
def _assert_common_primary_fields(entity_name: str,
                                  data: Dict[str, Any]) -> None:
    """PRD §2.4: every primary resource carries id, created_at,
    updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity_name}.version must be an integer"
    )
    assert data["version"] >= 1, f"{entity_name}.version must be >= 1"


def _assert_append_only_fields(entity_name: str,
                               data: Dict[str, Any]) -> None:
    """PRD §2.4: append-only entities carry ONLY id + created_at."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )


def assert_version_incremented_by_one(new_version: int,
                                      old_version: int) -> None:
    """PRD §2.10: 'increments `version` by exactly 1 on each mutated
    row.'"""
    assert new_version == old_version + 1, (
        f"version must increment by exactly 1: old={old_version}, "
        f"new={new_version}"
    )


# ---------------------------------------------------------------------------
# Patient — PRD §3.1.
# ---------------------------------------------------------------------------
def assert_patient(data: Dict[str, Any]) -> None:
    """PRD §3.1: Patient carries mrn, full_name, date_of_birth,
    primary_phone_e164, optional backup_phone_e164, and
    notification_consent."""
    _assert_common_primary_fields("Patient", data)
    assert isinstance(data.get("mrn"), str) and data["mrn"], (
        "Patient.mrn must be a non-empty string"
    )
    assert isinstance(data.get("full_name"), str) and data["full_name"], (
        "Patient.full_name must be a non-empty string"
    )
    assert isinstance(data.get("date_of_birth"), str), (
        "Patient.date_of_birth must be an ISO calendar date string"
    )
    assert isinstance(data.get("primary_phone_e164"), str), (
        "Patient.primary_phone_e164 must be a string"
    )
    # backup_phone_e164 optional but must be string-or-null if present.
    if "backup_phone_e164" in data:
        backup = data["backup_phone_e164"]
        assert backup is None or isinstance(backup, str), (
            "Patient.backup_phone_e164 must be string or null"
        )
    # PRD §3.1: notification_consent defaults to SMS_AND_VOICE.
    if "notification_consent" in data:
        assert data["notification_consent"] in NOTIFICATION_CONSENTS, (
            f"Patient.notification_consent must be in "
            f"{NOTIFICATION_CONSENTS}, got "
            f"{data['notification_consent']!r}"
        )


# ---------------------------------------------------------------------------
# Clinician — PRD §3.1.
# ---------------------------------------------------------------------------
def assert_clinician(data: Dict[str, Any]) -> None:
    """PRD §3.1: Clinician carries npi, full_name, role_kind,
    phone_e164, active."""
    _assert_common_primary_fields("Clinician", data)
    assert isinstance(data.get("npi"), str) and data["npi"], (
        "Clinician.npi must be a non-empty string"
    )
    assert isinstance(data.get("full_name"), str) and data["full_name"], (
        "Clinician.full_name must be a non-empty string"
    )
    assert data.get("role_kind") in CLINICIAN_ROLE_KINDS, (
        f"Clinician.role_kind must be in {CLINICIAN_ROLE_KINDS}, "
        f"got {data.get('role_kind')!r}"
    )
    assert isinstance(data.get("phone_e164"), str), (
        "Clinician.phone_e164 must be a string"
    )
    assert isinstance(data.get("active"), bool), (
        "Clinician.active must be a bool"
    )


# ---------------------------------------------------------------------------
# TestPanel — PRD §3.1.
# ---------------------------------------------------------------------------
def assert_test_panel(data: Dict[str, Any]) -> None:
    _assert_common_primary_fields("TestPanel", data)
    assert isinstance(data.get("code"), str) and data["code"], (
        "TestPanel.code must be a non-empty string"
    )
    assert isinstance(data.get("name"), str) and data["name"], (
        "TestPanel.name must be a non-empty string"
    )
    assert data.get("clia_complexity") in CLIA_COMPLEXITIES, (
        f"TestPanel.clia_complexity must be in {CLIA_COMPLEXITIES}, "
        f"got {data.get('clia_complexity')!r}"
    )
    assert data.get("specimen_type") in SPECIMEN_TYPES, (
        f"TestPanel.specimen_type must be in {SPECIMEN_TYPES}, "
        f"got {data.get('specimen_type')!r}"
    )
    assert isinstance(data.get("stability_minutes"), int), (
        "TestPanel.stability_minutes must be an integer"
    )
    assert data["stability_minutes"] > 0, (
        "TestPanel.stability_minutes must be > 0"
    )
    analytes = data.get("analytes")
    assert isinstance(analytes, list) and len(analytes) >= 1, (
        "TestPanel.analytes must be a non-empty list"
    )
    for spec in analytes:
        assert isinstance(spec, dict), "analyte spec must be an object"
        assert isinstance(spec.get("analyte_code"), str), (
            "analyte.analyte_code must be a string"
        )
        assert isinstance(spec.get("unit"), str), (
            "analyte.unit must be a string"
        )
        # bounds may be null individually.
        lo = spec.get("critical_low")
        hi = spec.get("critical_high")
        assert lo is None or isinstance(lo, (int, float)), (
            "analyte.critical_low must be number or null"
        )
        assert hi is None or isinstance(hi, (int, float)), (
            "analyte.critical_high must be number or null"
        )


# ---------------------------------------------------------------------------
# LabOrder — PRD §3.2 / §3.3 / §3.4.
# ---------------------------------------------------------------------------
def assert_lab_order(data: Dict[str, Any]) -> None:
    _assert_common_primary_fields("LabOrder", data)
    assert is_valid_uuid(data.get("patient_id", "")), (
        "LabOrder.patient_id must be a UUID"
    )
    assert is_valid_uuid(data.get("ordering_provider_id", "")), (
        "LabOrder.ordering_provider_id must be a UUID"
    )
    assert is_valid_uuid(data.get("panel_id", "")), (
        "LabOrder.panel_id must be a UUID"
    )
    assert data.get("priority") in LAB_ORDER_PRIORITIES, (
        f"LabOrder.priority must be in {LAB_ORDER_PRIORITIES}, "
        f"got {data.get('priority')!r}"
    )
    assert data.get("status") in LAB_ORDER_STATUSES, (
        f"LabOrder.status must be in {LAB_ORDER_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    assert isinstance(data.get("retest_count"), int), (
        "LabOrder.retest_count must be an integer"
    )
    assert data["retest_count"] >= 0, (
        "LabOrder.retest_count must be >= 0"
    )
    # parent_order_id may be null on first order.
    parent = data.get("parent_order_id")
    assert parent is None or is_valid_uuid(parent), (
        "LabOrder.parent_order_id must be UUID or null"
    )
    assert is_iso8601_timestamp(data.get("ordered_at", "")), (
        "LabOrder.ordered_at must be ISO 8601"
    )


# ---------------------------------------------------------------------------
# Specimen — PRD §3.3.
# ---------------------------------------------------------------------------
def assert_specimen(data: Dict[str, Any]) -> None:
    _assert_common_primary_fields("Specimen", data)
    assert is_valid_uuid(data.get("lab_order_id", "")), (
        "Specimen.lab_order_id must be a UUID"
    )
    assert is_valid_uuid(data.get("collected_by_id", "")), (
        "Specimen.collected_by_id must be a UUID"
    )
    assert is_iso8601_timestamp(data.get("collected_at", "")), (
        "Specimen.collected_at must be ISO 8601"
    )
    rcvd = data.get("received_at")
    assert rcvd is None or is_iso8601_timestamp(rcvd), (
        "Specimen.received_at must be ISO 8601 or null"
    )
    reason = data.get("rejected_reason")
    assert reason is None or reason in SPECIMEN_REJECTED_REASONS, (
        f"Specimen.rejected_reason must be in "
        f"{SPECIMEN_REJECTED_REASONS} or null, got {reason!r}"
    )
    assert data.get("status") in SPECIMEN_STATUSES, (
        f"Specimen.status must be in {SPECIMEN_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# TransportLeg — PRD §3.3 / §2.4 (append-only).
# ---------------------------------------------------------------------------
def assert_transport_leg(data: Dict[str, Any]) -> None:
    """PRD §2.4: TransportLeg is immutable after creation and carries
    only id + created_at — NO updated_at, NO version."""
    _assert_append_only_fields("TransportLeg", data)
    assert is_valid_uuid(data.get("specimen_id", "")), (
        "TransportLeg.specimen_id must be a UUID"
    )
    assert isinstance(data.get("leg_index"), int), (
        "TransportLeg.leg_index must be an integer"
    )
    assert data["leg_index"] >= 1, (
        "TransportLeg.leg_index is 1-based per PRD §3.3"
    )
    assert isinstance(data.get("from_location"), str), (
        "TransportLeg.from_location must be a string"
    )
    assert isinstance(data.get("to_location"), str), (
        "TransportLeg.to_location must be a string"
    )
    assert is_iso8601_timestamp(data.get("departed_at", "")), (
        "TransportLeg.departed_at must be ISO 8601"
    )
    arrived = data.get("arrived_at")
    assert arrived is None or is_iso8601_timestamp(arrived), (
        "TransportLeg.arrived_at must be ISO 8601 or null"
    )
    assert isinstance(data.get("courier_id"), str), (
        "TransportLeg.courier_id must be a string"
    )
    assert data.get("status") in TRANSPORT_LEG_STATUSES, (
        f"TransportLeg.status must be in {TRANSPORT_LEG_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# LabResult — PRD §3.4.
# ---------------------------------------------------------------------------
def assert_lab_result(data: Dict[str, Any]) -> None:
    _assert_common_primary_fields("LabResult", data)
    assert is_valid_uuid(data.get("lab_order_id", "")), (
        "LabResult.lab_order_id must be a UUID"
    )
    assert is_valid_uuid(data.get("resulted_by_id", "")), (
        "LabResult.resulted_by_id must be a UUID"
    )
    released_by = data.get("released_by_id")
    assert released_by is None or is_valid_uuid(released_by), (
        "LabResult.released_by_id must be UUID or null"
    )
    measurements = data.get("measurements")
    assert isinstance(measurements, list), (
        "LabResult.measurements must be a list"
    )
    for m in measurements:
        assert isinstance(m, dict), "measurement entry must be an object"
        assert isinstance(m.get("analyte_code"), str), (
            "measurement.analyte_code must be a string"
        )
        assert isinstance(m.get("value"), (int, float)), (
            "measurement.value must be numeric"
        )
        assert isinstance(m.get("unit"), str), (
            "measurement.unit must be a string"
        )
    critical_flags = data.get("critical_flags")
    assert isinstance(critical_flags, list), (
        "LabResult.critical_flags must be a list"
    )
    for f in critical_flags:
        assert isinstance(f, dict), "critical_flag must be an object"
        assert isinstance(f.get("analyte_code"), str), (
            "critical_flag.analyte_code must be a string"
        )
        assert f.get("side") in {"LOW", "HIGH"}, (
            f"critical_flag.side must be LOW or HIGH, got {f.get('side')!r}"
        )
        assert isinstance(f.get("value"), (int, float)), (
            "critical_flag.value must be numeric"
        )
        assert isinstance(f.get("bound"), (int, float)), (
            "critical_flag.bound must be numeric"
        )
    assert isinstance(data.get("severity_score"), (int, float)), (
        "LabResult.severity_score must be numeric"
    )
    assert data.get("status") in LAB_RESULT_STATUSES, (
        f"LabResult.status must be in {LAB_RESULT_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    assert is_iso8601_timestamp(data.get("resulted_at", "")), (
        "LabResult.resulted_at must be ISO 8601"
    )
    released_at = data.get("released_at")
    assert released_at is None or is_iso8601_timestamp(released_at), (
        "LabResult.released_at must be ISO 8601 or null"
    )


# ---------------------------------------------------------------------------
# CriticalNotification — PRD §3.5.
# ---------------------------------------------------------------------------
def assert_critical_notification(data: Dict[str, Any]) -> None:
    _assert_common_primary_fields("CriticalNotification", data)
    assert is_valid_uuid(data.get("lab_result_id", "")), (
        "CriticalNotification.lab_result_id must be a UUID"
    )
    assert is_valid_uuid(data.get("recipient_clinician_id", "")), (
        "CriticalNotification.recipient_clinician_id must be a UUID"
    )
    assert data.get("channel") in NOTIFICATION_CHANNELS, (
        f"CriticalNotification.channel must be in {NOTIFICATION_CHANNELS},"
        f" got {data.get('channel')!r}"
    )
    assert isinstance(data.get("attempt_count"), int), (
        "CriticalNotification.attempt_count must be an integer"
    )
    assert data["attempt_count"] >= 0, (
        "CriticalNotification.attempt_count must be >= 0"
    )
    assert is_iso8601_timestamp(data.get("first_sent_at", "")), (
        "CriticalNotification.first_sent_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("ack_deadline_at", "")), (
        "CriticalNotification.ack_deadline_at must be ISO 8601"
    )
    assert data.get("status") in NOTIFICATION_STATUSES, (
        f"CriticalNotification.status must be in {NOTIFICATION_STATUSES},"
        f" got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# AcknowledgementReceipt — PRD §3.5 / §2.4 (append-only).
# ---------------------------------------------------------------------------
def assert_acknowledgement_receipt(data: Dict[str, Any]) -> None:
    """PRD §2.4: AcknowledgementReceipt is append-only — only id +
    created_at; supplying or expecting updated_at/version is a contract
    error."""
    _assert_append_only_fields("AcknowledgementReceipt", data)
    assert is_valid_uuid(data.get("critical_notification_id", "")), (
        "AcknowledgementReceipt.critical_notification_id must be a UUID"
    )
    assert is_valid_uuid(data.get("acknowledged_by_id", "")), (
        "AcknowledgementReceipt.acknowledged_by_id must be a UUID"
    )
    assert is_iso8601_timestamp(data.get("acknowledged_at", "")), (
        "AcknowledgementReceipt.acknowledged_at must be ISO 8601"
    )
    assert isinstance(data.get("read_back_text"), str), (
        "AcknowledgementReceipt.read_back_text must be a string"
    )
    assert isinstance(data.get("ack_latency_minutes"), (int, float)), (
        "AcknowledgementReceipt.ack_latency_minutes must be numeric"
    )


# ---------------------------------------------------------------------------
# RetestRequest — PRD §3.7.
# ---------------------------------------------------------------------------
def assert_retest_request(data: Dict[str, Any]) -> None:
    _assert_common_primary_fields("RetestRequest", data)
    assert is_valid_uuid(data.get("lab_order_id", "")), (
        "RetestRequest.lab_order_id must be a UUID"
    )
    assert data.get("reason") in RETEST_REASONS, (
        f"RetestRequest.reason must be in {RETEST_REASONS}, "
        f"got {data.get('reason')!r}"
    )
    new_id = data.get("new_lab_order_id")
    assert new_id is None or is_valid_uuid(new_id), (
        "RetestRequest.new_lab_order_id must be UUID or null"
    )
    assert data.get("status") in RETEST_STATUSES, (
        f"RetestRequest.status must be in {RETEST_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# ComplianceAuditEvent — PRD §3.8 / §2.4 (append-only).
# ---------------------------------------------------------------------------
def assert_compliance_audit_event(data: Dict[str, Any]) -> None:
    _assert_append_only_fields("ComplianceAuditEvent", data)
    assert data.get("event_type") in AUDIT_EVENT_TYPES, (
        f"ComplianceAuditEvent.event_type must be in {AUDIT_EVENT_TYPES},"
        f" got {data.get('event_type')!r}"
    )
    assert is_valid_uuid(data.get("lab_order_id", "")), (
        "ComplianceAuditEvent.lab_order_id must be a UUID"
    )
    # actor_id is either a UUID (human) or the literal string "system"
    # per PRD §2.11.
    actor = data.get("actor_id")
    assert actor == "system" or is_valid_uuid(actor or ""), (
        "ComplianceAuditEvent.actor_id must be Clinician.id UUID "
        "or the literal string 'system'"
    )
    assert isinstance(data.get("payload"), dict), (
        "ComplianceAuditEvent.payload must be an object"
    )


__all__ = [
    # value-set constants
    "NOTIFICATION_CONSENTS",
    "CLINICIAN_ROLE_KINDS",
    "CLIA_COMPLEXITIES",
    "SPECIMEN_TYPES",
    "LAB_ORDER_PRIORITIES",
    "LAB_ORDER_STATUSES",
    "SPECIMEN_STATUSES",
    "SPECIMEN_REJECTED_REASONS",
    "TRANSPORT_LEG_STATUSES",
    "LAB_RESULT_STATUSES",
    "NOTIFICATION_CHANNELS",
    "NOTIFICATION_STATUSES",
    "RETEST_REASONS",
    "RETEST_STATUSES",
    "AUDIT_EVENT_TYPES",
    # helpers
    "assert_version_incremented_by_one",
    # entity assertions
    "assert_patient",
    "assert_clinician",
    "assert_test_panel",
    "assert_lab_order",
    "assert_specimen",
    "assert_transport_leg",
    "assert_lab_result",
    "assert_critical_notification",
    "assert_acknowledgement_receipt",
    "assert_retest_request",
    "assert_compliance_audit_event",
]
