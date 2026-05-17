"""Serializers turn stored row dicts into PRD-shaped public JSON objects."""
from __future__ import annotations

from typing import Any

from ..clock import iso_format


# ---------------------------------------------------------------------------
# Common-field projection
# ---------------------------------------------------------------------------

def _common_fields(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"id": row["id"], "created_at": iso_format(row["created_at"])}
    if "updated_at" in row:
        out["updated_at"] = iso_format(row["updated_at"])
    if "version" in row:
        out["version"] = row["version"]
    return out


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------

def patient_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common_fields(row),
        "mrn": row["mrn"],
        "full_name": row["full_name"],
        "date_of_birth": row["date_of_birth"],
        "primary_phone_e164": row["primary_phone_e164"],
        "backup_phone_e164": row.get("backup_phone_e164"),
        "notification_consent": row["notification_consent"],
    }


# ---------------------------------------------------------------------------
# Clinician
# ---------------------------------------------------------------------------

def clinician_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common_fields(row),
        "npi": row["npi"],
        "full_name": row["full_name"],
        "role_kind": row["role_kind"],
        "phone_e164": row["phone_e164"],
        "active": row["active"],
    }


# ---------------------------------------------------------------------------
# TestPanel
# ---------------------------------------------------------------------------

def test_panel_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common_fields(row),
        "code": row["code"],
        "name": row["name"],
        "clia_complexity": row["clia_complexity"],
        "specimen_type": row["specimen_type"],
        "stability_minutes": row["stability_minutes"],
        "analytes": row["analytes"],
    }


# ---------------------------------------------------------------------------
# LabOrder
# ---------------------------------------------------------------------------

def lab_order_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common_fields(row),
        "patient_id": row["patient_id"],
        "ordering_provider_id": row["ordering_provider_id"],
        "panel_id": row["panel_id"],
        "priority": row["priority"],
        "status": row["status"],
        "retest_count": row["retest_count"],
        "parent_order_id": row.get("parent_order_id"),
        "ordered_at": iso_format(row["ordered_at"]),
    }


# ---------------------------------------------------------------------------
# Specimen
# ---------------------------------------------------------------------------

def specimen_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common_fields(row),
        "lab_order_id": row["lab_order_id"],
        "collected_by_id": row["collected_by_id"],
        "collected_at": iso_format(row["collected_at"]),
        "received_at": iso_format(row.get("received_at")),
        "rejected_reason": row.get("rejected_reason"),
        "status": row["status"],
    }


# ---------------------------------------------------------------------------
# TransportLeg (immutable except for status flips; only id + created_at)
# ---------------------------------------------------------------------------

def transport_leg_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": iso_format(row["created_at"]),
        "specimen_id": row["specimen_id"],
        "leg_index": row["leg_index"],
        "from_location": row["from_location"],
        "to_location": row["to_location"],
        "departed_at": iso_format(row["departed_at"]),
        "arrived_at": iso_format(row.get("arrived_at")),
        "courier_id": row["courier_id"],
        "status": row["status"],
    }


# ---------------------------------------------------------------------------
# LabResult
# ---------------------------------------------------------------------------

def lab_result_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common_fields(row),
        "lab_order_id": row["lab_order_id"],
        "resulted_by_id": row["resulted_by_id"],
        "released_by_id": row.get("released_by_id"),
        "measurements": row["measurements"],
        "critical_flags": row["critical_flags"],
        "severity_score": row["severity_score"],
        "status": row["status"],
        "resulted_at": iso_format(row["resulted_at"]),
        "released_at": iso_format(row.get("released_at")),
    }


# ---------------------------------------------------------------------------
# CriticalNotification
# ---------------------------------------------------------------------------

def critical_notification_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common_fields(row),
        "lab_result_id": row["lab_result_id"],
        "recipient_clinician_id": row["recipient_clinician_id"],
        "channel": row["channel"],
        "attempt_count": row["attempt_count"],
        "first_sent_at": iso_format(row["first_sent_at"]),
        "ack_deadline_at": iso_format(row["ack_deadline_at"]),
        "status": row["status"],
    }


# ---------------------------------------------------------------------------
# AcknowledgementReceipt (append-only; id + created_at only)
# ---------------------------------------------------------------------------

def ack_receipt_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": iso_format(row["created_at"]),
        "critical_notification_id": row["critical_notification_id"],
        "acknowledged_by_id": row["acknowledged_by_id"],
        "acknowledged_at": iso_format(row["acknowledged_at"]),
        "read_back_text": row["read_back_text"],
        "ack_latency_minutes": row["ack_latency_minutes"],
    }


# ---------------------------------------------------------------------------
# RetestRequest
# ---------------------------------------------------------------------------

def retest_request_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common_fields(row),
        "lab_order_id": row["lab_order_id"],
        "reason": row["reason"],
        "new_lab_order_id": row.get("new_lab_order_id"),
        "status": row["status"],
    }


# ---------------------------------------------------------------------------
# ComplianceAuditEvent (append-only; id + created_at only)
# ---------------------------------------------------------------------------

def audit_event_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": iso_format(row["created_at"]),
        "event_type": row["event_type"],
        "lab_order_id": row["lab_order_id"],
        "actor_id": row["actor_id"],
        "payload": row["payload"],
    }
