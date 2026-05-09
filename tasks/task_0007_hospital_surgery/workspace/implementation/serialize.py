from decimal import Decimal

from db import db
from calc import planned_workload_minutes, actual_workload_minutes, to_decimal


def _common_fields(entity):
    return {
        "id": entity["id"],
        "created_at": entity["created_at"],
        "updated_at": entity["updated_at"],
        "version": entity["version"],
    }


def _audit_common(entity):
    return {
        "id": entity["id"],
        "created_at": entity["created_at"],
    }


def serialize_room(r):
    out = _common_fields(r)
    out.update({
        "room_number": r["room_number"],
        "room_type": r["room_type"],
        "equipment_list": list(r.get("equipment_list", [])),
        "specialty_required": r["specialty_required"],
        "turnover_buffer_minutes": r["turnover_buffer_minutes"],
        "hourly_rate": r["hourly_rate"],
    })
    return out


def serialize_case(c):
    out = _common_fields(c)
    out.update({
        "patient_id": c["patient_id"],
        "surgery_type": c["surgery_type"],
        "specialty_required": c["specialty_required"],
        "priority": c["priority"],
        "pre_op_assessment_attached": c["pre_op_assessment_attached"],
        "informed_consent_verified": c["informed_consent_verified"],
        "planned_start_minute": c.get("planned_start_minute"),
        "planned_end_minute": c.get("planned_end_minute"),
        "scheduled_room_id": c.get("scheduled_room_id"),
        "actual_start_minute": c.get("actual_start_minute"),
        "actual_end_minute": c.get("actual_end_minute"),
        "implant_cost_estimate": c.get("implant_cost_estimate"),
        "implant_cost_actual": c.get("implant_cost_actual"),
        "status": c["status"],
        "rejected_reason": c.get("rejected_reason"),
        "preempted_at_minute": c.get("preempted_at_minute"),
        "preempted_by_case_id": c.get("preempted_by_case_id"),
    })
    return out


def serialize_staff(s):
    out = _common_fields(s)
    out.update({
        "staff_name": s["staff_name"],
        "staff_role": s["staff_role"],
        "qualifications": list(s.get("qualifications", [])),
        "hourly_rate": s["hourly_rate"],
        "shift_start_minute": s["shift_start_minute"],
        "shift_end_minute": s["shift_end_minute"],
        "on_call": s.get("on_call", False),
        "planned_workload_minutes": planned_workload_minutes(s["id"]),
        "actual_workload_minutes": actual_workload_minutes(s["id"]),
    })
    return out


def serialize_assignment(a):
    out = _common_fields(a)
    out.update({
        "case_id": a["case_id"],
        "staff_id": a["staff_id"],
        "role_in_case": a["role_in_case"],
        "assigned_start_minute": a["assigned_start_minute"],
        "assigned_end_minute": a["assigned_end_minute"],
        "status": a["status"],
    })
    return out


def serialize_instrument(s):
    out = _common_fields(s)
    out.update({
        "set_name": s["set_name"],
        "specialty": s["specialty"],
        "sterilization_status": s["sterilization_status"],
        "last_sterilized_at_minute": s.get("last_sterilized_at_minute"),
        "current_case_id": s.get("current_case_id"),
        "cycle_count": s.get("cycle_count", 0),
    })
    return out


def serialize_booking(b):
    out = _common_fields(b)
    out.update({
        "case_id": b["case_id"],
        "instrument_set_id": b["instrument_set_id"],
        "status": b["status"],
    })
    return out


def serialize_settlement(s):
    out = _common_fields(s)
    out.update({
        "case_id": s["case_id"],
        "status": s["status"],
        "estimated_total_amount": s.get("estimated_total_amount"),
        "final_total_amount": s.get("final_total_amount"),
        "line_items": list(s.get("line_items") or []),
        "insurance_split": list(s.get("insurance_split") or []),
        "per_payer_amounts": list(s.get("per_payer_amounts") or []),
        "implant_cost": s.get("implant_cost", 0.0),
        "refund_amount": s.get("refund_amount", 0.0),
        "insurance_pre_auth_reference": s.get("insurance_pre_auth_reference"),
    })
    return out


def serialize_audit(a):
    out = _audit_common(a)
    out.update({
        "actor_role": a["actor_role"],
        "actor_user_id": a["actor_user_id"],
        "entity_type": a["entity_type"],
        "entity_id": a["entity_id"],
        "action": a["action"],
        "payload": dict(a.get("payload") or {}),
        "occurred_at_minute": a["occurred_at_minute"],
    })
    return out
