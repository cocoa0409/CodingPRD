"""Serialize stored records into JSON-ready dicts with computed fields."""
from util import iso_format
from services import compute


def _common(record):
    return {
        "id": record["id"],
        "created_at": iso_format(record["created_at"]),
        "updated_at": iso_format(record["updated_at"]),
        "version": record["version"],
    }


def clinic(c):
    out = _common(c)
    out.update({
        "name": c["name"],
        "exam_room_capacity": c["exam_room_capacity"],
        "surge_threshold": c["surge_threshold"],
        "diversion_threshold": c["diversion_threshold"],
        "avg_provider_minutes_per_esi": c["avg_provider_minutes_per_esi"],
        "self_pay_discount_pct": c["self_pay_discount_pct"],
        "posture": compute.compute_posture(c),
        "active_queue_depth": compute.active_queue_depth(c["id"]),
        "rooms_occupied": compute.rooms_occupied(c["id"]),
        "ops_run_index": c["ops_run_index"],
    })
    return out


def exam_room(r):
    out = _common(r)
    out.update({
        "clinic_id": r["clinic_id"],
        "room_label": r["room_label"],
        "room_type": r["room_type"],
        "status": r["status"],
        "current_visit_id": r["current_visit_id"],
    })
    return out


def provider(p):
    out = _common(p)
    out.update({
        "clinic_id": p["clinic_id"],
        "full_name": p["full_name"],
        "credential": p["credential"],
        "on_shift": p["on_shift"],
        "active_visit_count": _active_visit_count(p["id"]),
        "max_concurrent_visits": p["max_concurrent_visits"],
    })
    return out


def _active_visit_count(provider_id):
    from db import db
    return sum(
        1 for v in db.visits.values()
        if v.get("provider_id") == provider_id and v["clinical_status"] in ("IN_EXAM", "CHARTING")
    )


def queue_entry(q):
    out = _common(q)
    out.update({
        "clinic_id": q["clinic_id"],
        "patient_id": q["patient_id"],
        "arrival_channel": q["arrival_channel"],
        "chief_complaint": q["chief_complaint"],
        "reserved_at": iso_format(q["reserved_at"]),
        "hold_expires_at": iso_format(q["hold_expires_at"]),
        "esi_level": q["esi_level"],
        "airborne_precaution": q["airborne_precaution"],
        "priority_rank": compute.priority_rank(q),
        "estimated_wait_minutes": compute.estimated_wait_minutes(q),
        "triaged_at": iso_format(q["triaged_at"]),
        "status": q["status"],
    })
    return out


def patient(p):
    out = _common(p)
    out.update({
        "queue_entry_id": p["queue_entry_id"],
        "legal_name": p["legal_name"],
        "date_of_birth": p["date_of_birth"],
        "is_minor": p["is_minor"],
        "guarantor_name": p["guarantor_name"],
        "consent_signed": p["consent_signed"],
    })
    return out


def coverage(c):
    out = _common(c)
    out.update({
        "patient_id": c["patient_id"],
        "coverage_type": c["coverage_type"],
        "payer_name": c["payer_name"],
        "member_id": c["member_id"],
        "copay_cents": c["copay_cents"],
        "eligibility_status": c["eligibility_status"],
        "verified_at": iso_format(c["verified_at"]),
    })
    return out


def visit(v):
    subtotal, responsibility = compute.compute_responsibility(v)
    out = _common(v)
    out.update({
        "queue_entry_id": v["queue_entry_id"],
        "patient_id": v["patient_id"],
        "exam_room_id": v["exam_room_id"],
        "provider_id": v["provider_id"],
        "clinical_status": v["clinical_status"],
        "billing_status": v["billing_status"],
        "chart_note": v["chart_note"],
        "acuity_at_rooming": v["acuity_at_rooming"],
        "charges_subtotal_cents": v.get("charges_subtotal_cents", subtotal),
        "patient_responsibility_cents": v.get("patient_responsibility_cents", responsibility),
        "disposition": v["disposition"],
    })
    return out


def charge(c):
    out = _common(c)
    out.update({
        "visit_id": c["visit_id"],
        "cpt_code": c["cpt_code"],
        "amount_cents": c["amount_cents"],
        "source_type": c["source_type"],
        "voided": c["voided"],
    })
    return out


def occ_health_order(o):
    out = _common(o)
    out.update({
        "queue_entry_id": o["queue_entry_id"],
        "order_type": o["order_type"],
        "employer_name": o["employer_name"],
        "scheduled_start": iso_format(o["scheduled_start"]),
        "duration_minutes": o["duration_minutes"],
        "collector_id": o["collector_id"],
        "room_id": o["room_id"],
        "result": o["result"],
        "status": o["status"],
    })
    return out


def referral(r):
    out = _common(r)
    out.update({
        "visit_id": r["visit_id"],
        "destination_facility": r["destination_facility"],
        "transfer_reason": r["transfer_reason"],
        "mode": r["mode"],
        "accepted_at": iso_format(r["accepted_at"]),
        "status": r["status"],
    })
    return out


def discharge_instruction(d):
    out = _common(d)
    out.update({
        "visit_id": d["visit_id"],
        "instructions_text": d["instructions_text"],
        "follow_up_within_days": d["follow_up_within_days"],
        "follow_up_due_at": iso_format(d["follow_up_due_at"]),
        "follow_up_status": d["follow_up_status"],
    })
    return out
