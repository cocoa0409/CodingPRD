"""Serializers for each entity — produce the JSON-ready dict for responses.

Internal storage may carry datetime objects; serializers format them to
ISO strings, and copy out only the documented public fields.
"""

from services.time_util import format_iso


def _common(row):
    return {
        "id": row["id"],
        "created_at": format_iso(row["created_at"]),
        "updated_at": format_iso(row.get("updated_at")),
        "version": row.get("version", 1),
    }


def serialize_client(row):
    return {
        **_common(row),
        "name": row["name"],
        "contact_email": row["contact_email"],
        "contract_id": row.get("contract_id"),
        "deposit_balance_cents": row.get("deposit_balance_cents", 0),
        "outstanding_balance_cents": row.get("outstanding_balance_cents", 0),
    }


def serialize_tester(row):
    return {
        **_common(row),
        "full_name": row["full_name"],
        "qualifications": row.get("qualifications", []),
        "max_concurrent_tasks": row.get("max_concurrent_tasks", 5),
        "active_task_count": row.get("active_task_count", 0),
        "qualification_posture": row.get("qualification_posture", "QUALIFIED"),
    }


def serialize_reviewer(row):
    return {
        **_common(row),
        "full_name": row["full_name"],
        "scope_categories": row.get("scope_categories", []),
    }


def serialize_signatory(row):
    return {
        **_common(row),
        "full_name": row["full_name"],
        "signature_certificate_id": row["signature_certificate_id"],
        "scope_categories": row.get("scope_categories", []),
    }


def serialize_instrument(row):
    return {
        **_common(row),
        "asset_code": row["asset_code"],
        "capabilities": row.get("capabilities", []),
        "calibration_valid_from": format_iso(row["calibration_valid_from"]),
        "calibration_valid_to": format_iso(row["calibration_valid_to"]),
        "status": row.get("status", "AVAILABLE"),
        "usage_minutes_total": row.get("usage_minutes_total", 0),
    }


def serialize_sample(row):
    return {
        **_common(row),
        "client_id": row["client_id"],
        "source_project": row["source_project"],
        "material_category": row["material_category"],
        "specification": row["specification"],
        "witness_sampled": row["witness_sampled"],
        "witness_name": row.get("witness_name"),
        "sample_code": row["sample_code"],
        "handover_record": row["handover_record"],
        "storage_location": row["storage_location"],
        "status": row.get("status", "REGISTERED"),
    }


def serialize_task(row):
    return {
        **_common(row),
        "sample_id": row["sample_id"],
        "test_method": row["test_method"],
        "urgent": row.get("urgent", False),
        "assigned_tester_id": row.get("assigned_tester_id"),
        "instrument_booking_id": row.get("instrument_booking_id"),
        "status": row.get("status", "PENDING_ASSIGNMENT"),
        "retest_count": row.get("retest_count", 0),
        "priority_seq": row.get("priority_seq"),
    }


def serialize_booking(row):
    # InstrumentBooking has no updated_at / version (append-only envelope).
    return {
        "id": row["id"],
        "created_at": format_iso(row["created_at"]),
        "instrument_id": row["instrument_id"],
        "task_id": row["task_id"],
        "slot_start": format_iso(row["slot_start"]),
        "slot_end": format_iso(row["slot_end"]),
        "status": row.get("status", "RESERVED"),
    }


def serialize_record(row):
    return {
        **_common(row),
        "task_id": row["task_id"],
        "tester_id": row["tester_id"],
        "raw_data": row["raw_data"],
        "calculated_result": row.get("calculated_result"),
        "abnormal_flag": row.get("abnormal_flag", False),
        "status": row.get("status", "DRAFT"),
        "supersedes_record_id": row.get("supersedes_record_id"),
    }


def serialize_modification(row):
    return {
        "id": row["id"],
        "created_at": format_iso(row["created_at"]),
        "record_id": row["record_id"],
        "actor_role": row["actor_role"],
        "actor_id": row["actor_id"],
        "field_path": row["field_path"],
        "previous_value": row["previous_value"],
        "new_value": row["new_value"],
        "reason": row["reason"],
    }


def serialize_report(row):
    return {
        **_common(row),
        "task_id": row["task_id"],
        "template_code": row.get("template_code"),
        "reviewer_id": row.get("reviewer_id"),
        "signatory_id": row.get("signatory_id"),
        "signature_payload": row.get("signature_payload"),
        "status": row.get("status", "DRAFTED"),
        "issued_at": format_iso(row.get("issued_at")) if row.get("issued_at") else None,
    }


def serialize_invoice(row):
    return {
        **_common(row),
        "client_id": row["client_id"],
        "line_items": row.get("line_items", []),
        "subtotal_cents": row.get("subtotal_cents", 0),
        "surcharge_total_cents": row.get("surcharge_total_cents", 0),
        "refund_total_cents": row.get("refund_total_cents", 0),
        "package_discount_cents": row.get("package_discount_cents", 0),
        "deposit_applied_cents": row.get("deposit_applied_cents", 0),
        "total_due_cents": row.get("total_due_cents", 0),
        "status": row.get("status", "ISSUED"),
        "paid_at": format_iso(row.get("paid_at")) if row.get("paid_at") else None,
    }


def serialize_audit_event(row):
    return {
        "id": row["id"],
        "created_at": format_iso(row["created_at"]),
        "event_type": row["event_type"],
        "subject_type": row["subject_type"],
        "subject_id": row["subject_id"],
        "actor_role": row["actor_role"],
        "actor_id": row["actor_id"],
        "payload": row.get("payload", {}),
    }
