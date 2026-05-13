"""Entity -> JSON dict serializers.

We store internal numeric fields as Decimal and timestamps as ISO strings already;
serializers strip any internal markers and ensure money types are JSON-friendly.
"""

from __future__ import annotations

from decimal import Decimal


def _money(x):
    if x is None:
        return None
    if isinstance(x, Decimal):
        return float(x)
    return x


def employee(row: dict) -> dict:
    if not row:
        return None
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "employee_level": row["employee_level"],
        "department_id": row["department_id"],
        "supervisor_id": row.get("supervisor_id"),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def expense_standard(row: dict) -> dict:
    if not row:
        return None
    return {
        "id": row["id"],
        "version": row["version"],
        "effective_from": row["effective_from"],
        "effective_to": row.get("effective_to"),
        "city_tier": row["city_tier"],
        "employee_level": row["employee_level"],
        "lodging_daily_cap": _money(row["lodging_daily_cap"]),
        "per_diem_amount": _money(row["per_diem_amount"]),
        "transportation_daily_cap": _money(row["transportation_daily_cap"]),
        "holiday_multiplier": _money(row.get("holiday_multiplier")),
        "created_at": row["created_at"],
    }


def travel_application(row: dict) -> dict:
    if not row:
        return None
    return {
        "id": row["id"],
        "applicant_id": row["applicant_id"],
        "destination_city": row["destination_city"],
        "destination_tier": row["destination_tier"],
        "travel_scope": row["travel_scope"],
        "purpose": row["purpose"],
        "planned_start": row["planned_start"],
        "planned_end": row["planned_end"],
        "estimated_budget": _money(row["estimated_budget"]),
        "urgent": row.get("urgent", False),
        "status": row["status"],
        "required_chain": row.get("required_chain"),
        "standard_version_pinned": row.get("standard_version_pinned"),
        "total_booked_cost": _money(row.get("total_booked_cost", 0)),
        "rejection_reason": row.get("rejection_reason"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def itinerary_segment(row: dict) -> dict:
    if not row:
        return None
    return {
        "id": row["id"],
        "application_id": row["application_id"],
        "segment_type": row["segment_type"],
        "option_code": row["option_code"],
        "start_at": row["start_at"],
        "end_at": row["end_at"],
        "cost": _money(row["cost"]),
        "status": row["status"],
        "prior_segment_id": row.get("prior_segment_id"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def invoice(row: dict) -> dict:
    if not row:
        return None
    return {
        "id": row["id"],
        "applicant_id": row["applicant_id"],
        "invoice_number": row["invoice_number"],
        "invoice_code": row["invoice_code"],
        "amount": _money(row.get("amount")),
        "invoice_date": row.get("invoice_date"),
        "category": row.get("category"),
        "ocr_status": row["ocr_status"],
        "matched_segment_id": row.get("matched_segment_id"),
        "rejection_reason": row.get("rejection_reason"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def reimbursement_form(row: dict) -> dict:
    if not row:
        return None
    return {
        "id": row["id"],
        "application_id": row["application_id"],
        "applicant_id": row["applicant_id"],
        "status": row["status"],
        "total_claimed": _money(row.get("total_claimed", 0)),
        "total_reimbursable": _money(row.get("total_reimbursable", 0)),
        "total_self_paid": _money(row.get("total_self_paid", 0)),
        "requires_special_approval": row.get("requires_special_approval", False),
        "special_approval_granted": row.get("special_approval_granted", False),
        "correction_round": row.get("correction_round", 0),
        "rejection_reason": row.get("rejection_reason"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def reimbursement_item(row: dict) -> dict:
    if not row:
        return None
    return {
        "id": row["id"],
        "form_id": row["form_id"],
        "invoice_id": row["invoice_id"],
        "category": row["category"],
        "covered_days": row["covered_days"],
        "claimed_amount": _money(row["claimed_amount"]),
        "reimbursable_amount": _money(row.get("reimbursable_amount", 0)),
        "self_paid_amount": _money(row.get("self_paid_amount", 0)),
        "standard_cap_applied": _money(row.get("standard_cap_applied", 0)),
        "matched_segment_id": row.get("matched_segment_id"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def approval_record(row: dict) -> dict:
    if not row:
        return None
    return {
        "id": row["id"],
        "subject_type": row["subject_type"],
        "subject_id": row["subject_id"],
        "actor_id": row["actor_id"],
        "actor_role": row["actor_role"],
        "action": row["action"],
        "comment": row.get("comment"),
        "from_status": row["from_status"],
        "to_status": row["to_status"],
        "created_at": row["created_at"],
    }


def payment(row: dict) -> dict:
    if not row:
        return None
    return {
        "id": row["id"],
        "form_id": row["form_id"],
        "channel": row["channel"],
        "amount": _money(row["amount"]),
        "batch_id": row["batch_id"],
        "status": row["status"],
        "attempt_count": row["attempt_count"],
        "external_ref": row.get("external_ref"),
        "failure_reason": row.get("failure_reason"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def audit_log(row: dict) -> dict:
    if not row:
        return None
    return {
        "id": row["id"],
        "event_type": row["event_type"],
        "subject_type": row["subject_type"],
        "subject_id": row["subject_id"],
        "actor_id": row.get("actor_id"),
        "payload": row.get("payload", {}),
        "created_at": row["created_at"],
    }
