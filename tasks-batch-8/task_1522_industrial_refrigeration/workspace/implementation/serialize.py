"""Per-entity serializers.  Computed fields (SCAFFOLD `source: computed`) are
derived live in calc.py so every read observes the current logical clock.

ChargeAdjustment is the one append-only event entity (common_fields: false):
it serializes `id` and `created_at` only -- no `updated_at`, no `version`.
"""
import calc
from store import db


def facility_out(row):
    total = calc.book_total(row["id"])
    overdue, open_inc, expired, score, band = calc.posture(row["id"])
    return {
        "id": row["id"],
        "name": row["name"],
        "threshold_lbs": row["threshold_lbs"],
        "total_charge_lbs": total,
        "charge_posture": calc.charge_posture(total, row["threshold_lbs"]),
        "psm_program_status": row["psm_program_status"],
        "overdue_inspection_count": overdue,
        "open_incident_count": open_inc,
        "expired_training_count": expired,
        "posture_score": score,
        "compliance_posture": band,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def system_out(row):
    return {
        "id": row["id"],
        "facility_id": row["facility_id"],
        "name": row["name"],
        "design_charge_lbs": row["design_charge_lbs"],
        "condenser_approach_f": row["condenser_approach_f"],
        "min_head_psig": row["min_head_psig"],
        "max_head_psig": row["max_head_psig"],
        "float_head_enabled": row["float_head_enabled"],
        "last_gauge_reading_lbs": row["last_gauge_reading_lbs"],
        "last_gauge_reading_at": row["last_gauge_reading_at"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def equipment_out(row):
    return {
        "id": row["id"],
        "system_id": row["system_id"],
        "tag_number": row["tag_number"],
        "equipment_type": row["equipment_type"],
        "inspection_interval_days": row["inspection_interval_days"],
        "inspection_method": row["inspection_method"],
        "last_completed_at": row["last_completed_at"],
        "last_result": row["last_result"],
        "next_due_at": row["next_due_at"],
        "integrity_status": calc.integrity_status(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def psid_out(row):
    return {
        "id": row["id"],
        "system_id": row["system_id"],
        "doc_type": row["doc_type"],
        "revision_label": row["revision_label"],
        "content_uri": row["content_uri"],
        "status": row["status"],
        "last_reaffirmed_at": row["last_reaffirmed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def adjustment_out(row):
    """Append-only ledger event: id + created_at, never updated_at/version."""
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "facility_id": row["facility_id"],
        "system_id": row["system_id"],
        "adjustment_type": row["adjustment_type"],
        "quantity_lbs": row["quantity_lbs"],
        "rounded_lbs": row["rounded_lbs"],
        "reason": row["reason"],
        "posted_by_employee_id": row["posted_by_employee_id"],
    }


def inspection_out(row):
    return {
        "id": row["id"],
        "equipment_id": row["equipment_id"],
        "due_at": row["due_at"],
        "status": row["status"],
        "result": row["result"],
        "findings": row["findings"],
        "completed_at": row["completed_at"],
        "completed_late": row["completed_late"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def employee_out(row):
    return {
        "id": row["id"],
        "facility_id": row["facility_id"],
        "full_name": row["full_name"],
        "employment_status": row["employment_status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def training_out(row):
    return {
        "id": row["id"],
        "employee_id": row["employee_id"],
        "topic": row["topic"],
        "completed_at": row["completed_at"],
        "expires_at": row["expires_at"],
        "currency": calc.training_currency(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def drill_out(row):
    return {
        "id": row["id"],
        "facility_id": row["facility_id"],
        "drill_type": row["drill_type"],
        "scheduled_start_at": row["scheduled_start_at"],
        "scheduled_end_at": row["scheduled_end_at"],
        "status": row["status"],
        "attendee_employee_ids": row["attendee_employee_ids"],
        "conducted_at": row["conducted_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def pending_action_count(incident_id):
    """Tally of the incident's OPEN corrective actions.

    The state machine pins the arithmetic: create OPEN -> +1, complete -> -1,
    reject back to OPEN -> +1, and verify leaves the count untouched (the
    action was already out of OPEN).  The close gate is a separate, stricter
    check (every action VERIFIED) enforced at the transition site.
    """
    return sum(
        1
        for action in db.corrective_actions.values()
        if action["incident_id"] == incident_id and action["status"] == "OPEN"
    )


def has_unverified_actions(incident_id):
    """The incident close gate: every CorrectiveAction must stand VERIFIED."""
    return any(
        action["incident_id"] == incident_id and action["status"] != "VERIFIED"
        for action in db.corrective_actions.values()
    )


def incident_out(row):
    return {
        "id": row["id"],
        "facility_id": row["facility_id"],
        "equipment_id": row["equipment_id"],
        "severity": row["severity"],
        "description": row["description"],
        "reported_by_employee_id": row["reported_by_employee_id"],
        "investigator_employee_id": row["investigator_employee_id"],
        "status": row["status"],
        "pending_action_count": pending_action_count(row["id"]),
        "reopen_count": row["reopen_count"],
        "source_leak_event_id": row["source_leak_event_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def action_out(row):
    return {
        "id": row["id"],
        "incident_id": row["incident_id"],
        "description": row["description"],
        "assignee_employee_id": row["assignee_employee_id"],
        "due_at": row["due_at"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def audit_out(row):
    return {
        "id": row["id"],
        "facility_id": row["facility_id"],
        "scheduled_start_at": row["scheduled_start_at"],
        "due_at": row["due_at"],
        "lead_auditor": row["lead_auditor"],
        "origin": row["origin"],
        "status": row["status"],
        "findings_count": row["findings_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def contractor_out(row):
    return {
        "id": row["id"],
        "company_name": row["company_name"],
        "safety_score": row["safety_score"],
        "qualification_status": row["qualification_status"],
        "qualified_until": row["qualified_until"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def permit_out(row):
    return {
        "id": row["id"],
        "facility_id": row["facility_id"],
        "system_id": row["system_id"],
        "contractor_id": row["contractor_id"],
        "work_description": row["work_description"],
        "valid_from": row["valid_from"],
        "valid_until": row["valid_until"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def leak_out(row):
    notified_at = row["notified_at"]
    deadline = row["notification_deadline_at"]
    return {
        "id": row["id"],
        "system_id": row["system_id"],
        "estimated_release_lbs": row["estimated_release_lbs"],
        "source_description": row["source_description"],
        "status": row["status"],
        "final_release_lbs": row["final_release_lbs"],
        "confirmed_at": row["confirmed_at"],
        "notification_required": row["final_release_lbs"] is not None
        and calc.notification_required(row["final_release_lbs"]),
        "notification_deadline_at": deadline,
        "notification_status": row["notification_status"],
        "notified_at": notified_at,
        # exactly at the deadline is ON TIME (strict >)
        "late_notification": bool(
            notified_at is not None and deadline is not None and notified_at > deadline
        ),
        "auto_incident_id": row["auto_incident_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }
